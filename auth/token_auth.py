from auth.auth_provider import AuthProvider


class APIAuth(AuthProvider):

    def __init__(self, x_api_key):
        self.x_api_key = x_api_key

    def get_headers(self):

        return {
            "Authorization":
                f"Bearer {self.token}"
        }