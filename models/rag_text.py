from langchain.schema import Document
import openai
from tokenizer.text_tokenizer import TextTokenizer
from utilities.customlogger import logger


class RAG_Text:
    def __init__(self, vector_db_connector, chunk_size=500, chunk_overlap=50, use_gpt_embeddings=True):
        """
        Initialize the RAG_Text class.
        :param vector_db_connector: Shared instance of VectorDBConnector.
        :param chunk_size: Maximum size of text chunks.
        :param chunk_overlap: Overlap between consecutive text chunks.
        :param use_gpt_embeddings: Flag to determine if GPT should be used for query embeddings.
        """
        self.vector_db_connector = vector_db_connector
        self.text_tokenizer = TextTokenizer(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.use_gpt_embeddings = use_gpt_embeddings

    def add_to_vector_db(self, input_data, metadata=None):
        """
        Tokenize the input data, create embeddings, and store them in the vector database.
        :param input_data: Input text data to add.
        :param metadata: Optional metadata for the documents.
        """
        chunks = self.text_tokenizer.tokenize(input_data)
        documents = [
            Document(page_content=chunk, metadata=metadata if metadata else {})
            for chunk in chunks
        ]
        self.vector_db_connector.execute("add", documents=documents)
        logger.info(f"Added {len(documents)} documents to the vector database.")

    def query_vector_db(self, query, k=5):
        """
        Retrieve top-k similar chunks from the vector database based on a query.
        :param query: The query string to search.
        :param k: Number of top results to retrieve.
        :return: List of retrieved documents.
        """
        if self.use_gpt_embeddings:
            # Use GPT embeddings for querying
            query_embedding = self.vector_db_connector.embedding_model.embed_query(query)
            logger.debug("Using GPT embeddings for querying.")
        else:
            # Use local embeddings for querying
            query_embedding = self.vector_db_connector.embedding_model.embed_query(query)
            logger.debug("Using local embeddings for querying.")

        # Perform the query
        results = self.vector_db_connector.execute("query", query=query_embedding, k=k)
        logger.debug(f"Retrieved {len(results)} relevant chunks.")
        return results

    def generate_with_context(self, query, k=5):
        """
        Use retrieved chunks from the vector database as context for GPT generation.
        :param query: The query for which a response is to be generated.
        :param k: Number of top results to include as context.
        :return: Generated text response.
        """
        retrieved_docs = self.query_vector_db(query, k=k)
        context = "\n".join([doc.page_content for doc in retrieved_docs])

        if not context.strip():
            logger.warning("No relevant context found in the database for the query.")
            return "No relevant context found to generate a response."

        prompt = f"Here is the context from the database:\n{context}\n\nGenerate a response for the query:\n{query}"

        try:
            from configs import settings_store
            response = openai.ChatCompletion.create(
                model=settings_store.get("llm.openai.model", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ]
            )
            generated_text = response["choices"][0]["message"]["content"]
            logger.debug("Generated response using GPT.")
            return generated_text
        except Exception as e:
            logger.error(f"Error during GPT generation: {e}")
            return "An error occurred while generating the response."