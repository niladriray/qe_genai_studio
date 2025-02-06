from connectors.vector_db_connector import VectorDBConnector
from langchain.schema import Document  # Assuming you're using LangChain Document schema

def initialize_chromadb():
    """
    Initialize ChromaDB and create the default collection.
    """
    try:
        # Initialize the VectorDBConnector
        vector_db_connector = VectorDBConnector(db_path="./data/", use_gpt_embeddings=False)
        vector_db_connector.connect()
        vector_db_connector.delete_collection("delme")

        '''# Create the default collection (if it doesn't exist)
        collection = vector_db_connector.get_collection(collection_name="default")

        # Add initial data (optional)
        initial_documents = [
            Document(page_content="Sample document 1", metadata={"source": "init"}),
            Document(page_content="Sample document 2", metadata={"source": "init"}),
        ]
        vector_db_connector.execute("add", documents=initial_documents)
'''
        print("ChromaDB initialized successfully.")
    except Exception as e:
        print(f"Error initializing ChromaDB: {e}")

if __name__ == "__main__":
    initialize_chromadb()

