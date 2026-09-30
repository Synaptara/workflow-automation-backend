import requests

from . import register
from .base import BaseExecutor


@register("notion")
class NotionExecutor(BaseExecutor):
    def execute(self, app_event: str, step_config: dict, context: dict) -> dict:
        api_key = step_config.get("api_key")
        if not api_key:
            raise ValueError("Notion API Key is required.")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }

        if app_event == "create_page":
            database_id = step_config.get("database_id", "").replace("-", "")
            title = step_config.get("title", "Untitled Page")
            content = step_config.get("content", "")

            if not database_id:
                raise ValueError("Database ID is required to create a Notion page.")

            payload = {
                "parent": {"database_id": database_id},
                "properties": {
                    "Name": {  # Default primary title column in Notion databases
                        "title": [{"text": {"content": title}}]
                    }
                },
            }

            if content:
                payload["children"] = [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {"type": "text", "text": {"content": content}}
                            ]
                        },
                    }
                ]

            resp = requests.post(
                "https://api.notion.com/v1/pages",
                headers=headers,
                json=payload,
                timeout=10,
            )

            if not resp.ok:
                raise ValueError(
                    f"Notion API Error ({resp.status_code}): {resp.json().get('message', resp.text)}"
                )

            data = resp.json()
            return {
                "status": "success",
                "page_id": data.get("id"),
                "url": data.get("url"),
            }

        else:
            raise ValueError(f"Unsupported Notion event: {app_event}")
