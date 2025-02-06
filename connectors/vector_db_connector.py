from configs.config import Config
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings
from connectors.base_connector import BaseConnector
from utilities.customlogger import logger
from typing import Optional


class VectorDBConnector(BaseConnector):
    """
    Connector class for handling operations with a vector database.
    """

    def __init__(self, db_path: str = "vector_db", use_gpt_embeddings: bool = True):
        """
        Initialize the connector with the vector database path and embedding configuration.
        :param db_path: Directory to persist the vector database.
        :param use_gpt_embeddings: Flag to determine the embedding model to use (GPT or local).
        """
        self.db_path: str = db_path
        self.use_gpt_embeddings: bool = use_gpt_embeddings
        self.embedding_model = self._initialize_embedding_model()
        self.vector_db: Optional[Chroma] = None

    def _initialize_embedding_model(self):
        """
        Initialize the embedding model based on configuration.
        :return: An instance of the embedding model.
        """
        try:
            if self.use_gpt_embeddings:
                logger.debug("Using GPT-based embeddings (OpenAIEmbeddings).")
                return OpenAIEmbeddings()
            else:
                logger.debug("Using local embeddings (HuggingFaceEmbeddings).")
                return HuggingFaceEmbeddings(model_name=Config.HUGGINGFACE_EMBEDDINGS)
        except Exception as e:
            logger.error(f"Failed to initialize embedding model: {str(e)}")
            raise

    def connect(self):
        """
        Connect to the vector database and initialize the collection.
        """
        try:
            self.vector_db = Chroma(
                persist_directory=self.db_path,
                embedding_function=self.embedding_model
            )
            logger.info(f"Connected to vector database at {self.db_path}.")
        except Exception as e:
            logger.error(f"Failed to connect to vector database: {str(e)}")
            raise

    def disconnect(self):
        """
        Disconnect from the vector database.
        """
        if self.vector_db:
            self.vector_db = None
            logger.info("Disconnected from vector database.")

    def execute(self, operation, *args, **kwargs):
        """
        Execute an operation on the vector database.
        :param operation: The operation to perform ('add', 'query', etc.).
        :param args: Positional arguments for the operation.
        :param kwargs: Keyword arguments for the operation.
        """
        if not self.vector_db:
            raise ConnectionError("Vector database is not connected.")

        if operation == "add":
            documents = kwargs.get("documents")
            if documents:
                unique_documents = []
                for doc in documents:
                    # Check for duplicates
                    existing_docs = self.vector_db.similarity_search(doc.page_content, k=1)
                    if existing_docs:
                        similarity_score = existing_docs[0].metadata.get("similarity", 0)
                        if similarity_score > 0.8:
                            logger.info(f"Duplicate document found: {doc.page_content[:30]}...")
                            continue
                    unique_documents.append(doc)

                if unique_documents:
                    self.vector_db.add_documents(unique_documents)
                    logger.info(f"Added {len(unique_documents)} unique documents to the vector database.")
                else:
                    logger.debug("No new documents to add.")
        elif operation == "query":
            query = kwargs.get("query")
            k = kwargs.get("k", 5)

            query_embedding = self._process_query(query)
            # Get the current number of elements in the index, just checks if the db has data or not
            current_index_size = self.vector_db._collection.count()

            # Handle empty database scenario
            if current_index_size == 0:
                logger.warning("Vector database is empty. No results to return.")
                return []

            # Adjust `k` if it exceeds the index size
            if k > current_index_size:
                logger.warning(
                    f"Number of requested results {k} exceeds the index size {current_index_size}. Adjusting `k` to {current_index_size}.")
                k = current_index_size

            # Perform similarity search using embeddings
            try:
                results = self.vector_db.similarity_search_by_vector(query_embedding, k=k)
                logger.debug(f"Retrieved {len(results)} relevant documents.")
                return results
            except Exception as e:
                logger.error(f"Error during similarity search: {e}")
                raise

        elif operation == "delete":
            doc_ids = kwargs.get("doc_ids")
            if not doc_ids or not isinstance(doc_ids, list):
                raise ValueError("`doc_ids` must be a non-empty list of document IDs to delete.")

            try:
                self.vector_db.delete(doc_ids)
                logger.info(f"Successfully deleted {len(doc_ids)} documents from the vector database.")
            except Exception as e:
                logger.error(f"Error deleting documents: {str(e)}")
                raise

        else:
            raise ValueError(f"Unsupported operation: {operation}")

    def _process_query(self, query):
        """
        Process the query to generate its embedding.
        :param query: The query string, list of strings, or precomputed embedding.
        :return: The embedding vector.
        """
        if isinstance(query, str):
            return self.embedding_model.embed_query(query)
        elif isinstance(query, list) and all(isinstance(x, str) for x in query):
            query_embeddings = [self.embedding_model.embed_query(q) for q in query]
            return [sum(col) / len(col) for col in zip(*query_embeddings)]
        elif isinstance(query, list) and all(isinstance(x, float) for x in query):
            return query
        else:
            raise ValueError("Query must be a string, a list of strings, or a valid embedding (list of floats).")


    def get_collection(self, collection_name: str = "default"):
        """
        Retrieve or create a collection in the vector database.
        :param collection_name: Name of the collection.
        :return: The collection object.
        """
        if not self.vector_db:
            raise RuntimeError("Vector database is not connected. Call `connect()` first.")

        try:
            collection = self.vector_db.get_or_create_collection(name=collection_name)
            logger.info(f"Retrieved or created collection '{collection_name}'.")
            return collection
        except Exception as e:
            logger.error(f"Failed to get or create collection: {str(e)}")
            raise

    def delete_collection(self, docid: list = None):
        self.vector_db.delete(docid)

    def delete_all_documents(self, paskey):
        """
        Delete all documents in the ChromaDB collection.
        """
        if paskey != "delme": return
        if not self.vector_db:
            raise RuntimeError("Vector database is not connected. Call `connect()` first.")
        try:
            # Assuming the vector DB collection has a `delete` method with a wildcard to delete all documents
            collection = self.get_collection()
            collection.delete()
            print("All documents have been deleted from the collection.")
        except Exception as e:
            print(f"Error deleting all documents: {e}")