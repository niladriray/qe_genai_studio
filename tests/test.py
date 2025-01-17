from models.test_case_generator import TestCaseGenerator
from connectors.vector_db_connector import VectorDBConnector
# Initialize the TestCaseGenerator
import os
import threading
from utilities.customlogger import logger



# Ensure the data directory exists
os.makedirs("./data", exist_ok=True)
generator = TestCaseGenerator(
    vector_db_path="./data/",
    chunk_size=300,
    chunk_overlap=50,
    use_gpt_embeddings=False,
)

# Verify connection (optional debug step)
if generator.vector_db_connector.vector_db is None:
    raise RuntimeError("Vector database failed to connect.")
else:
    logger.debug("Vector database connected successfully!")

# Test Data
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

try:
    # Step 1: Add test cases to the vector database
    #print("Processing plain text test cases...")
    generator.add_test_cases(requirements, plain_text_test_cases, format="plain_text")
    #print("Processing BDD test cases...")
    generator.add_test_cases(requirements, bdd_test_cases, format="bdd")
    #print("Processing 'other' format test cases...")
    generator.add_test_cases(requirements, other_test_cases, format="other")

    # Step 2: Query plain text test cases
    print("\nQuerying plain text test cases...")
    query = "Validate login functionality"
    plain_text_results = generator.query_similar(query, k=3, format_filter="plain_text")
    print(f"\n--- Plain Text Results searching---\n Searching: {query}")
    for doc in plain_text_results:
        print(f"Requirement: {doc['document'].page_content}, Similarity Score: {doc['similarity_score']}")
        print(f"Test Case: {doc['document'].metadata.get('completion', 'No test case available')}")

    # Step 3: Query BDD test cases
    print("\nQuerying BDD test cases...")
    bdd_results = generator.query_similar(query, k=3, format_filter="bdd")
    print(f"\n--- BDD Results ---\n Searching: {query}")
    for doc in bdd_results:
        print(f"Requirement: {doc['document'].page_content}, Similarity Score: {doc['similarity_score']}")
        print(f"Test Case: {doc['document'].metadata.get('completion', 'No test case available')}")


    # Step 4: Query "other" format test cases
    print(f"\nQuerying 'other' format test cases...\n Searching: {query}")
    other_results = generator.query_similar(query, k=3, format_filter="other")
    print("\n--- Other Format Results ---")
    for doc in other_results:
        print(f"Requirement: {doc['document'].page_content}, Similarity Score: {doc['similarity_score']}")
        print(f"Test Case: {doc['document'].metadata.get('completion', 'No test case available')}")

    # Step 5: Debugging metadata
    print("\n--- Debugging Metadata ---")
    for result in plain_text_results + bdd_results + other_results:
        doc = result["document"]  # Access the document from the dictionary
        similarity_score = result["similarity_score"]  # Access the similarity score
        print(f"Metadata: {doc.metadata}, Similarity Score: {similarity_score:.2f}")


    # Step 6: Generate a new test case using GPT
    logger.info("\nGenerating a new test case using GPT...")
    new_requirement = "Check functionality of updating user profile details."
    generated_test_case = generator.generate_test_case(
        query=new_requirement,
        format="bdd",
        k=3,  # Use top-3 similar test cases for context
    )

    logger.info("\n--- Generated Test Case ---")
    print(generated_test_case)


except Exception as e:
    print(f"An error occurred: {e}")

finally:
    try:
        # Clean up generator and vector database
        generator.close()
        generator.vector_db_connector.disconnect()

        # Explicitly terminate any threading-related background tasks
        if hasattr(generator.vector_db_connector.vector_db, "close"):
            generator.vector_db_connector.vector_db.close()

        # Clean up threading state
        threading._shutdown()
    except Exception as cleanup_error:
        print(f"Error during cleanup: {cleanup_error}")
    print("\nTest case generator closed.")