import requests


class HttpClient:
    def __init__(self, api_key):
        self.api_key = api_key

    def set_logger(self, logger):
        self.logger = logger

    def get(self, url, accept="application/json, application/zip", file_path=None):
        """
        Perform a GET request with the specified headers.
        """
        headers = {"accept": accept, "X-API-KEY": self.api_key}
        response = requests.get(url, headers=headers, stream=True)
        self.logger.info(f"GET URL - Status Code: {response.status_code}")

        self._handle_response(response)

        content_type = response.headers.get("Content-Type", "")
        self.logger.info(f"Content-Type: {content_type}")
        if content_type in [
            "application/zip",
            "application/octect-stream",
        ] and file_path:
            # Save the ZIP file to the specified path
            with open(file_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        file.write(chunk)
            return f"File saved to {file_path}"
        elif accept == "application/json":
            return response.json()
        else:
            return response.content

    def post(self, url, accept="application/json",file_name=None):
        """
        Perform a POST request with the specified headers and optional file.
        """
        headers = {"accept": accept, "X-API-KEY": self.api_key}

        if file_name:
            with open(file_name, "rb") as file:
                files = {"files": file} if file else None
                response = requests.post(url, headers=headers, files=files)
                self._handle_response(response)
                return response.json() if accept == "application/json" else response.content
        else:
            response = requests.post(url, headers=headers)
            self._handle_response(response)
            return response.json() if accept == "application/json" else response.content

    def _handle_response(self, response):
        """
        Handle HTTP response, raising an exception for non-2xx status codes.
        """
        if not response.ok:
            raise requests.HTTPError(
                f"HTTP Error: {response.status_code} - {response.text}"
            )
