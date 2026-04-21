import time
from typing import Optional

from connectors.vector_db_connector import VectorDBConnector
from tokenizer.text_tokenizer import TextTokenizer
from models.rag_text import RAG_Text
from models.store_embeddings import StoreEmbeddings
from models.domain_store import DomainStoreService
from langchain.schema import Document
from configs.config import Config
from configs import settings_store
from utilities.customlogger import logger
from models.llm_factory import build_llm
import domains  # noqa: F401  (triggers profile registration)
from domains.registry import default_profile
import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"


def _build_kb_context(query, mne, kb_ids, profile):
    """Assemble a ``{kb_context}`` block from one or more user Knowledge Bases.

    Returns ``(kb_context_str, metrics_dict)``. The string is either empty
    (no augmentation) or a properly-formatted block ending in ``\n\n`` so
    it drops cleanly into the prompt templates.
    """
    if not kb_ids:
        return "", None
    if not bool(settings_store.get("generate.kb_context.enabled", True)):
        return "", {"skipped": "disabled"}

    # Lazy imports: KB stack only loads when augmentation is actually used.
    from models.kb.kb_service import KBService
    from models.kb.retrieval_utils import resolve_file_scope

    k = int(settings_store.get("generate.kb_context.k", 3) or 3)
    auto_scope = bool(settings_store.get("generate.kb_context.auto_scope_mne", True))
    hyde = bool(settings_store.get("generate.kb_context.hyde", False))

    scope_query = f"{query} {mne}" if mne and mne != "N/A" else (query or "")
    blocks: list = []
    used_kbs: list = []
    total_hits = 0
    ref_idx = 1

    for kb_id in kb_ids:
        try:
            kb = KBService(kb_id)
        except ValueError:
            logger.warning(f"augment_kb: unknown KB id {kb_id!r}, skipping")
            continue
        except Exception as e:
            logger.warning(f"augment_kb: failed to open KB {kb_id!r}: {e}")
            continue

        scope = None
        if auto_scope:
            try:
                scope = resolve_file_scope(scope_query, kb.list_files())
            except Exception as e:
                logger.debug(f"augment_kb: scope resolution failed for {kb_id}: {e}")
                scope = None

        try:
            hits = kb.query_text(query, k=k, source_files=scope, hyde=hyde)
        except Exception as e:
            logger.warning(f"augment_kb: query failed on {kb_id}: {e}")
            continue

        if not hits:
            continue

        used_kbs.append({
            "kb_id": kb_id,
            "kb_name": kb.kb.get("name"),
            "scope": scope,
            "hits": len(hits),
        })
        total_hits += len(hits)

        for hit in hits:
            meta = hit.get("metadata") or {}
            file = meta.get("source_file") or "source"
            page = meta.get("page")
            slide = meta.get("slide")
            if page is not None:
                loc = f" (page {page})"
            elif slide is not None:
                loc = f" (slide {slide})"
            else:
                loc = ""
            body = (hit.get("parent_document") or hit.get("document") or "").strip()
            body = body.replace("\n\n", "\n")
            if len(body) > 700:
                body = body[:700].rstrip() + "…"
            blocks.append(
                f"[K{ref_idx}] {kb.kb.get('name', kb_id)} · {file}{loc}\n{body}"
            )
            ref_idx += 1

    if not blocks:
        return "", {"used_kbs": [], "hits": 0}

    preamble = (
        "## Reference material from external knowledge base\n"
        "Treat the following excerpts as authoritative for application-specific "
        "details (architecture, wireframes, page specs, APIs, business rules). "
        "Use them to inform the output and cite inline as [K1], [K2] when the "
        "reference directly shaped a test / story / script.\n\n"
    )
    kb_context = preamble + "\n\n".join(blocks) + "\n\n"
    return kb_context, {"used_kbs": used_kbs, "hits": total_hits}


