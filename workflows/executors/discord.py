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
            raise ValueError(
                "DISCORD_BOT_TOKEN missing in both step configuration and backend environment."
            )
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
                raise PermissionError("Discord Unauthorized: Invalid bot token.")
            elif resp.status_code == 403:
                raise PermissionError(
                    f"Discord Forbidden: Bot lacks necessary permissions. Details: {error_details}"
                )
            elif resp.status_code == 404:
                raise FileNotFoundError(f"Discord Target Not Found: {error_details}")
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
            channel_id = step_config.get("channel_id")
            if not channel_id:
                raise ValueError("Discord send_message requires 'channel_id'.")

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
                raise ValueError(
                    "Discord send_message payload cannot be empty (requires content or embed)."
                )

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
            guild_id = step_config.get("guild_id")
            channel_name = step_config.get("channel_name")
            private_user_id = step_config.get("private_user_id")

            if not guild_id or not channel_name:
                raise ValueError(
                    "Discord create_channel requires both 'guild_id' and 'channel_name'."
                )

            channel_type = int(step_config.get("channel_type", 0))  # 0 = GUILD_TEXT
            payload = {
                "name": str(channel_name).strip().replace(" ", "-").lower(),
                "type": channel_type,
            }

            # Inject Private Permissions if a user ID is mapped
            if private_user_id:
                payload["permission_overwrites"] = [
                    {
                        "id": str(
                            guild_id
                        ),  # The @everyone role shares the exact ID of the Guild
                        "type": 0,  # 0 = role
                        "deny": "1024",  # Deny VIEW_CHANNEL (0x400)
                    },
                    {
                        "id": str(private_user_id),
                        "type": 1,  # 1 = member
                        "allow": "1024",  # Allow VIEW_CHANNEL (0x400)
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
            guild_id = step_config.get("guild_id")
            user_id = step_config.get("user_id")
            role_id = step_config.get("role_id")
            if not all([guild_id, user_id, role_id]):
                raise ValueError(
                    "Discord add_role requires 'guild_id', 'user_id', and 'role_id'."
                )

            self._send_request(
                "PUT", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}", token
            )
            return {
                "assigned": True,
                "user_id": str(user_id),
                "role_id": str(role_id),
                "guild_id": str(guild_id),
            }

        elif event == "remove_role":
            guild_id = step_config.get("guild_id")
            user_id = step_config.get("user_id")
            role_id = step_config.get("role_id")
            if not all([guild_id, user_id, role_id]):
                raise ValueError(
                    "Discord remove_role requires 'guild_id', 'user_id', and 'role_id'."
                )

            self._send_request(
                "DELETE", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}", token
            )
            return {
                "removed": True,
                "user_id": str(user_id),
                "role_id": str(role_id),
                "guild_id": str(guild_id),
            }

        else:
            raise ValueError(f"Unsupported Discord action event: {app_event}")
