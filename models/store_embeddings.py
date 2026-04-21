from langchain_core import documents

from tokenizer.text_tokenizer import TextTokenizer
from langchain.schema import Document
from scipy.spatial.distance import cosine
from utilities.customlogger import logger
from configs.config import Config

'''
Considerations for Storing Embeddings
	1.	Metadata:
        •	Store additional metadata such as:
        •	Test case format (plain_text, bdd, custom).
        •	Type of document (e.g., requirement, test_case).
        •	Metadata allows for easy filtering during queries.
	2.	Chunk Size and Overlap:
        •	Ensure chunk_size and chunk_overlap are appropriately set to preserve semantic integrity while tokenizing requirements.
	3.	Standardizing Formats:
	    •	Convert all test cases to a standard format before generating embeddings to ensure consistency across the database.
	4.	Versioning:
	    •	Add a version field to metadata to differentiate updated or newly added test cases.
'''


class StoreEmbeddings:
    def __init__(self, vector_db_connector, chunk_size=500, chunk_overlap=50, similarity_threshold=0.8):
        """
        Initialize the StoreEmbeddings class.
        :param vector_db_connector: Shared instance of VectorDBConnector.
        :param chunk_size: Maximum size of text chunks.
        :param chunk_overlap: Overlap between consecutive text chunks.
        :param similarity_threshold: Threshold for identifying similar requirements.
        """
        self.vector_db_connector = vector_db_connector
        self.text_tokenizer = TextTokenizer(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.similarity_threshold = similarity_threshold

    from scipy.spatial.distance import cosine

    from scipy.spatial.distance import cosine

    @staticmethod
    def is_duplicate(vector_db_connector, requirement_embedding, metadata, similarity_threshold=0.8,
                     return_similar=False, k=5, profile=None):
        """
        Check if a requirement embedding is similar to any existing embeddings in the database for a specific format,
        or return similar documents.

        :param metadata:
        :param vector_db_connector: Instance of VectorDBConnector for database operations.
        :param requirement_embedding: Embedding vector of the new requirement.
        :param similarity_threshold: The similarity threshold to determine duplication.
        :param return_similar: If True, return the list of similar documents instead of a boolean.
        :param k: Number of similar results to retrieve.
        :return: True if a similar requirement exists with the same format (or list of similar docs if return_similar is True).
        """
        if not isinstance(requirement_embedding, list):
            raise ValueError(f"Requirement embedding must be a list, got {type(requirement_embedding)}.")

        # Resolve profile lazily so existing callers that don't pass one still work.
        if profile is None:
            from domains.registry import default_profile
            profile = default_profile()

        # Query for the most similar documents (retrieves text-based documents)
        similar_docs = vector_db_connector.execute("query", query=requirement_embedding, k=k)

        # Process the results to filter by format and calculate similarity
        matching_docs = []
        best_match = None
        highest_match_count = -1

        mkeys = profile.metadata_keys
        fmt_key = mkeys["format"]
        mne_key = mkeys["mne"]
        tech_key = mkeys["tech"]
        prio_key = mkeys["priority"]
        profile_domain = profile.name

        for doc in similar_docs:
            # Scope retrieval to the active domain. Legacy records without a
            # "domain" tag default to Config.DEFAULT_DOMAIN so test_case behavior
            # is preserved end-to-end.
            doc_domain = doc.metadata.get("domain", Config.DEFAULT_DOMAIN)
            if doc_domain != profile_domain:
                continue

            # Dynamically compute embedding for the retrieved document
            doc_embedding = vector_db_connector.embedding_model.embed_query(doc.page_content)

            # Calculate cosine similarity
            similarity_score = 1 - cosine(requirement_embedding, doc_embedding)
            logger.debug(f"Calculated similarity score: {similarity_score:.2f} for format: {metadata.get(fmt_key)}.")

            # Skip documents below the similarity threshold
            if similarity_score < similarity_threshold:
                continue

            # Retrieve document metadata. Check format/mne/tech under both the
            # short keys ("fmt"/"mne"/"tech") and legacy long keys stored on
            # older records.
            doc_metadata = doc.metadata
            format_match = doc_metadata.get(fmt_key, doc_metadata.get("format")) == metadata.get(fmt_key)
            mne_match = doc_metadata.get(mne_key) == metadata.get(mne_key)
            tech_match = doc_metadata.get(tech_key) == metadata.get(tech_key)

            metadata_match_count = int(format_match) + int(mne_match) + int(tech_match)

            try:
                feedback_priority = float(doc_metadata.get(prio_key, Config.USE_CASE_TG_DEFAULT_PRIORITY))
            except (TypeError, ValueError):
                feedback_priority = Config.USE_CASE_TG_DEFAULT_PRIORITY

            # Combined rank: similarity dominates, feedback priority nudges.
            combined_score = similarity_score + Config.USE_CASE_TG_PRIORITY_WEIGHT * feedback_priority

            matching_docs.append({
                "document": doc,
                "similarity_score": similarity_score,
                "priority": metadata_match_count,             # kept for backward-compat with callers
                "metadata_match_count": metadata_match_count,
                "feedback_priority": feedback_priority,
                "combined_score": combined_score,
            })

            if metadata_match_count > highest_match_count:
                highest_match_count = metadata_match_count
                best_match = matching_docs[-1]

        if return_similar:
            # Rank by metadata fit first, then by combined (similarity + feedback priority).
            matching_docs.sort(
                key=lambda x: (x["metadata_match_count"], x["combined_score"]),
                reverse=True,
            )
            return matching_docs

        # Return True if any document meets the threshold and is the best match
        return best_match is not None

    def add_embeddings(self, requirements, completions=None, metadata=None):
        """
        Add documents to the vector database, storing requirement as searchable content
        and completion as a separate parameter.

        :param requirements: List of requirements (text).
        :param completions: List of test cases corresponding to the requirements.
        :param metadata: List of metadata dictionaries corresponding to the requirements.
        """
        documents = []

        for i, requirement in enumerate(requirements):
            # Ensure `requirement` is a string
            if not isinstance(requirement, str):
                raise ValueError(f"Requirement must be a string, got {type(requirement)} instead.")

            # Retrieve the corresponding completion and metadata
            completion = completions[i] if completions and i < len(completions) else ""
            requirement_metadata = metadata[i] if metadata and i < len(metadata) else {}

            # Add additional metadata if necessary
            requirement_metadata.update({
               Config.USE_CASE_LABEL : Config.USE_CASE_TYPE_TG
            })

            # Tokenize requirement into chunks
            chunks = self.text_tokenizer.tokenize(requirement)

            # Create documents with requirement as `page_content` and completion as a separate parameter
            for chunk in chunks:
                documents.append(Document(page_content=chunk, metadata=requirement_metadata))

        # Add documents to the vector database if any are created
        if documents:
            self.vector_db_connector.execute("add", documents=documents)
            logger.info(f"Added {len(documents)} documents to the vector database.")
            return len(documents)
        else:
            logger.info("No new documents to add.")
            return 0

    def update_or_create_record(self, requirement, metadata, content_updates=None, k=5):
        """
        Update an existing record in the vector database if metadata matches, otherwise create a new record.

        :param requirement: The requirement text used to find the existing record.
        :param metadata: Metadata dictionary for matching and updating the record.
        :param content_updates: The updated content for the requirement if updating.
        :param k: Number of similar documents to retrieve.
        :return: A boolean indicating whether the record was updated (True) or created (False).
        """
        # Validate inputs
        if not isinstance(requirement, str):
            raise ValueError("Requirement must be a string.")
        if not isinstance(metadata, dict):
            raise ValueError("Metadata must be a dictionary.")

        # Generate embedding for the requirement
        requirement_embedding = self.vector_db_connector.embedding_model.embed_query(requirement)

        # Query for the most similar documents
        similar_docs = self.is_duplicate(
            self.vector_db_connector,
            requirement_embedding=requirement_embedding,
            metadata=metadata,
            return_similar=True,
            k=k
        )

        best_match = None
        best_similarity = 0

        for result in similar_docs:
            doc = result["document"]
            similarity_score = result["similarity_score"]

            if similarity_score >= self.similarity_threshold:
                doc_metadata = doc.metadata

                # Check if all metadata attributes match
                metadata_match = all(doc_metadata.get(key) == metadata.get(key) for key in metadata.keys())

                if metadata_match and similarity_score > best_similarity:
                    best_match = doc
                    best_similarity = similarity_score

        if best_match:
            logger.info(f"Matching document found with similarity score: {best_similarity:.2f}. Updating record.")

            # Delete the existing document before updating
            try:
                self.vector_db_connector.execute("delete", doc_ids=[best_match.id])
                logger.info("Existing document deleted successfully.")
            except Exception as e:
                logger.error(f"Error deleting existing document: {str(e)}")
                raise RuntimeError("Failed to delete the existing document.")

            # Prepare updated metadata and content
            updated_metadata = metadata.copy()

            updated_content = content_updates if content_updates else best_match.page_content

            # Add the updated document back to the vector database
            updated_document = Document(
                page_content=requirement,
                metadata=updated_metadata,
                completion=updated_content,
            )
            self.vector_db_connector.execute("add", documents=[updated_document])
            logger.info("Document updated successfully in the vector database.")
            return True  # Updated existing record

        # If no exact metadata match found, create a new record
        logger.info("No exact metadata match found. Creating a new record.")
        self.add_embeddings([requirement], [content_updates if content_updates else ""], [metadata])
        return False  # Created a new record





    def close(self):
        """ Disconnect from the vector database. """
        self.vector_db_connector.disconnect()