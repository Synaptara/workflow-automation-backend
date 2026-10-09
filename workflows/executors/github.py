import base64

import requests

from . import register
from .base import BaseExecutor


@register("github")
class GitHubExecutor(BaseExecutor):
    def execute(self, app_event: str, step_config: dict, context: dict) -> dict:
        access_token = step_config.get("access_token")
        if not access_token:
            raise ValueError(
                "GitHub access token missing. Please connect GitHub in the Vault."
            )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        if app_event == "create_repository":
            repo_name = step_config.get("repo_name")
            if not repo_name:
                raise ValueError("Repository name is required.")

            is_private = str(step_config.get("private", "true")).lower() == "true"

            payload = {
                "name": repo_name,
                "private": is_private,
                "auto_init": True,
            }

            resp = requests.post(
                "https://api.github.com/user/repos",
                headers=headers,
                json=payload,
                timeout=10,
            )
            if not resp.ok:
                raise ValueError(
                    f"GitHub Error ({resp.status_code}): {resp.json().get('message', resp.text)}"
                )

            data = resp.json()
            return {
                "status": "success",
                "repo_url": data.get("html_url"),
                "clone_url": data.get("clone_url"),
            }

        elif app_event == "push_code":
            repo_full_name = step_config.get("repo_name")  # e.g. "octocat/Hello-World"
            branch = step_config.get("branch", "main")
            commit_message = step_config.get(
                "commit_message", "Automated commit via Orkflo"
            )
            content = step_config.get("content", "Automated entry")
            file_path = step_config.get("file_path", "orkflo_log.txt")

            if not repo_full_name:
                raise ValueError("Repository name (owner/repo) is required.")

            encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")

            # Check if file exists to get SHA for updating
            sha = None
            check_resp = requests.get(
                f"https://api.github.com/repos/{repo_full_name}/contents/{file_path}?ref={branch}",
                headers=headers,
                timeout=10,
            )
            if check_resp.ok:
                sha = check_resp.json().get("sha")

            payload = {
                "message": commit_message,
                "content": encoded_content,
                "branch": branch,
            }
            if sha:
                payload["sha"] = sha

            resp = requests.put(
                f"https://api.github.com/repos/{repo_full_name}/contents/{file_path}",
                headers=headers,
                json=payload,
                timeout=10,
            )
            if not resp.ok:
                raise ValueError(
                    f"GitHub Error ({resp.status_code}): {resp.json().get('message', resp.text)}"
                )

            return {
                "status": "success",
                "commit_sha": resp.json().get("commit", {}).get("sha"),
            }

        else:
            raise ValueError(f"Unsupported GitHub event: {app_event}")

    def register_webhook(
        self, app_event: str, step_config: dict, webhook_url: str
    ) -> None:
        """Programmatically tells GitHub to send events to the Orkflo server."""
        if app_event != "new_issue":
            return

        access_token = step_config.get("access_token")
        repo_name = step_config.get("repo_name")

        if not access_token or not repo_name:
            raise ValueError(
                "GitHub trigger requires 'repo_name' and a valid connection."
            )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        # 1. Check existing hooks to prevent duplicate registrations
        hooks_url = f"https://api.github.com/repos/{repo_name}/hooks"
        existing_hooks_resp = requests.get(hooks_url, headers=headers, timeout=10)

        if existing_hooks_resp.ok:
            for hook in existing_hooks_resp.json():
                if hook.get("config", {}).get("url") == webhook_url:
                    return  # Webhook is already securely attached

        # 2. Register the new webhook
        payload = {
            "name": "web",
            "active": True,
            "events": ["issues"],
            "config": {"url": webhook_url, "content_type": "json", "insecure_ssl": "0"},
        }

        resp = requests.post(hooks_url, headers=headers, json=payload, timeout=10)
        if not resp.ok:
            raise ValueError(f"Failed to register GitHub webhook: {resp.text}")
