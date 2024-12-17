import openpyxl
from base_connector import BaseConnector
class SpreadsheetConnector(BaseConnector):
    """
    Connector for reading/writing Excel spreadsheets.
    """

    def __init__(self, file_path):
        self.file_path = file_path
        self.workbook = None

    def connect(self):
        """Loads the Excel workbook."""
        self.workbook = openpyxl.load_workbook(self.file_path)
        print(f"Connected to spreadsheet: {self.file_path}")

    def disconnect(self):
        """Saves and closes the Excel workbook."""
        if self.workbook:
            self.workbook.save(self.file_path)
            print("Saved and disconnected from the spreadsheet.")

    def execute(self, sheet_name, operation, data=None):
        """
        Reads or writes data to the specified sheet.

        Args:
            sheet_name (str): Name of the Excel sheet.
            operation (str): 'read' or 'write'.
            data (list): Data to write (optional).

        Returns:
            list: Data read from the sheet.
        """
        sheet = self.workbook[sheet_name]

        if operation == 'read':
            return [[cell.value for cell in row] for row in sheet.rows]

        elif operation == 'write' and data:
            for row in data:
                sheet.append(row)
            print(f"Data written to sheet: {sheet_name}")
        else:
            raise ValueError("Invalid operation. Use 'read' or 'write'.")
