from genai_framework.connectors import GPTGatewayConnector, DBConnector, SpreadsheetConnector

gpt_connector = GPTGatewayConnector(
    api_base="https://your-azure-api-endpoint",
    api_key="your-api-key",
    deployment_name="gpt-deployment-name"
)
gpt_connector.connect()
response = gpt_connector.execute(prompt="Explain AI in simple terms.")
print(response)
gpt_connector.disconnect()



db_connector = DBConnector(db_url="sqlite:///example.db")
db_connector.connect()
rows = db_connector.execute("SELECT * FROM users")
print(rows)
db_connector.disconnect()



sheet_connector = SpreadsheetConnector(file_path="example.xlsx")
sheet_connector.connect()
data = sheet_connector.execute(sheet_name="Sheet1", operation="read")
print(data)
sheet_connector.disconnect()
