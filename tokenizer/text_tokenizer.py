from langchain.text_splitter import RecursiveCharacterTextSplitter
from tokenizer.base_tokenizer import BaseTokenizer
from utilities.customlogger import logger

class TextTokenizer(BaseTokenizer):
    """
    Handles tokenization and detokenization of text.
    """
    def __init__(self, chunk_size=500, chunk_overlap=50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap
        )

    def tokenize(self, input_data):
        """
        Splits text into chunks based on chunk size and overlap.
        :param input_data: The input text to tokenize.
        :return: List of text chunks.
        """
        chunks = self.splitter.split_text(input_data)
        logger.debug(f"Tokenized into {len(chunks)} chunks.")
        return chunks

    def detokenize(self, tokens):
        """
        Joins a list of tokens into a single text string.
        :param tokens: List of tokens.
        :return: Detokenized text string.
        """
        return " ".join(tokens)