import requests

from . import register
from .base import BaseExecutor

TRELLO_API = "https://api.trello.com/1/cards"


@register("trello")
class TrelloExecutor(BaseExecutor):
    """config: {"key": str, "token": str, "list_id": str, "name_template": str, "desc_template": str}
    key/token can also be pulled from a stored Credential and merged in before calling execute()."""

    def execute(self, config: dict, context: dict) -> dict:
        name = (
            config.get("name_template", "New card").format(**context)
            if "{" in config.get("name_template", "")
            else config.get("name_template", "New card")
        )
        desc = config.get("desc_template", "")

        params = {
            "key": config["key"],
            "token": config["token"],
            "idList": config["list_id"],
            "name": name,
            "desc": desc,
        }
        resp = requests.post(TRELLO_API, params=params, timeout=5)
        resp.raise_for_status()
        return {"status_code": resp.status_code, "card_id": resp.json().get("id")}
