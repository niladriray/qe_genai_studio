from abc import ABC, abstractmethod

class BaseTokenizer(ABC):
    """
    Abstract Base Tokenizer class to define a consistent API for all tokenizer.
    """

    @abstractmethod
    def tokenize(self, input_data):
        """Tokenizes the input data."""
        pass

    @abstractmethod
    def detokenize(self, tokens):
        """Detokenizes the tokens back to the original data."""
        pass