class TestCaseGenerator:
    """
    Handles querying similar test cases and generating new test cases using RAG architecture and LangChain pipeline.
    """

    def __init__(self, vector_db_path="vector_db", chunk_size=500, chunk_overlap=50, use_gpt_embeddings=True, profile=None):
        self.profile = profile if profile is not None else default_profile()
        """
        Initialize the TestCaseGenerator class.
        :param vector_db_path: Path to the vector database.
        :param chunk_size: Maximum size of text chunks.
        :param chunk_overlap: Overlap between consecutive text chunks.
        :param use_gpt_embeddings: Whether to use GPT embeddings or local embeddings.
        """
        # Initialize and connect VectorDBConnector
        self.vector_db_connector = VectorDBConnector(db_path=vector_db_path, use_gpt_embeddings=use_gpt_embeddings)
        self.vector_db_connector.connect()

        # Pass the shared connector to dependent classes
        self.text_tokenizer = TextTokenizer(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.store_embeddings = StoreEmbeddings(
            vector_db_connector=self.vector_db_connector,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
        self.rag_text = RAG_Text(
            vector_db_connector=self.vector_db_connector,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            use_gpt_embeddings=use_gpt_embeddings
        )

        # Backend-agnostic chat LLM (OpenAI or Ollama) selected via env vars.
        self.llm = build_llm()

        # Phase 5A: per-domain retrieval facade (hybrid BM25+dense → rerank →
        # optional MMR, plus priority-weighted boost). Falls back to the
        # legacy dense-only path through StoreEmbeddings when the feature
        # flag is flipped off.
        self._domain_store: Optional[DomainStoreService] = None
        self._vector_db_path = vector_db_path

    def _get_domain_store(self) -> DomainStoreService:
        if self._domain_store is None:
            self._domain_store = DomainStoreService(
                profile=self.profile,
                vector_db_connector=self.vector_db_connector,
                db_path=self._vector_db_path,
            )
        return self._domain_store

    def query_similar(self, query, k=5, metadata=None, similarity_threshold=0.8):
        """
        Query the vector database for similar prior examples for this domain.

        Phase 5A: when ``domain.retrieval.hybrid`` is on (default), routes
        through ``DomainStoreService`` which runs the same hybrid BM25 +
        dense + cross-encoder rerank pipeline as the Knowledge Base page.
        When off, falls back to the legacy dense-only path through
        ``StoreEmbeddings.is_duplicate(..., return_similar=True)``.
        """
        metadata = metadata or {}
        use_hybrid = bool(settings_store.get("domain.retrieval.hybrid", True))

        if use_hybrid:
            similar_docs = self._get_domain_store().query_similar(
                query=query,
                k=k,
                metadata=metadata,
                similarity_threshold=similarity_threshold,
            )
        else:
            # Legacy dense-only path — kept behind the flag so operators
            # can A/B compare on their own corpus.
            query_embedding = self.vector_db_connector.embedding_model.embed_query(query)
            similar_docs = StoreEmbeddings.is_duplicate(
                vector_db_connector=self.vector_db_connector,
                requirement_embedding=query_embedding,
                similarity_threshold=similarity_threshold,
                metadata=metadata,
                return_similar=True,
                k=k,
                profile=self.profile,
            )

        logger.info(
            f"Retrieved {len(similar_docs)} {self.profile.target_label.lower()} "
            f"records (hybrid={use_hybrid}) matching format: "
            f"{metadata.get(self.profile.metadata_keys['format']) or 'any'}."
        )
        return similar_docs

    def generate_test_case(self, query, k=5, metadata=None, return_with_prompt=False,
                           augment_kbs=None):
        """
        Generate a test case using the GPT model, incorporating retrieved context and metadata.
        :param query: The query string.
        :param k: Number of retrieved documents to use as context.
        :param metadata: Dictionary containing metadata (e.g., format, mne, tech).
        :param return_with_prompt: If True, return both the generated test case and the prompt.
        :param augment_kbs: Optional list of Knowledge Base ids. For each KB,
            retrieval is auto-scoped by the row's mnemonic against KB
            filenames, and the top-k excerpts are injected as authoritative
            reference material in the prompt.
        :return: Generated test case, or a tuple (prompt, generated test case) if return_with_prompt is True.
        """
        t_total_start = time.perf_counter()
        metrics = {
            "domain": self.profile.name,
            "model": settings_store.get("llm.backend", "openai"),
            "model_name": (settings_store.get("llm.ollama.model") if (settings_store.get("llm.backend") or "").lower() == "ollama"
                           else settings_store.get("llm.openai.model")),
        }

        mkeys = self.profile.metadata_keys
        format_type = metadata.get(mkeys["format"], "plain_text")
        mne = metadata.get(mkeys["mne"], "N/A")
        tech = metadata.get(mkeys["tech"], "N/A")
        completion_key = "completion"

        # --- Phase 1: Retrieval (embed query + ChromaDB search) ---
        t0 = time.perf_counter()
        retrieved_docs = self.query_similar(query, metadata=metadata, similarity_threshold=0, k=k)
        metrics["retrieval_sec"] = round(time.perf_counter() - t0, 3)
        metrics["docs_retrieved"] = len(retrieved_docs)

        target_label = self.profile.target_label
        examples_block = ""
        metrics["context_used"] = False
        if not retrieved_docs:
            logger.warning(
                f"No similar documents found for format: {format_type}. Generating a {target_label.lower()} without any context."
            )
        else:
            logger.info(f"Retrieved {len(retrieved_docs)} similar documents for format: {format_type}.")
            highest_similarity = max(r["similarity_score"] for r in retrieved_docs)
            metrics["top_similarity"] = round(highest_similarity, 4)
            min_ctx = float(settings_store.get("retrieval.min_context_similarity"))
            if highest_similarity < min_ctx:
                logger.info(
                    f"Highest similarity score is below {min_ctx:.2f} for format: {format_type}. Generating without context."
                )
            else:
                seen_pairs = set()
                example_blocks = []
                for result in retrieved_docs:
                    doc = result["document"]
                    req_text = doc.page_content.strip()
                    tc_text = (doc.metadata.get(completion_key) or "").strip()
                    if not tc_text:
                        continue
                    pair_key = (req_text, tc_text)
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)
                    example_blocks.append(
                        f"Example {len(example_blocks) + 1} "
                        f"(similarity: {result['similarity_score']:.2f}, "
                        f"priority: {result.get('feedback_priority', Config.USE_CASE_TG_DEFAULT_PRIORITY):.2f}):\n"
                        f"{self.profile.source_label}:\n{req_text}\n"
                        f"{target_label}:\n{tc_text}"
                    )
                    logger.debug(
                        f"Example metadata: {doc.metadata}, "
                        f"similarity: {result['similarity_score']:.2f}, "
                        f"priority: {result.get('feedback_priority')}"
                    )
                if example_blocks:
                    examples_block = "\n\n".join(example_blocks)
                    metrics["context_used"] = True
                    metrics["examples_count"] = len(example_blocks)

        # --- Phase 2a: Knowledge Base augmentation (Phase 5B) ---
        t0 = time.perf_counter()
        kb_context, kb_context_metrics = _build_kb_context(
            query=query, mne=mne, kb_ids=augment_kbs, profile=self.profile,
        )
        metrics["kb_context_sec"] = round(time.perf_counter() - t0, 3)
        if kb_context_metrics:
            metrics["kb_context"] = kb_context_metrics

        # --- Phase 2b: Prompt assembly ---
        t0 = time.perf_counter()
        template = self.profile.few_shot_template if examples_block else self.profile.bare_template
        prompt = template.format(
            examples=examples_block, query=query, format=format_type,
            mne=mne, tech=tech, kb_context=kb_context,
        )
        metrics["prompt_build_sec"] = round(time.perf_counter() - t0, 3)
        metrics["prompt_len_chars"] = len(prompt)

        # --- Phase 3: LLM invocation ---
        t0 = time.perf_counter()
        try:
            response = self.llm.invoke(prompt)
            generated_text = response.content
        except Exception as e:
            logger.exception(
                f"LLM invocation failed while generating {target_label} "
                f"(domain={self.profile.name}, format={format_type}): {e}"
            )
            raise RuntimeError(
                f"{target_label} generation failed: {type(e).__name__}: {e}"
            ) from e
        metrics["llm_sec"] = round(time.perf_counter() - t0, 3)
        metrics["response_len_chars"] = len(generated_text)

        if format_type == "bdd":
            generated_text = self._format_bdd(generated_text)
        elif format_type == "other":
            generated_text = self._format_custom(generated_text)

        logger.info(f"Generated {target_label.lower()} in {format_type} format.")
        logger.debug(f"Generated {target_label}: {generated_text}")

        # --- Phase 4: Store back into ChromaDB ---
        t0 = time.perf_counter()
        self.add_test_cases(self.profile.use_case_type, [query], [generated_text], [metadata])
        metrics["store_sec"] = round(time.perf_counter() - t0, 3)
        logger.info(f"Stored the generated {target_label.lower()} in the embedding store with metadata: {metadata}.")

        metrics["total_sec"] = round(time.perf_counter() - t_total_start, 3)

        logger.info(
            f"Performance: retrieval={metrics['retrieval_sec']}s, "
            f"prompt_build={metrics['prompt_build_sec']}s, "
            f"llm={metrics['llm_sec']}s, "
            f"store={metrics['store_sec']}s, "
            f"total={metrics['total_sec']}s"
        )

        if return_with_prompt:
            return prompt, generated_text, metrics
        return generated_text, metrics

    def _format_bdd(self, test_case):
        """
        Convert a test case to BDD format.
        :param test_case: The input test case in plain text.
        :return: Test case in BDD format.
        """
        bdd_format = f"Feature: Generated Test Case\n\nScenario: {test_case}\nGiven precondition\nWhen action\nThen expected result"
        return bdd_format

    def _format_custom(self, test_case):
        """
        Convert a test case to a custom format.
        :param test_case: The input test case in plain text.
        :return: Test case in a custom format.
        """
        custom_format = f"### Custom Test Case ###\nRequirement: Custom Format\nDetails: {test_case}\n### End ###"
        return custom_format

    def close(self):
        """
        Disconnect from the vector database.
        """
        self.vector_db_connector.disconnect()

    def add_test_cases(self, use_case, requirements, test_cases=None, metadata=None):
        """
        Add test cases to the vector database.
        :param use_case: Use case name or identifier.
        :param requirements: List of requirements (text).
        :param test_cases: List of test cases corresponding to the requirements.
        :param metadata: List of metadata dictionaries corresponding to the requirements.
        :return: List of statuses for each requirement - Added or Already Exist.
        """
        # Validate inputs
        if not requirements or not isinstance(requirements, list):
            raise ValueError("Requirements must be a non-empty list of strings.")
        if test_cases and not isinstance(test_cases, list):
            raise ValueError("Test cases, if provided, must be a list of strings.")
        if metadata and not isinstance(metadata, list):
            raise ValueError("Metadata, if provided, must be a list of dictionaries.")

        statuses = []  # To track the status of each requirement

        for i, requirement in enumerate(requirements):
            # Prepare metadata for the current requirement
            requirement_metadata = metadata[i] if metadata and i < len(metadata) else {}
            test_case = test_cases[i] if test_cases and i < len(test_cases) else {}

            requirement_metadata.update({
                Config.USE_CASE_LABEL: use_case,
                "completion": test_case,
                "domain": self.profile.name,
            })

            # Compute embeddings for the requirement
            requirement_embedding = self.vector_db_connector.embedding_model.embed_query(requirement)

            # Use the static method from StoreEmbeddings to check for duplicates, including metadata
            existing_docs = StoreEmbeddings.is_duplicate(
                self.vector_db_connector,
                requirement_embedding,
                metadata=requirement_metadata,
                return_similar=True,
                profile=self.profile,
            )

            # Check similarity conditions
            if existing_docs:
                is_similar = False
                for doc in existing_docs:
                    similarity_score = doc.get("similarity_score", 0)
                    doc_metadata = doc.get("document").metadata

                    # Check similarity score and metadata fields
                    if (
                        similarity_score >= self.profile.dedup_similarity_threshold and
                        all(requirement_metadata.get(field) == doc_metadata.get(field)
                            for field in self.profile.dedup_match_fields)
                    ):
                        is_similar = True
                        statuses.append({
                            "requirement": requirement,
                            "status": "Already Exist",
                            "similarity_score": round(float(similarity_score), 2),
                        })
                        logger.info(f"Skipping duplicate {self.profile.target_label.lower()} for {self.profile.source_label.lower()}: {requirement}")
                        break

                if is_similar:
                    continue

            '''USE_CASE_TG_SIMILARITY_CHECK = [0.8, "tech", "fmt", "mne"]
            if existing_docs:
                similarity_score = existing_docs[0].get("similarity_score", 0)
                logger.info(f"Skipping duplicate test case for requirement: {requirement}")
                statuses.append({
                    "requirement": requirement,
                    "status": f"Already Exist (Similarity: {similarity_score:.2f})"
                })
                continue'''




            # Tokenize the requirement into chunks
            chunks = self.text_tokenizer.tokenize(requirement)

            # Create documents for each chunk with metadata
            for chunk in chunks:
                document = Document(page_content=chunk, metadata=requirement_metadata)

                self.store_embeddings.add_embeddings(
                    requirements = [document.page_content],
                    metadata = [document.metadata]
                )

            statuses.append({"requirement": requirement, "status": "Added", "similarity_score": None})

        # Phase 5A: keep the per-domain BM25 sidecar in sync. The add path
        # writes through langchain, which doesn't expose generated ids to
        # us, so we let the domain store re-bootstrap from Chroma on its
        # next query. Cheap at domain-store size.
        if (
            bool(settings_store.get("domain.retrieval.hybrid", True))
            and any(s.get("status") == "Added" for s in statuses)
        ):
            try:
                self._get_domain_store().mark_stale()
            except Exception as e:
                logger.warning(f"BM25 resync after add_test_cases failed: {e}")

        # Log statuses for debugging
        logger.debug(f"Statuses for requirements: {statuses}")

        return statuses

    def save_curated_test_case(self, requirement, test_case, metadata):
        """
        Persist a tester-curated (edited) test case as a new high-priority example.
        This is the write-back half of the feedback loop: curated pairs bias
        future retrieval via the priority field.
        """
        if not requirement or not test_case:
            raise ValueError("Both requirement and test_case are required for curation.")
        curated_metadata = dict(metadata or {})
        curated_metadata[self.profile.metadata_keys["priority"]] = Config.USE_CASE_TG_CURATED_PRIORITY
        curated_metadata["curated"] = True
        statuses = self.add_test_cases(
            self.profile.use_case_type,
            [requirement],
            [test_case],
            metadata=[curated_metadata],
        )
        logger.info(f"Saved curated test case with metadata: {curated_metadata}")
        return statuses[0] if statuses else {"status": "Error"}

    def update_test_cases(self, requirements, test_cases=None, metadata=None):
        """
        Update existing test cases in the vector database. If metadata matches, update the record; otherwise, create a new one.

        :param use_case: Use case name or identifier.
        :param requirements: List of requirements (text).
        :param test_cases: List of test cases corresponding to the requirements.
        :param metadata: List of metadata dictionaries corresponding to the requirements.
        :return: List of statuses for each requirement - Updated, Added, or Already Exist.
        """
        # Validate inputs
        if not requirements or not isinstance(requirements, list):
            raise ValueError("Requirements must be a non-empty list of strings.")
        if test_cases and not isinstance(test_cases, list):
            raise ValueError("Test cases, if provided, must be a list of strings.")
        if metadata and not isinstance(metadata, list):
            raise ValueError("Metadata, if provided, must be a list of dictionaries.")

        statuses = []  # To track the status of each requirement

        for i, requirement in enumerate(requirements):
            # Prepare metadata for the current requirement
            requirement_metadata = metadata[i] if metadata and i < len(metadata) else {}
            requirement_metadata[Config.USE_CASE_LABEL] = Config.USE_CASE_TYPE_TG

            # Check if the requirement exists and update if needed
            updated = self.store_embeddings.update_or_create_record(
                requirement, metadata=requirement_metadata, content_updates=test_cases[i] if test_cases else None
            )

            # Set status message based on update result
            status_message = "Updated" if updated else "Added"
            statuses.append({"requirement": requirement, "status": status_message})

        # Log statuses for debugging
        logger.debug(f"Statuses for updated test cases: {statuses}")

        return statuses