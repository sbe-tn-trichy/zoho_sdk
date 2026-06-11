from ..base import BaseResource

class Accounts(BaseResource):
    def __init__(self, client):
        super().__init__(client, "accounts")
