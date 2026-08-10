import os
from dotenv import load_dotenv


# Create singleton instance of Config class
class Config:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance.load_config()
        return cls._instance

    def load_config(self):
        # Load the env file from the current directory
        load_dotenv()
        self.X_API_KEY = os.getenv("X_API_KEY")
        self.ENV_CODE = os.getenv("ENV_CODE")
        self.MSSQL_CONNECTION_ODBC = os.getenv("MSSQL_CONNECTION_ODBC")
        self.MYSQL_CONNECTION_STRING = os.getenv("MYSQL_CONNECTION_STRING")

        if self.ENV_CODE == "dev":
            self.BASE_URL = os.getenv("DEV_BASE_URL")
        else:
            self.BASE_URL = os.getenv("PROD_BASE_URL")

settings = Config()