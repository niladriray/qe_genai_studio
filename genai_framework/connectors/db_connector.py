from sqlalchemy import create_engine, text
from base_connector import BaseConnector

class DBConnector(BaseConnector):
    """
    Connector for SQL-based databases using SQLAlchemy.
    """

    def __init__(self, db_url):
        self.db_url = db_url
        self.engine = None
        self.connection = None

    def connect(self):
        """Creates a database connection."""
        self.engine = create_engine(self.db_url)
        self.connection = self.engine.connect()
        print(f"Connected to database: {self.db_url}")

    def disconnect(self):
        """Closes the database connection."""
        if self.connection:
            self.connection.close()
            print("Disconnected from the database.")

    def execute(self, query, params=None):
        """
        Executes a SQL query.

        Args:
            query (str): The SQL query to execute.
            params (dict): Parameters for the query.

        Returns:
            list: Result set as a list of rows.
        """
        if not self.connection:
            raise Exception("Database not connected. Call connect() first.")
        result = self.connection.execute(text(query), params or {})
        return result.fetchall()
