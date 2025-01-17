from connectors.vector_db_connector import VectorDBConnector
from tokenizer.text_tokenizer import TextTokenizer
from langchain.schema import Document
from scipy.spatial.distance import cosine
from utilities.customlogger import logger

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
    def is_duplicate(vector_db_connector, requirement_embedding, format_type, similarity_threshold=0.8,
                     return_similar=False, k=5):
        """
        Check if a requirement embedding is similar to any existing embeddings in the database for a specific format,
        or return similar documents.

        :param vector_db_connector: Instance of VectorDBConnector for database operations.
        :param requirement_embedding: Embedding vector of the new requirement.
        :param format_type: The format type to check for duplication (e.g., plain_text, bdd).
        :param similarity_threshold: The similarity threshold to determine duplication.
        :param return_similar: If True, return the list of similar documents instead of a boolean.
        :param k: Number of similar results to retrieve.
        :return: True if a similar requirement exists with the same format (or list of similar docs if return_similar is True).
        """
        if not isinstance(requirement_embedding, list):
            raise ValueError(f"Requirement embedding must be a list, got {type(requirement_embedding)}.")

        # Query for the most similar documents (retrieves text-based documents)
        similar_docs = vector_db_connector.execute("query", query=requirement_embedding, k=k)

        # Process the results to filter by format and calculate similarity
        matching_docs = []
        for doc in similar_docs:
            if doc.metadata.get("format") == format_type:
                # Dynamically compute embedding for the retrieved document
                doc_embedding = vector_db_connector.embedding_model.embed_query(doc.page_content)

                # Calculate cosine similarity
                similarity_score = 1 - cosine(requirement_embedding, doc_embedding)
                logger.debug(f"Calculated similarity score: {similarity_score:.2f} for format: {format_type}")

                # Check if the similarity score meets the threshold
                if similarity_score >= similarity_threshold:
                    matching_docs.append({"document": doc, "similarity_score": similarity_score})
                    print(matching_docs)

        if return_similar:
            return matching_docs

        # Return True if any document meets the threshold
        return len(matching_docs) > 0

    def add_embeddings(self, requirements, completions=None, format_type="plain_text"):
        """
        Add documents to the vector database without storing embeddings in the metadata.
        :param requirements: List of requirements (text).
        :param completions: List of test cases corresponding to the requirements.
        :param format_type: Format of the test cases (e.g., 'plain_text', 'bdd', 'other').
        """
        documents = []

        for i, requirement in enumerate(requirements):
            # Ensure `requirement` is a string
            if not isinstance(requirement, str):
                raise ValueError(f"Requirement must be a string, got {type(requirement)} instead.")

            # Tokenize and prepare for insertion
            completion = completions[i] if completions and i < len(completions) else ""
            chunks = self.text_tokenizer.tokenize(requirement)

            for chunk in chunks:
                metadata = {
                    "type": "requirement",
                    "format": format_type,
                    "completion": completion
                }
                documents.append(Document(page_content=chunk, metadata=metadata))

        if documents:
            self.vector_db_connector.execute("add", documents=documents)
            logger.info(f"Added {len(documents)} documents to the vector database.")
            return len(documents)
        else:
            logger.info("No new documents to add.")
            return 0


    def close(self):
        """ Disconnect from the vector database. """
        self.vector_db_connector.disconnect()