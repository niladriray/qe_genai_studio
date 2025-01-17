import unittest
from models.test_case_generator import TestCaseGenerator
from utilities.customlogger import Logger

class TestCaseGeneratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """
        Initialize the TestCaseGenerator before running tests.
        """
        cls.generator = TestCaseGenerator(
            vector_db_path="./data/",
            chunk_size=300,
            chunk_overlap=50
        )

    def test_add_test_cases_and_query(self):
        """
        Test adding and querying test cases in different formats.
        """
        # Test data
        requirements = [
            "Verify user login functionality",
            "Validate account balance retrieval",
            "Ensure password reset functionality works as expected"
        ]

        plain_text_test_cases = [
            "1. Input valid username and password.\n2. Click login.\n3. Verify successful login.",
            "1. Access account balance page.\n2. Verify the displayed balance matches the database value.",
            "1. Click 'Forgot Password'.\n2. Enter registered email.\n3. Verify email receipt and reset the password."
        ]

        bdd_test_cases = [
            "Feature: User Login\n\nScenario: Successful login\nGiven a valid username and password\nWhen the user logs in\nThen the dashboard is displayed.",
            "Feature: Account Balance Retrieval\n\nScenario: Correct balance\nGiven a user with a bank account\nWhen they access the balance\nThen the correct amount is shown.",
            "Feature: Password Reset\n\nScenario: Email receipt\nGiven a registered email\nWhen the user requests a password reset\nThen the reset email is sent."
        ]

        other_test_cases = [
            "Custom: Login functionality is tested by entering credentials.",
            "Custom: Balance retrieval verified using backend APIs.",
            "Custom: Password reset email sent verified in the email logs."
        ]

        # Add test cases to the vector database
        self.generator.add_test_cases(requirements, plain_text_test_cases, format="plain_text")
        self.generator.add_test_cases(requirements, bdd_test_cases, format="bdd")
        self.generator.add_test_cases(requirements, other_test_cases, format="other")

        # Query plain text test cases
        query = "Validate login functionality"
        plain_text_results = self.generator.query_similar(query, k=3, format_filter="plain_text")
        self.assertGreater(len(plain_text_results), 0)
        for doc in plain_text_results:
            self.assertIn("plain_text", doc.metadata.get("format"))

        # Query BDD test cases
        bdd_results = self.generator.query_similar(query, k=3, format_filter="bdd")
        self.assertGreater(len(bdd_results), 0)
        for doc in bdd_results:
            self.assertIn("bdd", doc.metadata.get("format"))

        # Query "other" format test cases
        other_results = self.generator.query_similar(query, k=3, format_filter="other")
        self.assertGreater(len(other_results), 0)
        for doc in other_results:
            self.assertIn("other", doc.metadata.get("format"))

    def test_debug_metadata(self):
        """
        Test that metadata is correctly stored and retrievable.
        """
        query = "Validate login functionality"
        results = self.generator.query_similar(query, k=3)

        # Ensure metadata includes the expected keys
        for doc in results:
            self.assertIn("type", doc.metadata)
            self.assertIn("format", doc.metadata)
            self.assertIn("completion", doc.metadata)

    @classmethod
    def tearDownClass(cls):
        """
        Clean up after all tests have run.
        """
        cls.generator.close()


if __name__ == "__main__":
    unittest.main()