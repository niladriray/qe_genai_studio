from langchain_community.embeddings import HuggingFaceEmbeddings
from .base_tokenizer import BaseTokenizer


class ImageTokenizer(BaseTokenizer):
    def __init__(self, model_name="openai/clip-vit-base-patch32"):
        self.embeddings = HuggingFaceEmbeddings(model_name=model_name)

    def tokenize(self, input_data):
        embeddings = self.embeddings.embed_documents([input_data])
        print(f"Tokenized image into {len(embeddings)} embeddings.")
        return embeddings

    def detokenize(self, tokens):
        return "Detokenization not applicable for image embeddings."