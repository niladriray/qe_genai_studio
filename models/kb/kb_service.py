"""KBService — orchestrates ingestion and retrieval for a single Knowledge Base.

Each KB lives in its own filesystem root under `chromadb/kb/<kb_id>/{text,image}`
with two sibling Chroma collections (different embedding dimensions force the
split: 384-d MiniLM for text, 512-d CLIP for images).
"""

from __future__ import annotations

import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import chromadb
from langchain_huggingface import HuggingFaceEmbeddings

from configs import kb_registry, settings_store
from configs.config import Config
from models.kb import loaders
from models.kb import summarizer as summarizer_mod
from models.kb.bm25_index import KBBM25Index
from models.kb.image_embedder import CLIPImageEmbedder
from models.kb.parents_store import ParentsStore
from models.llm_factory import build_llm
from models.retrieval.hybrid_retriever import (
    HybridRetriever, _shape_hits,
)
from tokenizer.text_tokenizer import TextTokenizer
from utilities.customlogger import logger


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_shape_hits = _shape_hits  # re-export for any external consumers


class KBService:
    """Per-KB facade over two Chroma collections (text + image)."""

    _text_embedder_singleton: Optional[HuggingFaceEmbeddings] = None

    def __init__(self, kb_id: str) -> None:
        kb = kb_registry.get_kb(kb_id)
        if kb is None:
            raise ValueError(f"Unknown KB: {kb_id}")
        self.kb: Dict[str, Any] = kb
        self.kb_id: str = kb["id"]

        root: Path = kb_registry.chroma_root(self.kb_id)
        root.mkdir(parents=True, exist_ok=True)
        text_path = root / "text"
        image_path = root / "image"
        text_path.mkdir(exist_ok=True)
        image_path.mkdir(exist_ok=True)

        self._text_client = chromadb.PersistentClient(path=str(text_path))
        self._text_collection = self._text_client.get_or_create_collection(
            name="text",
            metadata={"hnsw:space": "cosine"},
        )
        self._image_client = chromadb.PersistentClient(path=str(image_path))
        self._image_collection = self._image_client.get_or_create_collection(
            name="image",
            metadata={"hnsw:space": "cosine"},
        )

        self._image_embedder: Optional[CLIPImageEmbedder] = None

        # BM25 index sits next to the text collection. Load the pickle if
        # present; bootstrap from Chroma the first time a query arrives for
        # a KB that predates this feature.
        self._bm25 = KBBM25Index(text_path / "bm25.pkl")
        self._bm25.load()

        # Parent-chunk sidecar store for parent-document retrieval.
        self._parents = ParentsStore(text_path / "parents.json")

        # Persistent copies of uploaded files, used by the re-ingest flow to
        # rebuild from source without requiring a re-upload.
        self._uploads_dir = root / "uploads"
        self._uploads_dir.mkdir(parents=True, exist_ok=True)

        self._llm_lock = threading.Lock()
        self._llm_cached = None

        self._retriever: Optional[HybridRetriever] = None

    def _llm(self):
        with self._llm_lock:
            if self._llm_cached is None:
                self._llm_cached = build_llm()
            return self._llm_cached

    def _ensure_bm25_bootstrapped(self) -> None:
        if len(self._bm25) > 0:
            return
        if self._text_collection.count() == 0:
            return
        self._bm25.bootstrap_from_chroma(self._text_collection)

    def _get_retriever(self) -> HybridRetriever:
        if self._retriever is None:
            self._retriever = HybridRetriever(
                chroma_collection=self._text_collection,
                bm25_index=self._bm25,
                text_embedder=self.text_embedder,
                settings_prefix="kb.retrieval",
            )
        return self._retriever

    def _persist_upload(self, file_path: str, file_id: str) -> Optional[Path]:
        """Copy the uploaded file into the KB's uploads directory so we
        can re-ingest later without requiring the user to re-upload."""
        try:
            src = Path(file_path)
            ext = src.suffix or ""
            dest = self._uploads_dir / f"{file_id}{ext}"
            shutil.copyfile(src, dest)
            return dest
        except Exception as e:
            logger.warning(f"KB[{self.kb_id}] persist upload failed: {e}")
            return None

    @property
    def text_embedder(self) -> HuggingFaceEmbeddings:
        cls = type(self)
        if cls._text_embedder_singleton is None:
            cls._text_embedder_singleton = HuggingFaceEmbeddings(model_name=Config.HUGGINGFACE_EMBEDDINGS)
        return cls._text_embedder_singleton

    def _img(self) -> CLIPImageEmbedder:
        if self._image_embedder is None:
            self._image_embedder = CLIPImageEmbedder()
        return self._image_embedder

    def ingest_file(self, file_path: str, mime: Optional[str] = None,
                    source_filename: Optional[str] = None,
                    file_id: Optional[str] = None,
                    persist_source: bool = True,
                    progress_cb: Optional[Callable[[str, int, int], None]] = None
                    ) -> Dict[str, Any]:
        mime = mime or loaders.detect_mime(file_path)
        source = source_filename or Path(file_path).name
        file_id = file_id or uuid.uuid4().hex
        now = _now()

        persisted_path: Optional[Path] = None
        if persist_source:
            persisted_path = self._persist_upload(file_path, file_id)

        base_meta = {
            "kb_id": self.kb_id,
            "kb_name": self.kb.get("name", ""),
            "file_id": file_id,
            "source_file": source,
            "mime_type": mime,
            "created_at": now,
        }

        if loaders.is_image_mime(mime):
            record = self._ingest_image(file_path, base_meta)
        else:
            record = self._ingest_text(file_path, mime, base_meta, progress_cb=progress_cb)

        if persisted_path is not None:
            record["persisted_path"] = str(persisted_path)
        return record

    def _ingest_image(self, file_path: str, base_meta: Dict[str, Any]) -> Dict[str, Any]:
        from PIL import Image

        with Image.open(file_path) as img:
            width, height = img.size
        vec = self._img().embed_image(file_path)
        caption = Path(base_meta["source_file"]).stem.replace("_", " ").replace("-", " ")
        meta = dict(base_meta)
        meta.update({
            "content_type": "image",
            "caption": caption,
            "width": int(width),
            "height": int(height),
        })
        chunk_id = f"{base_meta['file_id']}:0"
        self._image_collection.add(
            embeddings=[vec],
            documents=[base_meta["source_file"]],
            metadatas=[meta],
            ids=[chunk_id],
        )
        record = {
            "file_id": base_meta["file_id"],
            "source_file": base_meta["source_file"],
            "mime_type": base_meta["mime_type"],
            "content_type": "image",
            "chunks": 1,
            "pages": None,
            "added_at": base_meta["created_at"],
        }
        kb_registry.add_file_record(self.kb_id, record)
        logger.info(f"KB[{self.kb_id}] ingested image {base_meta['source_file']}")
        return record

    def _ingest_text(self, file_path: str, mime: str, base_meta: Dict[str, Any],
                     progress_cb: Optional[Callable[[str, int, int], None]] = None
                     ) -> Dict[str, Any]:
        loader = loaders.LOADERS.get(mime)
        if loader is None:
            raise ValueError(f"Unsupported mime type for KB ingestion: {mime}")

        def _pg(stage: str, cur: int, total: int) -> None:
            if progress_cb is not None:
                try:
                    progress_cb(stage, cur, total)
                except Exception:
                    pass

        _pg("loading", 0, 1)
        pieces = loader(file_path)
        file_id = base_meta["file_id"]
        _pg("loaded", len(pieces), len(pieces))

        child_size = int(settings_store.get("kb.chunk.child_size", 500) or 500)
        child_overlap = int(settings_store.get("kb.chunk.child_overlap", 50) or 50)
        parent_size = int(settings_store.get("kb.chunk.parent_size", 1500) or 1500)
        parent_overlap = int(settings_store.get("kb.chunk.parent_overlap", 200) or 200)

        child_tok = TextTokenizer(chunk_size=child_size, chunk_overlap=child_overlap)
        parent_tok = TextTokenizer(chunk_size=parent_size, chunk_overlap=parent_overlap)

        do_summaries = bool(settings_store.get("kb.summarize.enabled", True))
        do_page_sum = do_summaries and bool(settings_store.get("kb.summarize.per_page", True))
        do_file_sum = do_summaries and bool(settings_store.get("kb.summarize.per_file", True))

        ids: List[str] = []
        embeddings: List[List[float]] = []
        docs: List[str] = []
        metas: List[Dict[str, Any]] = []
        parents_to_save: Dict[str, Dict[str, Any]] = {}
        page_summaries: List[Dict[str, Any]] = []
        child_count = 0

        total_pieces = len(pieces)
        for piece_idx, (text, piece_meta) in enumerate(pieces):
            _pg("chunking", piece_idx, total_pieces)
            piece_extras: Dict[str, Any] = {}
            for k, v in (piece_meta or {}).items():
                if isinstance(v, (str, int, float, bool)):
                    piece_extras[k] = v

            parent_chunks = parent_tok.tokenize(text)
            for p_idx, parent_text in enumerate(parent_chunks):
                parent_text = (parent_text or "").strip()
                if not parent_text:
                    continue
                parent_id = f"p:{file_id}:{piece_idx}:{p_idx}"
                parent_meta = {**base_meta, **piece_extras, "content_type": "parent",
                               "parent_id": parent_id}
                parents_to_save[parent_id] = {"text": parent_text, "metadata": parent_meta}

                child_chunks = child_tok.tokenize(parent_text)
                for c_idx, child_text in enumerate(child_chunks):
                    child_text = (child_text or "").strip()
                    if not child_text:
                        continue
                    chunk_id = f"c:{file_id}:{piece_idx}:{p_idx}:{c_idx}"
                    emb = self.text_embedder.embed_query(child_text)
                    meta = {**base_meta, **piece_extras, "content_type": "text",
                            "chunk_id": chunk_id, "parent_id": parent_id}
                    ids.append(chunk_id)
                    embeddings.append(emb)
                    docs.append(child_text)
                    metas.append(meta)
                    child_count += 1

            # Per-page summary — indexed as its own retrievable chunk.
            if do_page_sum and text and text.strip():
                _pg("summarizing_page", piece_idx + 1, total_pieces)
                summary = summarizer_mod.summarize_page(text, self._llm())
                if summary:
                    ps_id = f"ps:{file_id}:{piece_idx}"
                    ps_emb = self.text_embedder.embed_query(summary)
                    ps_meta = {**base_meta, **piece_extras,
                               "content_type": "page_summary", "chunk_id": ps_id}
                    ids.append(ps_id)
                    embeddings.append(ps_emb)
                    docs.append(summary)
                    metas.append(ps_meta)
                    page_summaries.append({
                        "page": piece_extras.get("page") or piece_extras.get("slide") or (piece_idx + 1),
                        "summary": summary,
                    })

        # Per-file executive summary — one big chunk that dominates retrieval
        # for summary-intent questions about the whole file.
        file_summary_text: Optional[str] = None
        if do_file_sum and page_summaries:
            _pg("summarizing_file", total_pieces, total_pieces)
            file_summary_text = summarizer_mod.summarize_file(
                page_summaries, base_meta["source_file"], self._llm()
            )
            if file_summary_text:
                fs_id = f"fs:{file_id}"
                fs_emb = self.text_embedder.embed_query(file_summary_text)
                fs_meta = {**base_meta, "content_type": "file_summary", "chunk_id": fs_id}
                ids.append(fs_id)
                embeddings.append(fs_emb)
                docs.append(file_summary_text)
                metas.append(fs_meta)

        _pg("indexing", total_pieces, total_pieces)
        if ids:
            self._text_collection.add(
                embeddings=embeddings,
                documents=docs,
                metadatas=metas,
                ids=ids,
            )
            self._bm25.add(ids, docs, metas)
        if parents_to_save:
            self._parents.add(parents_to_save)
        _pg("done", total_pieces, total_pieces)

        record = {
            "file_id": file_id,
            "source_file": base_meta["source_file"],
            "mime_type": mime,
            "content_type": "text",
            "chunks": child_count,
            "parents": len(parents_to_save),
            "page_summaries": len(page_summaries),
            "has_file_summary": bool(file_summary_text),
            "pages": len(pieces),
            "added_at": base_meta["created_at"],
        }
        kb_registry.add_file_record(self.kb_id, record)
        logger.info(
            f"KB[{self.kb_id}] ingested {base_meta['source_file']} → "
            f"{child_count} children, {len(parents_to_save)} parents, "
            f"{len(page_summaries)} page summaries, file_summary={bool(file_summary_text)} "
            f"across {len(pieces)} pieces"
        )
        return record

    @staticmethod
    def _scope_where(source_files: Optional[List[str]]) -> Optional[Dict[str, Any]]:
        if not source_files:
            return None
        files = [f for f in source_files if f]
        if not files:
            return None
        if len(files) == 1:
            return {"source_file": files[0]}
        return {"source_file": {"$in": files}}

    def query_text(self, question: str, k: int = 5,
                   source_files: Optional[List[str]] = None,
                   hyde: Optional[bool] = None) -> List[Dict[str, Any]]:
        if self._text_collection.count() == 0 or not question:
            return []
        self._ensure_bm25_bootstrapped()
        where = self._scope_where(source_files)

        results = self._get_retriever().query(
            question=question,
            k=k,
            where=where,
            log_tag=f"KB[{self.kb_id}]",
            hyde=hyde,
        )
        if not results:
            return []

        # Parent-document expansion — KB-specific, so it lives here rather
        # than in the shared retriever.
        if bool(settings_store.get("kb.retrieval.parent_expand", True)):
            needed_pids = {
                (h.get("metadata") or {}).get("parent_id")
                for h in results if (h.get("metadata") or {}).get("parent_id")
            }
            needed_pids.discard(None)
            parent_lookup = (
                self._parents.get_many(list(needed_pids))
                if needed_pids else {}
            )
            for h in results:
                pid = (h.get("metadata") or {}).get("parent_id")
                if pid and pid in parent_lookup:
                    h["parent_id"] = pid
                    h["parent_document"] = (
                        parent_lookup[pid].get("text") or h.get("document", "")
                    )

        return results

    def query_images(self, question: str, k: int = 2,
                     min_similarity: float = 0.22,
                     source_files: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        count = self._image_collection.count()
        if count == 0 or not question:
            return []
        k = max(1, min(k, count))
        emb = self._img().embed_text(question)
        where = self._scope_where(source_files)
        kwargs: Dict[str, Any] = {
            "query_embeddings": [emb],
            "n_results": k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where is not None:
            kwargs["where"] = where
        res = self._image_collection.query(**kwargs)
        hits = _shape_hits(res)
        return [h for h in hits if h.get("similarity", 0.0) >= min_similarity]

    def list_files(self) -> List[Dict[str, Any]]:
        kb = kb_registry.get_kb(self.kb_id)
        return list((kb or {}).get("files", []))

    def delete_file(self, file_id: str, remove_upload: bool = True) -> bool:
        for coll in (self._text_collection, self._image_collection):
            try:
                coll.delete(where={"file_id": file_id})
            except Exception as e:
                logger.warning(f"KB[{self.kb_id}] delete_file {file_id} on {coll.name} failed: {e}")
        try:
            self._bm25.remove_where(lambda m: m.get("file_id") == file_id)
        except Exception as e:
            logger.warning(f"KB[{self.kb_id}] BM25 delete for {file_id} failed: {e}")
        try:
            self._parents.remove_where(lambda m: m.get("file_id") == file_id)
        except Exception as e:
            logger.warning(f"KB[{self.kb_id}] parents delete for {file_id} failed: {e}")
        if remove_upload:
            for ext_file in self._uploads_dir.glob(f"{file_id}.*"):
                try:
                    ext_file.unlink()
                except OSError:
                    pass
        kb_registry.remove_file_record(self.kb_id, file_id)
        return True

    # --- re-ingest ---------------------------------------------------------

    def reingest_all(self, progress_cb: Optional[Callable[[str, int, int], None]] = None) -> Dict[str, Any]:
        """Wipe indexed data for every persisted file in this KB and
        re-run ingest on each from its saved upload. Files without a
        persisted upload are reported as skipped — user must re-upload
        them to benefit from Phase 4 features.
        """
        files = list(self.list_files())
        total = len(files)
        done = 0
        skipped: List[Dict[str, Any]] = []
        reingested: List[Dict[str, Any]] = []
        for f in files:
            file_id = f.get("file_id")
            source = f.get("source_file") or file_id
            if progress_cb:
                try:
                    progress_cb(source or "", done, total)
                except Exception:
                    pass
            # Find persisted upload
            candidate: Optional[Path] = None
            if file_id:
                for ext_file in self._uploads_dir.glob(f"{file_id}.*"):
                    candidate = ext_file
                    break
            if candidate is None or not candidate.exists():
                skipped.append({"file_id": file_id, "source_file": source,
                                 "reason": "no persisted upload"})
                done += 1
                continue
            try:
                self.delete_file(file_id, remove_upload=False)
                rec = self.ingest_file(
                    str(candidate),
                    mime=f.get("mime_type"),
                    source_filename=source,
                    file_id=file_id,
                    persist_source=False,
                )
                reingested.append(rec)
            except Exception as e:
                logger.exception(f"KB[{self.kb_id}] re-ingest failed for {source}: {e}")
                skipped.append({"file_id": file_id, "source_file": source,
                                 "reason": str(e)})
            done += 1
            if progress_cb:
                try:
                    progress_cb(source or "", done, total)
                except Exception:
                    pass
        return {"reingested": reingested, "skipped": skipped, "total": total}
