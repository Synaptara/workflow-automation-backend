from urllib.parse import quote

import requests
from decouple import config as env

from . import register
from .base import BaseExecutor

TOKEN_URL = "https://oauth2.googleapis.com/token"


@register("google_sheets")
class GoogleSheetsExecutor(BaseExecutor):
    def _refresh(self, refresh_token: str) -> str:
        r = requests.post(
            TOKEN_URL,
            data={
                "client_id": env("GOOGLE_CLIENT_ID"),
                "client_secret": env("GOOGLE_CLIENT_SECRET"),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )
        if not r.ok:
            raise ValueError(
                "Google connection expired. Reconnect Google Sheets in the Vault."
            )
        return r.json()["access_token"]

    def _append(self, token, sheet_id, rng, row):
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{quote(sheet_id, safe='')}/values/{quote(rng, safe='')}:append"
        return requests.post(
            url,
            params={"valueInputOption": "USER_ENTERED"},
            headers={"Authorization": f"Bearer {token}"},
            json={"values": [row]},
            timeout=10,
        )

    def execute(self, app_event: str, config: dict, context: dict) -> dict:
        token = config.get("access_token")
        sheet_id = str(config.get("spreadsheet_id") or "").strip()
        rng = str(config.get("range") or "Sheet1!A:A").strip()
        raw = str(config.get("values") or "")
        if not (token and sheet_id and raw.strip()):
            raise ValueError(
                "Google Sheets needs a connection, a spreadsheet ID and values."
            )

        row = [v.strip() for v in raw.split(",") if v.strip()]
        resp = self._append(token, sheet_id, rng, row)
        if resp.status_code == 401 and config.get("refresh_token"):
            resp = self._append(
                self._refresh(config["refresh_token"]), sheet_id, rng, row
            )
        if not resp.ok:
            msg = (
                resp.json().get("error", {}).get("message", resp.text)
                if resp.content
                else resp.status_code
            )
            raise ValueError(f"Google Sheets error: {msg}")
        return resp.json()
