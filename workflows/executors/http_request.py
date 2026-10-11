import ipaddress
import json
import socket
from urllib.parse import urljoin, urlparse

import requests
from decouple import config as env

from . import register
from .base import BaseExecutor

ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
MAX_REDIRECTS = 3
MAX_BYTES = 1024 * 1024  # 1 MB response cap
ALLOW_PRIVATE = env("ALLOW_PRIVATE_HTTP_TARGETS", default=False, cast=bool)  # dev only


def _check_url(url):
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("URL must start with http:// or https://")
    if ALLOW_PRIVATE:
        return
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError("Could not resolve the host in the URL")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        ip = getattr(ip, "ipv4_mapped", None) or ip
        if not ip.is_global:
            raise ValueError("Requests to private or internal addresses are blocked")


def _json_field(raw, label, must_be_dict=False):
    raw = (raw or "").strip() if isinstance(raw, str) else raw
    if not raw:
        return None
    if not isinstance(raw, str):
        return raw
    try:
        val = json.loads(raw)
    except json.JSONDecodeError as e:
        if must_be_dict:
            raise ValueError(f"Invalid JSON in {label}: {e}")
        return raw  # body falls back to raw text
    if must_be_dict and not isinstance(val, dict):
        raise ValueError(f"{label.capitalize()} must be a JSON object.")
    return val


@register("http")
class HTTPExecutor(BaseExecutor):
    """Config: {"method", "url", "headers": JSON str, "body": JSON str}"""

    def execute(self, app_event: str, config: dict, context: dict) -> dict:
        method = str(config.get("method") or "GET").upper()
        if method not in ALLOWED_METHODS:
            raise ValueError(f"Unsupported method: {method}")
        url = config.get("url")
        headers = _json_field(config.get("headers"), "headers", must_be_dict=True) or {}
        payload = _json_field(config.get("body"), "body")

        kwargs = {
            "headers": headers,
            "timeout": 10,
            "stream": True,
            "allow_redirects": False,
        }
        if isinstance(payload, (dict, list)):
            kwargs["json"] = payload
        elif payload is not None:
            kwargs["data"] = (
                payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
            )

        resp = None
        for _ in range(MAX_REDIRECTS + 1):
            _check_url(url)
            resp = requests.request(method, url, **kwargs)
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get(
                "Location"
            ):
                url = urljoin(url, resp.headers["Location"])
                if resp.status_code in (301, 302, 303):
                    method = "GET"
                    kwargs.pop("json", None)
                    kwargs.pop("data", None)
                resp.close()
                continue
            break
        else:
            raise ValueError("Too many redirects")

        body = b""
        for chunk in resp.iter_content(8192):
            body += chunk
            if len(body) > MAX_BYTES:
                resp.close()
                raise ValueError("Response is larger than 1 MB")
        resp.raise_for_status()

        text = body.decode(resp.encoding or "utf-8", errors="replace")
        try:
            data = json.loads(text)
        except ValueError:
            data = text
        return {"status_code": resp.status_code, "response": data}
