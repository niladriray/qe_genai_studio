from connectors.gpt_gateway_connector import GPTGatewayConnector
from connectors.db_connector import DBConnector
from connectors.spreadsheet_connector import SpreadsheetConnector
from tokenizer.text_tokenizer import TextTokenizer
from tokenizer.image_tokenizer import ImageTokenizer

def main():
    """
    Entry point for the QE-GenAI framework. Demonstrates how to:
    1. Connect to GPT via Azure API Gateway
    2. Connect to a database
    3. Use tokenizer for text and image data
    """

    print("=== QE-GenAI Framework Starting ===")

    # -----------------------------
    # Initialize and Use Connectors
    # -----------------------------

    # 1. GPT Gateway Connector Example
    print("\n--- Connecting to GPT API ---")
    gpt_connector = GPTGatewayConnector(
        api_base="https://your-azure-endpoint",
        api_key="your-azure-api-key",
        deployment_name="gpt-deployment"
    )
    try:
        gpt_connector.connect()
        response = gpt_connector.execute(prompt="Explain AI in simple terms.", max_tokens=50)
        print("GPT Response:", response["choices"][0]["message"]["content"])
    finally:
        gpt_connector.disconnect()

    # 2. Database Connector Example
    print("\n--- Connecting to Database ---")
    db_connector = DBConnector(db_url="sqlite:///example.db")
    try:
        db_connector.connect()
        rows = db_connector.execute("SELECT 'Hello from DB!' AS message")
        print("Database Response:", rows[0][0])
    finally:
        db_connector.disconnect()

    # 3. Spreadsheet Connector Example
    print("\n--- Working with Spreadsheet ---")
    spreadsheet_connector = SpreadsheetConnector(file_path="example.xlsx")
    try:
        spreadsheet_connector.connect()
        sheet_data = spreadsheet_connector.execute(sheet_name="Sheet1", operation="read")
        print("Spreadsheet Data:", sheet_data)
    finally:
        spreadsheet_connector.disconnect()

    # -----------------------------
    # Initialize and Use Tokenizers
    # -----------------------------

    # 4. Text Tokenizer Example
    print("\n--- Tokenizing Text Data ---")
    text_data = "LangChain makes building GenAI apps easy and modular."
    text_tokenizer = TextTokenizer(chunk_size=10, chunk_overlap=0)
    text_tokens = text_tokenizer.tokenize(text_data)
    print("Text Tokens:", text_tokens)

    # 5. Image Tokenizer Example
    print("\n--- Tokenizing Image Data ---")
    image_path = "path/to/image.jpg"  # Replace with an actual image path
    image_tokenizer = ImageTokenizer()
    image_embeddings = image_tokenizer.tokenize(image_path)
    print("Image Embeddings:", image_embeddings)

    print("\n=== QE-GenAI Framework Completed Successfully ===")


if __name__ == "__main__":
    main()