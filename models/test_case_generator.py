from connectors.vector_db_connector import VectorDBConnector
from tokenizer.text_tokenizer import TextTokenizer
from models.rag_text import RAG_Text
from models.store_embeddings import StoreEmbeddings
from langchain.schema import Document
from langchain.prompts import PromptTemplate
from langchain.chains import SequentialChain, LLMChain
from langchain_openai import ChatOpenAI
from utilities.customlogger import logger
import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

class TestCaseGenerator:
    """
    Handles querying similar test cases and generating new test cases using RAG architecture and LangChain pipeline.
    """

    def __init__(self, vector_db_path="vector_db", chunk_size=500, chunk_overlap=50, use_gpt_embeddings=True):
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

        # Configure GPT model
        self.llm = ChatOpenAI(model="gpt-4", temperature=0.7)

    def query_similar(self, query, k=5, format_filter=None, similarity_threshold=0.8):
        """
        Query the vector database for similar test cases.
        :param query: The query string.
        :param k: Number of similar documents to retrieve.
        :param format_filter: Filter results by format (e.g., 'plain_text', 'bdd').
        :return: Retrieved test cases.
        """
        # Generate the embedding for the query
        query_embedding = self.vector_db_connector.embedding_model.embed_query(query)

        # Use the `is_duplicate` method to handle the core logic of querying
        similar_docs = StoreEmbeddings.is_duplicate(
            vector_db_connector=self.vector_db_connector,
            requirement_embedding=query_embedding,
            similarity_threshold=similarity_threshold,
            format_type=format_filter,
            return_similar=True,  # Ensure we return similar docs instead of a boolean
            k=k
        )

        logger.info(f"Retrieved {len(similar_docs)} test cases matching format: {format_filter or 'any'}.")
        return similar_docs

    def generate_test_case(self, query, k=5, format="plain_text", return_with_prompt=False):
        """
        Generate a test case using the GPT model, incorporating retrieved context.
        :param query: The query string.
        :param k: Number of retrieved documents to use as context.
        :param format: Desired format of the generated test case ('plain_text', 'bdd', 'other').
        :param return_with_prompt: If True, return both the generated test case and the prompt.
        :return: Generated test case, or a tuple (prompt, generated test case) if return_with_prompt is True.
        """
        # Retrieve similar documents
        retrieved_docs = self.query_similar(query, format_filter=format, similarity_threshold=0, k=k)

        if not retrieved_docs:
            logger.warning(
                f"No similar documents found for format: {format}. Generating a test case without any context.")
            context = ""
        else:
            # Log similarity scores for debugging
            logger.info(f"Retrieved {len(retrieved_docs)} similar documents for format: {format}.")
            for result in retrieved_docs:
                similarity_score = result["similarity_score"]
                doc_metadata = result["document"].metadata
                logger.debug(f"Document Metadata: {doc_metadata}, Similarity Score: {similarity_score:.2f}")

            # Check if the highest similarity score is below the threshold (e.g., 0.25)
            highest_similarity = max(result["similarity_score"] for result in retrieved_docs)
            if highest_similarity < 0.25:
                logger.info(f"Highest similarity score is below 0.25 for format: {format}. Generating without context.")
                context = ""
            else:
                # Build the context string from retrieved documents
                context = "\n".join(
                    [
                        f"Requirement: {result['document'].page_content}\n"
                        f"Completion: {result['document'].metadata.get('completion', '')}"
                        for result in retrieved_docs
                    ]
                )

        # Prepare the prompt based on the format
        template = (
            "Here are some similar requirements and their test cases:\n{context}\n\n"
            "Generate a test case in {format} format for the following requirement:\n{query}"
        )
        prompt = template.format(context=context, query=query, format=format)

        try:
            # Generate the test case using the GPT model
            response = self.llm.invoke(prompt)
            generated_text = response.content
        except Exception as e:
            logger.error(f"Error generating test case: {e}")
            raise RuntimeError("Test case generation failed.")

        # Format the output if required
        if format == "bdd":
            generated_text = self._format_bdd(generated_text)
        elif format == "other":
            generated_text = self._format_custom(generated_text)

        logger.info(f"Generated test case in {format} format.")
        logger.debug(f"Generated Test Case: {generated_text}")

        # Store the generated test case in the embedding store
        print(query, generated_text)
        self.add_test_cases([query], [generated_text], format=format)
        #self.store_embeddings.add_embeddings([query], [generated_text], format_type=format)
        logger.info(f"Stored the generated test case in the embedding store for format: {format}.")

        if return_with_prompt:
            return prompt, generated_text
        return generated_text

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

    def add_test_cases(self, requirements, test_cases=None, format="plain_text"):
        """
        Add test cases in the specified format to the vector database.
        :param requirements: List of requirements (text).
        :param test_cases: List of test cases corresponding to the requirements.
        :param format: Format of the test cases (e.g., 'plain_text', 'bdd', 'other').
        :return: List of statuses for each requirement - Added or Already Exist.
        """
        # Validate inputs
        if not requirements or not isinstance(requirements, list):
            raise ValueError("Requirements must be a non-empty list of strings.")
        if test_cases and not isinstance(test_cases, list):
            raise ValueError("Test cases, if provided, must be a list of strings.")

        statuses = []  # To track the status of each requirement
        documents = []

        for i, requirement in enumerate(requirements):
            # Compute embeddings for requirements upfront
            requirement_embedding = self.vector_db_connector.embedding_model.embed_query(requirement)

            # Use the static method from StoreEmbeddings to check for duplicates
            docs = StoreEmbeddings.is_duplicate(self.vector_db_connector, requirement_embedding, format, return_similar=True)
            if len(docs) > 0:
                logger.info(f"Skipping duplicate test case for requirement: {requirement}")
                statuses.append({"requirement": requirement,
                                 "status": f"Already Exist (Similarity: {docs[0].get('similarity_score'):.2f})"})
                continue

            '''if StoreEmbeddings.is_duplicate(self.vector_db_connector, requirement_embedding, format):
                logger.info(f"Skipping duplicate test case for requirement: {requirement}")
                statuses.append({"requirement": requirement, "status": "Already Exist"})
                continue'''

            # Prepare test case and tokenize the requirement
            test_case = test_cases[i] if test_cases and i < len(test_cases) else ""
            chunks = self.text_tokenizer.tokenize(requirement)

            # Prepare documents without including embeddings in the metadata
            for chunk in chunks:
                metadata = {
                    "type": "requirement",
                    "format": format,
                    "completion": test_case,
                }
                documents.append(Document(page_content=chunk, metadata=metadata))

            statuses.append({"requirement": requirement, "status": "Added"})

        if documents:
            # Add documents without embeddings
            self.store_embeddings.add_embeddings(
                [doc.page_content for doc in documents],
                [doc.metadata.get("completion", "") for doc in documents],
                format_type=format
            )
        logger.info(f"Added {len(documents)} test cases to the vector database in {format} format.")

        # Log statuses for debugging
        logger.debug(f"Statuses for requirements: {statuses}")

        return statuses