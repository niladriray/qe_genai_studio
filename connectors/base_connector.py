from abc import ABC, abstractmethod

class BaseConnector(ABC):
    """
    Abstract Base Connector class to define a consistent API for all connectors.
    """

    @abstractmethod
    def connect(self):
        pass

    @abstractmethod
    def disconnect(self):
        pass

    @abstractmethod
    def execute(self, *args, **kwargs):
        pass
