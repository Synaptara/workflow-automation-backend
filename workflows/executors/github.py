import base64

import requests

from . import register
from .base import BaseExecutor


@register("github")
class GitHubExecutor(BaseExecutor):
    def _get_headers(self, access_token: str) -> dict:
        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def execute(self, app_event: str, step_config: dict, context: dict) -> dict:
        access_token = step_config.get("access_token")
        if not access_token:
            raise ValueError(
                "GitHub access token missing. Please connect GitHub in the Vault."
            )

        headers = self._get_headers(access_token)

        try:
            if app_event == "create_repository":
                repo_name = step_config.get("repo_name")
                if not repo_name:
                    raise ValueError("Repository name is required.")

                is_private = str(step_config.get("private", "true")).lower() == "true"
                resp = requests.post(
                    "https://api.github.com/user/repos",
                    headers=headers,
                    json={"name": repo_name, "private": is_private, "auto_init": True},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "status": "success",
                    "repo_url": data.get("html_url"),
                    "clone_url": data.get("clone_url"),
                }

            elif app_event == "push_code":
                repo_full_name = step_config.get("repo_name")
                branch = step_config.get("branch", "main")
                file_path = step_config.get("file_path", "orkflo_log.txt")

                if not repo_full_name:
                    raise ValueError("Repository name (owner/repo) is required.")

                encoded_content = base64.b64encode(
                    step_config.get("content", "Automated entry").encode("utf-8")
                ).decode("utf-8")

                sha = None
                check_resp = requests.get(
                    f"https://api.github.com/repos/{repo_full_name}/contents/{file_path}?ref={branch}",
                    headers=headers,
                    timeout=10,
                )
                if check_resp.ok:
                    sha = check_resp.json().get("sha")

                payload = {
                    "message": step_config.get(
                        "commit_message", "Automated commit via Orkflo"
                    ),
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
                resp.raise_for_status()
                return {
                    "status": "success",
                    "commit_sha": resp.json().get("commit", {}).get("sha"),
                }

            else:
                raise ValueError(f"Unsupported GitHub event: {app_event}")

        except requests.RequestException as e:
            # Safely extract GitHub's specific error message if available
            error_msg = str(e)
            if hasattr(e, "response") and e.response is not None:
                error_msg = e.response.json().get("message", error_msg)
            raise ValueError(f"GitHub API Error: {error_msg}")

    def fetch_test_data(self, app_event: str, step_config: dict) -> dict:
        """Fetches a real issue from the user's repository to use as test variables in the UI."""
        if app_event != "new_issue":
            return {"message": "Test data not available for this event type."}

        repo_name = step_config.get("repo_name")
        access_token = step_config.get("access_token")

        if not repo_name or not access_token:
            raise ValueError(
                "Repository name and connection required to fetch test data."
            )

        try:
            resp = requests.get(
                f"https://api.github.com/repos/{repo_name}/issues?per_page=1&state=all",
                headers=self._get_headers(access_token),
                timeout=10,
            )
            resp.raise_for_status()
            issues = resp.json()

            if not issues:
                return {
                    "issue_title": "Sample Issue",
                    "issue_body": "No real issues found in repo.",
                }

            issue = issues[0]
            return {
                "issue_title": issue.get("title"),
                "issue_body": issue.get("body"),
                "author": issue.get("user", {}).get("login"),
                "repo_name": repo_name,
                "url": issue.get("html_url"),
            }
        except requests.RequestException as e:
            raise ValueError(f"Failed to fetch test data: {str(e)}")

    def normalize_payload(self, app_event: str, raw_payload: dict) -> dict:
        """
        Translates raw deeply-nested webhook payloads into the flat dictionary
        that matches the variables exposed to the frontend UI.
        """
        if app_event == "new_issue":
            issue = raw_payload.get("issue", {})
            repo = raw_payload.get("repository", {})
            user = issue.get("user", {})

            return {
                "event_type": "new_issue",
                "issue_title": issue.get("title", "No Title"),
                "issue_body": issue.get("body", "No Description provided."),
                "author": user.get("login", "Unknown"),
                "repo_name": repo.get("full_name", repo.get("name", "Unknown Repo")),
                "url": issue.get("html_url", ""),
            }

        return raw_payload

    def register_webhook(
        self, app_event: str, step_config: dict, webhook_url: str
    ) -> None:
        if app_event != "new_issue":
            return

        access_token = step_config.get("access_token")
        repo_name = step_config.get("repo_name")

        if not access_token or not repo_name:
            raise ValueError(
                "GitHub trigger requires 'repo_name' and a valid connection."
            )

        headers = self._get_headers(access_token)
        hooks_url = f"https://api.github.com/repos/{repo_name}/hooks"

        try:
            # 1. Check existing hooks to prevent duplicate registrations
            existing_hooks_resp = requests.get(hooks_url, headers=headers, timeout=10)
            if existing_hooks_resp.ok:
                for hook in existing_hooks_resp.json():
                    if hook.get("config", {}).get("url") == webhook_url:
                        return

            # 2. Register the new webhook
            payload = {
                "name": "web",
                "active": True,
                "events": ["issues"],
                "config": {
                    "url": webhook_url,
                    "content_type": "json",
                    "insecure_ssl": "0",
                },
            }
            resp = requests.post(hooks_url, headers=headers, json=payload, timeout=10)
            resp.raise_for_status()

        except requests.RequestException as e:
            raise ValueError(
                f"Failed to register GitHub webhook. Check your repo name and permissions. Error: {str(e)}"
            )

    def match_ingress_event(
        self, app_event: str, event_type: str, payload: dict, step_config: dict
    ) -> bool:
        repo_filter = step_config.get("repository", "").strip()
        incoming_repo = payload.get("repository", {}).get("full_name", "").strip()
        if repo_filter and repo_filter != incoming_repo:
            return False
        return True
