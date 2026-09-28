import json

import requests

from . import register
from .base import BaseExecutor


@register("http")
class HTTPExecutor(BaseExecutor):
    """
    Executes a generic HTTP request.
    Config expects: {"method": str, "url": str, "headers": str (JSON), "body": str (JSON)}
    """

    def execute(self, config: dict, context: dict) -> dict:
        method = config.get("method", "GET").upper()
        url = config.get("url")

        # Parse the headers safely
        headers_str = config.get("headers", "").strip()
        headers_dict = {}
        if headers_str:
            try:
                parsed_headers = json.loads(headers_str)
                # Ensure the parsed JSON is actually a dictionary, not an int/string/list
                if not isinstance(parsed_headers, dict):
                    raise ValueError("Headers must be a valid JSON dictionary object.")
                headers_dict = parsed_headers
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in headers: {str(e)}")

        # Parse the body safely
        body_str = config.get("body", "").strip()
        payload = None
        if body_str:
            try:
                payload = json.loads(body_str)
            except json.JSONDecodeError:
                # Fallback to sending raw text if it's not valid JSON
                payload = body_str

        # Make the dynamic request
        if isinstance(payload, dict):
            # Sends as application/json
            resp = requests.request(
                method=method, url=url, headers=headers_dict, json=payload, timeout=10
            )
        else:
            # FIX: Convert raw numbers/booleans to strings to prevent urllib3 crashes
            if payload is not None and not isinstance(payload, (str, bytes)):
                payload = json.dumps(payload)

            # Sends as text/plain or whatever is specified in custom headers
            resp = requests.request(
                method=method, url=url, headers=headers_dict, data=payload, timeout=10
            )

        resp.raise_for_status()

        try:
            resp_data = resp.json()
        except ValueError:
            resp_data = resp.text

        return {"status_code": resp.status_code, "response": resp_data}
