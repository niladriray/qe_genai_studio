from connectors.vector_db_connector import VectorDBConnector
from tokenizer.text_tokenizer import TextTokenizer
from models.rag_text import RAG_Text
from models.store_embeddings import StoreEmbeddings
from langchain.schema import Document
from configs.config import Config
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

    def query_similar(self, query, k=5, metadata=None, similarity_threshold=0.8):
        """
        Query the vector database for similar test cases.
        :param similarity_threshold:
        :param metadata:
        :param query: The query string.
        :param k: Number of similar documents to retrieve.

        :return: Retrieved test cases.
        """
        # Generate the embedding for the query
        query_embedding = self.vector_db_connector.embedding_model.embed_query(query)

        # Use the `is_duplicate` method to handle the core logic of querying
        similar_docs = StoreEmbeddings.is_duplicate(
            vector_db_connector=self.vector_db_connector,
            requirement_embedding=query_embedding,
            similarity_threshold=similarity_threshold,
            metadata=metadata,
            return_similar=True,  # Ensure we return similar docs instead of a boolean
            k=k
        )

        logger.info(f"Retrieved {len(similar_docs)} test cases matching format: {metadata.get(Config.USE_CASE_TG_METADATA_FMT) or 'any'}.")
        return similar_docs

    def generate_test_case(self, query, k=5, metadata=None, return_with_prompt=False):
        """
        Generate a test case using the GPT model, incorporating retrieved context and metadata.
        :param query: The query string.
        :param k: Number of retrieved documents to use as context.
        :param metadata: Dictionary containing metadata (e.g., format, mne, tech).
        :param return_with_prompt: If True, return both the generated test case and the prompt.
        :return: Generated test case, or a tuple (prompt, generated test case) if return_with_prompt is True.
        """
        # Extract relevant fields from metadata
        format_type = metadata.get(Config.USE_CASE_TG_METADATA_FMT, "plain_text")
        mne = metadata.get(Config.USE_CASE_TG_METADATA_MNE, "N/A")
        tech = metadata.get(Config.USE_CASE_TG_METADATA_TECH, "N/A")

        # Retrieve similar documents
        retrieved_docs = self.query_similar(query, metadata=metadata, similarity_threshold=0, k=k)

        if not retrieved_docs:
            logger.warning(
                f"No similar documents found for format: {format_type}. Generating a test case without any context."
            )
            context = ""
        else:
            # Log similarity scores for debugging
            logger.info(f"Retrieved {len(retrieved_docs)} similar documents for format: {format_type}.")
            for result in retrieved_docs:
                similarity_score = result["similarity_score"]
                doc_metadata = result["document"].metadata
                logger.debug(f"Document Metadata: {doc_metadata}, Similarity Score: {similarity_score:.2f}")

            # Check if the highest similarity score is below the threshold (e.g., 0.25)
            highest_similarity = max(result["similarity_score"] for result in retrieved_docs)
            if highest_similarity < 0.25:
                logger.info(
                    f"Highest similarity score is below 0.25 for format: {format_type}. Generating without context.")
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

        # Prepare the prompt based on the format and metadata
        template = (
            "Here are some similar requirements and their test cases:\n{context}\n\n"
            "Generate a test case in {format} format for the following requirement:\n{query}\n\n"
            "Metadata:\nMNE: {mne}\nTech: {tech}"
        )
        prompt = template.format(context=context, query=query, format=format_type, mne=mne, tech=tech)

        try:
            # Generate the test case using the GPT model
            #response = self.llm.invoke(prompt)
            #generated_text = response.content
            generated_text = '''
                Feature: Generated Test Case

Scenario: Feature: New Customer Online Checking Account Opening
  As a new customer,
  I want to be able to easily open a new checking account online
  So that I can start banking without having to visit a branch

  Scenario: New customer successfully opens a checking account online
    Given I have navigated to the bank's website
    When I click on the "Open New Account" button
    And I select "Checking Account" from the available options
    And I fill in the required information such as name, address, social security number, and initial deposit amount
    And I click the "Submit" button
    Then I should see a confirmation message stating the checking account has been successfully opened
    When I log in to the new account using the provided credentials
    Then I should see that the account balance reflects the initial deposit amount
    And I should see that the account details (name, address etc.) are correctly displayed
    When I log out from the account
    Then I should be logged out successfully
Given precondition
When action
Then expected result
            '''
        except Exception as e:
            logger.error(f"Error generating test case: {e}")
            raise RuntimeError("Test case generation failed.")

        # Format the output if required
        if format_type == "bdd":
            generated_text = self._format_bdd(generated_text)
        elif format_type == "other":
            generated_text = self._format_custom(generated_text)

        logger.info(f"Generated test case in {format_type} format.")
        logger.debug(f"Generated Test Case: {generated_text}")

        # Store the generated test case in the embedding store
        self.add_test_cases(Config.USE_CASE_TYPE_TG, [query], [generated_text], [metadata])
        logger.info(f"Stored the generated test case in the embedding store with metadata: {metadata}.")

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
            })

            # Compute embeddings for the requirement
            requirement_embedding = self.vector_db_connector.embedding_model.embed_query(requirement)

            # Use the static method from StoreEmbeddings to check for duplicates, including metadata
            existing_docs = StoreEmbeddings.is_duplicate(
                self.vector_db_connector,
                requirement_embedding,
                metadata=requirement_metadata,
                return_similar=True
            )

            # Check similarity conditions
            if existing_docs:
                is_similar = False
                for doc in existing_docs:
                    similarity_score = doc.get("similarity_score", 0)
                    doc_metadata = doc.get("document").metadata

                    # Check similarity score and metadata fields
                    if (
                        similarity_score >= Config.USE_CASE_TG_SIMILARITY_CHECK[0] and
                        all(requirement_metadata.get(field) == doc_metadata.get(field)
                            for field in Config.USE_CASE_TG_SIMILARITY_CHECK[1:])
                    ):
                        is_similar = True
                        statuses.append({
                            "requirement": requirement,
                            "status": f"Already Exist (Similarity: {similarity_score:.2f})"
                        })
                        logger.info(f"Skipping duplicate test case for requirement: {requirement}")
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

            statuses.append({"requirement": requirement, "status": "Added"})

        # Log statuses for debugging
        logger.debug(f"Statuses for requirements: {statuses}")

        return statuses

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