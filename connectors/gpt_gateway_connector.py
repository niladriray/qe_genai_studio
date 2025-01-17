import requests
import os
from connectors.base_connector import BaseConnector
class GPTGatewayConnector(BaseConnector):
    """
    Connector for GPT API through Azure API Gateway.
    """

    def __init__(self, api_base, api_key, deployment_name):
        self.api_base = api_base  # Azure API endpoint
        self.api_key = api_key  # Azure API Key
        self.deployment_name = deployment_name  # Deployment name of GPT model
        self.headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key,
        }
        self.session = None

    def connect(self):
        """Establishes a session."""
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        print("Connected to GPT Gateway via Azure API.")

    def disconnect(self):
        """Closes the session."""
        if self.session:
            self.session.close()
            print("Disconnected from GPT Gateway.")

    def execute(self, prompt, max_tokens=1000):
        """
        Sends a prompt to GPT and retrieves the response.

        Args:
            prompt (str): Input prompt for GPT.
            max_tokens (int): Maximum number of tokens to generate.

        Returns:
            dict: The response JSON from GPT.
        """
        endpoint = f"{self.api_base}/openai/deployments/{self.deployment_name}/chat/completions?api-version=2024-03-01-preview"

        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens
        }

        response = self.session.post(endpoint, json=payload)

        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Error {response.status_code}: {response.text}")
