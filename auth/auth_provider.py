from abc import ABC
from abc import abstractmethod


class AuthProvider(ABC):

    @abstractmethod
    def get_headers(self) -> dict:
        pass