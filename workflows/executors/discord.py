import logging
from typing import Any, Dict

import requests
from decouple import config

from . import register
from .base import BaseExecutor

logger = logging.getLogger(__name__)
DISCORD_API_BASE = "https://discord.com/api/v10"


@register("discord")
class DiscordExecutor(BaseExecutor):
    """
    Industrial-grade executor for outbound Discord REST API operations.
    Supports bot tokens from the encrypted vault or environment fallbacks.
    """

    def _resolve_token(self, step_config: Dict[str, Any]) -> str:
        token = step_config.get("bot_token") or config(
            "DISCORD_BOT_TOKEN", default=None
        )
        if not token:
            raise ValueError("DISCORD_BOT_TOKEN missing in backend environment.")
        return token.strip()

    def _send_request(
        self, method: str, endpoint: str, token: str, payload: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "OrkfloBot/2.0 (WorkflowAutomationBackend)",
        }
        url = f"{DISCORD_API_BASE}{endpoint}"

        try:
            resp = requests.request(
                method=method, url=url, headers=headers, json=payload, timeout=10
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Network error connecting to Discord Gateway: {str(exc)}"
            ) from exc

        if not resp.ok:
            error_details = resp.text
            try:
                error_json = resp.json()
                error_details = error_json.get("message", resp.text)
                if "code" in error_json:
                    error_details += f" (Discord Code: {error_json['code']})"
            except Exception:
                pass

            if resp.status_code == 401:
                raise ValueError(
                    "Discord authentication failed. Re-authenticate Discord in the Vault."
                )
            elif resp.status_code == 403:
                raise ValueError(
                    f"Discord Forbidden: Make sure the Orkflo bot is invited to your server and has permission to view/post in this channel. ({error_details})"
                )
            elif resp.status_code == 404:
                raise ValueError(
                    f"Discord channel or server not found. Check your Channel/Guild ID. ({error_details})"
                )
            elif resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After", "unknown")
                raise RuntimeError(
                    f"Discord Rate Limit Reached. Retry after {retry_after}s: {error_details}"
                )

            raise ValueError(f"Discord API Error ({resp.status_code}): {error_details}")

        return (
            resp.json()
            if resp.content
            else {"status": "success", "status_code": resp.status_code}
        )

    def execute(
        self, app_event: str, step_config: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        token = self._resolve_token(step_config)
        event = (app_event or "send_message").lower()

        if event == "send_message":
            channel_id = str(step_config.get("channel_id") or "").strip()
            if not channel_id:
                raise ValueError("Discord Send Message requires a Channel ID.")

            content = step_config.get("content", "")
            title = step_config.get("embed_title", "")
            description = step_config.get("embed_description", "")
            color_hex = str(step_config.get("embed_color", "5865F2")).replace("#", "")

            payload: Dict[str, Any] = {}
            if content:
                payload["content"] = str(content)

            if title or description:
                try:
                    color_int = int(color_hex, 16) if color_hex else 0x5865F2
                except ValueError:
                    color_int = 0x5865F2

                payload["embeds"] = [
                    {
                        "title": str(title) if title else None,
                        "description": str(description) if description else None,
                        "color": color_int,
                    }
                ]

            if not payload:
                raise ValueError("Discord message content cannot be empty.")

            res = self._send_request(
                "POST", f"/channels/{channel_id}/messages", token, payload
            )
            return {
                "delivered": True,
                "message_id": res.get("id"),
                "channel_id": res.get("channel_id"),
                "timestamp": res.get("timestamp"),
            }

        elif event == "create_channel":
            guild_id = str(step_config.get("guild_id") or "").strip()
            channel_name = str(step_config.get("channel_name") or "").strip()
            private_user_id = str(step_config.get("private_user_id") or "").strip()

            if not guild_id or not channel_name:
                raise ValueError(
                    "Discord Create Channel requires both a Server (Guild) ID and Channel Name."
                )

            channel_type = int(step_config.get("channel_type", 0))
            payload = {
                "name": channel_name.replace(" ", "-").lower(),
                "type": channel_type,
            }

            if private_user_id:
                payload["permission_overwrites"] = [
                    {
                        "id": guild_id,
                        "type": 0,
                        "deny": "1024",
                    },
                    {
                        "id": private_user_id,
                        "type": 1,
                        "allow": "1024",
                    },
                ]

            res = self._send_request(
                "POST", f"/guilds/{guild_id}/channels", token, payload
            )
            return {
                "created": True,
                "channel_id": res.get("id"),
                "channel_name": res.get("name"),
                "guild_id": res.get("guild_id"),
                "is_private": bool(private_user_id),
            }

        elif event == "add_role":
            guild_id = str(step_config.get("guild_id") or "").strip()
            user_id = str(step_config.get("user_id") or "").strip()
            role_id = str(step_config.get("role_id") or "").strip()
            if not all([guild_id, user_id, role_id]):
                raise ValueError(
                    "Discord Assign Role requires Server ID, Target User ID, and Role ID."
                )

            self._send_request(
                "PUT", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}", token
            )
            return {
                "assigned": True,
                "user_id": user_id,
                "role_id": role_id,
                "guild_id": guild_id,
            }

        elif event == "remove_role":
            guild_id = str(step_config.get("guild_id") or "").strip()
            user_id = str(step_config.get("user_id") or "").strip()
            role_id = str(step_config.get("role_id") or "").strip()
            if not all([guild_id, user_id, role_id]):
                raise ValueError(
                    "Discord Remove Role requires Server ID, Target User ID, and Role ID."
                )

            self._send_request(
                "DELETE", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}", token
            )
            return {
                "removed": True,
                "user_id": user_id,
                "role_id": role_id,
                "guild_id": guild_id,
            }

        else:
            raise ValueError(f"Unsupported Discord action event: {app_event}")

    def fetch_test_data(
        self, app_event: str, step_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        token = self._resolve_token(step_config)

        if app_event == "member_join":
            guild_id = str(step_config.get("guild_id") or "").strip()
            if not guild_id:
                raise ValueError("Enter a Server (Guild) ID first to load sample data.")

            res = self._send_request(
                "GET", f"/guilds/{guild_id}/members?limit=1", token
            )
            if not res or not isinstance(res, list):
                return {
                    "event_type": "member_join",
                    "author_id": "1160188996488544306",
                    "author_name": "new_member",
                    "guild_id": guild_id,
                }

            member = res[0]
            user = member.get("user", {})
            return {
                "event_type": "member_join",
                "author_id": user.get("id"),
                "author_name": user.get("username"),
                "guild_id": guild_id,
                "created_at": member.get("joined_at"),
            }

        elif app_event == "new_message":
            channel_id = str(step_config.get("channel_id") or "").strip()
            if not channel_id:
                raise ValueError("Enter a Channel ID first to load sample messages.")

            res = self._send_request(
                "GET", f"/channels/{channel_id}/messages?limit=1", token
            )
            if not res or not isinstance(res, list):
                return {
                    "event_type": "new_message",
                    "channel_id": channel_id,
                    "author_id": "123456789",
                    "author_name": "sample_user",
                    "content": "Sample message for workflow testing",
                }

            msg = res[0]
            author = msg.get("author", {})
            return {
                "event_type": "new_message",
                "message_id": msg.get("id"),
                "channel_id": msg.get("channel_id"),
                "author_id": author.get("id"),
                "author_name": author.get("username"),
                "content": msg.get("content", ""),
                "created_at": msg.get("timestamp"),
            }

        raise ValueError(f"Cannot fetch test data for event: {app_event}")

    def match_ingress_event(
        self, app_event: str, event_type: str, payload: dict, step_config: dict
    ) -> bool:
        target_event = (app_event or "new_message").lower()
        if target_event != event_type:
            return False

        if event_type == "new_message":
            target_channel = str(step_config.get("channel_id", "")).strip()
            incoming_channel = str(payload.get("channel_id", "")).strip()
            if target_channel and target_channel != incoming_channel:
                return False

            target_guild = str(step_config.get("guild_id", "")).strip()
            incoming_guild = str(payload.get("guild_id", "")).strip()
            if target_guild and target_guild != incoming_guild:
                return False

        elif event_type == "member_join":
            target_guild = str(step_config.get("guild_id", "")).strip()
            incoming_guild = str(payload.get("guild_id", "")).strip()
            if target_guild and target_guild != incoming_guild:
                return False

        elif event_type == "reaction_added":
            target_channel = str(step_config.get("channel_id", "")).strip()
            incoming_channel = str(payload.get("channel_id", "")).strip()
            if target_channel and target_channel != incoming_channel:
                return False

            target_emoji = str(step_config.get("emoji", "")).strip()
            incoming_emoji = str(payload.get("emoji", "")).strip()
            if target_emoji and target_emoji != incoming_emoji:
                return False

        return True
