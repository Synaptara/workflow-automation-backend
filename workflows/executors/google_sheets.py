import requests

from . import register
from .base import BaseExecutor


@register("google_sheets")
class GoogleSheetsExecutor(BaseExecutor):
    def execute(self, config: dict, context: dict) -> dict:
        access_token = config.get("access_token")
        spreadsheet_id = config.get("spreadsheet_id")
        sheet_range = config.get("range", "Sheet1!A:A")
        raw_values = config.get("values", "")

        if not all([access_token, spreadsheet_id, raw_values]):
            raise ValueError(
                "Google Sheets requires an access token, spreadsheet ID, and values."
            )

        row_data = [val.strip() for val in raw_values.split(",") if val.strip()]

        url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{sheet_range}:append"
        params = {"valueInputOption": "USER_ENTERED"}
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        payload = {"values": [row_data]}

        resp = requests.post(url, params=params, headers=headers, json=payload)
        resp.raise_for_status()

        return resp.json()
