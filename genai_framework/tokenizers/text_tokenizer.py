from langchain.text_splitter import RecursiveCharacterTextSplitter
from .base_tokenizer import BaseTokenizer

class TextTokenizer(BaseTokenizer):
    def __init__(self, chunk_size=500, chunk_overlap=50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap
        )

    def tokenize(self, input_data):
        chunks = self.splitter.split_text(input_data)
        print(f"Tokenized into {len(chunks)} chunks.")
        return chunks

    def detokenize(self, tokens):
        return " ".join(tokens)