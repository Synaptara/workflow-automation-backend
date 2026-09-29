import requests

from . import register
from .base import BaseExecutor

NOTION_API = "https://api.notion.com/v1/pages"


@register("notion")
class NotionExecutor(BaseExecutor):
    """
    config: {"api_key": str, "database_id": str, "title": str, "content": str}
    """

    def execute(self, config: dict, context: dict) -> dict:
        api_key = config.get("api_key")
        database_id = config.get("database_id")
        title = config.get("title", "Automated Entry")
        content = config.get("content", "")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }

        # Notion's strict block structure for creating a database row with a title and paragraph
        payload = {
            "parent": {"database_id": database_id},
            "properties": {
                "Name": {  # Default title column in Notion is usually "Name"
                    "title": [{"text": {"content": title}}]
                }
            },
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": content}}]
                    },
                }
            ],
        }

        resp = requests.post(NOTION_API, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        return {"status_code": resp.status_code, "notion_url": resp.json().get("url")}
