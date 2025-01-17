from scipy.spatial.distance import cosine
from utilities.customlogger import logger

class FeedbackLoop:
    """
    Handles feedback integration, similarity checks, and accuracy assessment to improve test case generation.
    """

    def __init__(self, store_embeddings):
        """
        Initialize the FeedbackLoop class.
        :param store_embeddings: Instance of StoreEmbeddings for adding feedback to the vector database.
        """
        self.store_embeddings = store_embeddings

    def add_feedback(self, feedbacks, reference_completions=None, format="plain_text"):
        """
        Add feedback to the vector database.
        :param feedbacks: List of feedback text.
        :param reference_completions: List of user-provided completions corresponding to the feedback.
        :param format: Format of the feedback (e.g., 'plain_text', 'bdd').
        :return: List of statuses for the feedbacks.
        """
        if not feedbacks:
            logger.warning("No feedback provided to add.")
            return []

        logger.info("Processing feedback for integration...")
        statuses = self.store_embeddings.add_test_cases(
            requirements=feedbacks,
            test_cases=reference_completions,
            format=format
        )
        logger.info(f"Feedback statuses: {statuses}")
        return statuses

    def promote_feedback(self, feedback_id):
        """
        Promote a feedback entry to a regular requirement if it meets certain criteria.
        :param feedback_id: Unique identifier of the feedback entry in the database.
        :return: Boolean indicating success or failure.
        """
        feedback_doc = self.store_embeddings.vector_db_connector.execute("retrieve", id=feedback_id)
        if not feedback_doc:
            logger.warning(f"Feedback with ID {feedback_id} not found.")
            return False

        feedback_doc.metadata["type"] = "requirement"
        self.store_embeddings.vector_db_connector.execute("update", documents=[feedback_doc])
        logger.info(f"Promoted feedback with ID {feedback_id} to a regular requirement.")
        return True

    def assess_accuracy(self, generated_completion, reference_completion, similarity_threshold=0.8):
        """
        Assess the accuracy of a generated completion by comparing it with the reference completion.
        :param generated_completion: The generated test case.
        :param reference_completion: The reference test case.
        :param similarity_threshold: The threshold for considering the completion accurate.
        :return: A tuple (accuracy_flag, similarity_score).
        """
        if not generated_completion or not reference_completion:
            logger.warning("Generated or reference completion is empty. Cannot assess accuracy.")
            return False, 0.0

        logger.info("Assessing accuracy of generated completion...")
        try:
            generated_embedding = self.store_embeddings.vector_db_connector.embedding_model.embed_query(generated_completion)
            reference_embedding = self.store_embeddings.vector_db_connector.embedding_model.embed_query(reference_completion)

            # Calculate cosine similarity
            similarity_score = 1 - cosine(generated_embedding, reference_embedding)
            logger.debug(f"Calculated similarity score: {similarity_score:.2f}")

            accuracy_flag = similarity_score >= similarity_threshold
            if accuracy_flag:
                logger.info("Generated completion meets the accuracy threshold.")
            else:
                logger.warning("Generated completion does not meet the accuracy threshold.")

            return accuracy_flag, similarity_score
        except Exception as e:
            logger.error(f"Error during accuracy assessment: {str(e)}")
            return False, 0.0

    def process_feedback(self, feedback, generated_completion, reference_completion, format="plain_text"):
        """
        Process feedback by assessing accuracy and adding it to the database if needed.
        :param feedback: The feedback text.
        :param generated_completion: The generated test case.
        :param reference_completion: The reference test case.
        :param format: Format of the feedback (e.g., 'plain_text', 'bdd').
        :return: A dictionary with accuracy results and feedback status.
        """
        logger.info(f"Processing feedback: {feedback}")
        try:
            accuracy_flag, similarity_score = self.assess_accuracy(generated_completion, reference_completion)

            feedback_status = "Not Added"
            if not accuracy_flag:
                logger.info(f"Adding feedback to the database due to low similarity score: {similarity_score:.2f}")
                self.add_feedback([feedback], [reference_completion], format)
                feedback_status = "Added"

            return {
                "accuracy": accuracy_flag,
                "similarity_score": similarity_score,
                "feedback_status": feedback_status
            }
        except Exception as e:
            logger.error(f"Error processing feedback: {str(e)}")
            return {
                "accuracy": False,
                "similarity_score": 0.0,
                "feedback_status": "Error"
            }