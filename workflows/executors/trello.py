import requests

from . import register
from .base import BaseExecutor

TRELLO_API = "https://api.trello.com/1/cards"
TRELLO_LIST_CARDS_API = "https://api.trello.com/1/lists/{list_id}/cards"


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


def poll_trello_new_cards(config: dict, last_seen_id: str | None):
    """
    Fetches cards from a Trello list and returns cards created since last_seen_id.
    Returns: (list_of_new_card_dicts, new_last_seen_id)
    """
    key = config.get("key")
    token = config.get("token")
    list_id = config.get("list_id")

    if not all([key, token, list_id]):
        return [], last_seen_id

    url = TRELLO_LIST_CARDS_API.format(list_id=list_id)
    params = {"key": key, "token": token, "fields": "name,desc,id,dateLastActivity,url"}

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    cards = resp.json()

    if not cards:
        return [], last_seen_id

    # CRITICAL FIX: Sort cards by ID descending (newest first).
    # Trello IDs contain timestamps, so this ignores visual board position!
    cards.sort(key=lambda c: c["id"], reverse=True)

    # If first poll, set cursor to absolute newest card without firing
    if not last_seen_id:
        return [], cards[0]["id"]

    new_cards = []
    for card in cards:
        if card["id"] == last_seen_id:
            break
        new_cards.append(card)

    # Process oldest to newest
    new_cards.reverse()
    latest_id = cards[0]["id"] if cards else last_seen_id

    return new_cards, latest_id
