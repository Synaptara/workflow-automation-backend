import base64

import requests

from . import register
from .base import BaseExecutor


class VaultAuthError(ValueError):
    """Raised when a stored OAuth token or API key is expired or revoked."""

    pass


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
            raise VaultAuthError(
                "GitHub is not connected. Open the Integrations Vault to authenticate."
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
            status_code = getattr(e.response, "status_code", None)
            if status_code == 401:
                raise VaultAuthError(
                    "Your GitHub connection has expired or been revoked. Re-authenticate GitHub in the Vault."
                )
            if status_code == 403:
                raise ValueError(
                    "GitHub rate limit reached or your token lacks 'repo' permissions."
                )
            if status_code == 404:
                raise ValueError(
                    "GitHub repository or branch not found. Check the owner/repo format."
                )

            error_msg = "GitHub request failed."
            if getattr(e, "response", None) is not None:
                try:
                    error_msg = e.response.json().get("message", error_msg)
                except ValueError:
                    pass
            raise ValueError(f"GitHub API Error: {error_msg}")

    def fetch_test_data(self, app_event: str, step_config: dict) -> dict:
        if app_event != "new_issue":
            return {"message": "Test data not available for this event type."}

        repo_name = str(step_config.get("repo_name") or "").strip()
        access_token = step_config.get("access_token")

        if not access_token:
            raise VaultAuthError(
                "GitHub is not connected. Open the Integrations Vault to authenticate."
            )
        if not repo_name:
            raise ValueError("Enter a Repository Name (owner/repo) first.")

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
                    "author": "octocat",
                    "repo_name": repo_name,
                    "url": f"https://github.com/{repo_name}/issues/1",
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
            status_code = getattr(e.response, "status_code", None)
            if status_code == 401:
                raise VaultAuthError(
                    "Your GitHub connection has expired. Re-authenticate GitHub in the Vault."
                )
            if status_code == 404:
                raise ValueError(
                    f"Repository '{repo_name}' not found or you don't have access to it."
                )
            raise ValueError("Could not fetch issues from GitHub. Please try again.")

    def normalize_payload(self, app_event: str, raw_payload: dict) -> dict:
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

        repo_name = str(step_config.get("repo_name") or "").strip()
        if not repo_name:
            raise ValueError("GitHub trigger requires a Repository Name (owner/repo).")

        access_token = step_config.get("access_token")
        if not access_token:
            raise VaultAuthError(
                "GitHub token missing or expired. Re-authenticate GitHub in the Integrations Vault."
            )

        headers = self._get_headers(access_token)
        hooks_url = f"https://api.github.com/repos/{repo_name}/hooks"

        try:
            existing_hooks_resp = requests.get(hooks_url, headers=headers, timeout=10)
            if existing_hooks_resp.status_code == 401:
                raise VaultAuthError(
                    "Your GitHub token has expired or is invalid. Re-authenticate GitHub in the Vault."
                )
            if existing_hooks_resp.status_code in (403, 404):
                raise ValueError(
                    f"Cannot access webhooks for '{repo_name}'. Ensure the repo exists and you have admin access."
                )

            existing_hooks_resp.raise_for_status()
            for hook in existing_hooks_resp.json():
                if hook.get("config", {}).get("url") == webhook_url:
                    return

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
            if resp.status_code == 422:
                # Hook already exists on GitHub
                return
            resp.raise_for_status()

        except VaultAuthError:
            raise
        except requests.RequestException as e:
            status_code = getattr(e.response, "status_code", None)
            if status_code == 401:
                raise VaultAuthError(
                    "Your GitHub token has expired or is invalid. Re-authenticate GitHub in the Vault."
                )
            raise ValueError(
                f"Could not register webhook on '{repo_name}'. Check repository permissions."
            )

    def match_ingress_event(
        self, app_event: str, event_type: str, payload: dict, step_config: dict
    ) -> bool:
        repo_filter = step_config.get("repository", "").strip()
        incoming_repo = payload.get("repository", {}).get("full_name", "").strip()
        if repo_filter and repo_filter != incoming_repo:
            return False
        return True
