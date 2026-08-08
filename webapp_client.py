"""Writes to Google Sheets through a Web App script bound to the spreadsheet.

This is the easy connection path: the user pastes a short script into their own
sheet and deploys it, which avoids Google Cloud Console, service accounts, key
files and sharing steps entirely. The script runs as the sheet's owner, so no
credentials ever reach this machine.

Exposes the same interface as SheetClient so app.py can use either one.
"""
import requests

from fields import FIELD_ORDER, PHONE_HEADERS, sheet_synonyms

TIMEOUT = 60


class SheetError(Exception):
    pass


def _mapping() -> dict:
    return {f: sheet_synonyms(f) for f in FIELD_ORDER if sheet_synonyms(f)}


class WebAppClient:
    def __init__(self, url: str, key: str):
        self.url = (url or "").strip()
        self.key = (key or "").strip()

    # ------------------------------------------------------------ helpers

    def configured(self) -> bool:
        return bool(self.url and self.key)

    def reset(self):
        pass  # stateless

    def _fail(self, detail: str) -> SheetError:
        return SheetError(detail)

    def _check(self, data: dict):
        if isinstance(data, dict) and data.get("error"):
            err = str(data["error"])
            if "Wrong key" in err:
                raise self._fail(
                    "The sheet rejected the app's key. Re-copy the script from step 2 "
                    "(it contains a fresh key) and deploy it again.")
            raise self._fail(err)
        return data

    def _request(self, method: str, **kwargs):
        if not self.configured():
            raise self._fail("No sheet connected yet.")
        try:
            if method == "GET":
                r = requests.get(self.url, params={"key": self.key}, timeout=TIMEOUT)
            else:
                r = requests.post(self.url, json=kwargs.get("json"), timeout=TIMEOUT)
        except requests.exceptions.Timeout:
            raise self._fail("The sheet took too long to answer. Try again.")
        except requests.exceptions.RequestException as e:
            raise self._fail(f"Could not reach the sheet script: {e}")

        if r.status_code in (401, 403):
            raise self._fail(
                "Google refused the request. When deploying the script, set "
                '"Who has access" to "Anyone".')
        if r.status_code == 404:
            raise self._fail("That web-app link was not found. Re-copy the deployment URL.")
        if r.status_code >= 400:
            raise self._fail(f"The sheet script returned an error (HTTP {r.status_code}).")

        try:
            return self._check(r.json())
        except ValueError:
            body = (r.text or "").strip()
            if "Google Apps Script" in body or "<html" in body.lower():
                raise self._fail(
                    "That link opened a Google sign-in page instead of the script. "
                    'Re-deploy with "Execute as: Me" and "Who has access: Anyone", '
                    "then paste the new link.")
            raise self._fail("The sheet script sent back something unreadable.")

    # ------------------------------------------------------------ interface

    def sa_email(self):
        return None

    def info(self) -> dict:
        return self._request("GET")

    def tabs(self) -> list:
        return self.info().get("tabs", [])

    def existing_jobs(self, tab: str) -> dict:
        data = self._request("POST", json={"key": self.key, "action": "existing", "tab": tab})
        return {jid: 0 for jid in data.get("job_ids", [])}

    def push_rows(self, tab: str, rows: list) -> list:
        payload = {
            "key": self.key,
            "action": "push",
            "tab": tab,
            "rows": rows,
            "mapping": _mapping(),
            "phone_headers": PHONE_HEADERS,
        }
        data = self._request("POST", json=payload)
        return data.get("results", [])
