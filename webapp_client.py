"""Writes to Google Sheets through a Web App script bound to the spreadsheet.

This is the easy connection path: the user pastes a short script into their own
sheet and deploys it, which avoids Google Cloud Console, service accounts, key
files and sharing steps entirely. The script runs as the sheet's owner, so no
credentials ever reach this machine.

Exposes the same interface as SheetClient so app.py can use either one.
"""
import re

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
            raise self._fail(self._explain_html(r))

    @staticmethod
    def _explain_html(r) -> str:
        """Say what Google actually replied, instead of guessing.

        A web app that isn't reachable returns an HTML page, and the page
        differs by cause — an unfinished authorisation, a test URL, a wrong
        link. Reporting them as one generic error sent people back to a
        deployment dialog that was already configured correctly.
        """
        body = (r.text or "")
        low = body.lower()
        final = (r.url or "").lower()

        if "accounts.google.com" in final or "signin" in final:
            return ("Google asked for a sign-in, which means this deployment is not "
                    "public yet.\n"
                    "In the Apps Script editor: Deploy → Manage deployments → the pencil "
                    "icon → set Who has access to “Anyone” → Deploy. Then copy the URL "
                    "again — it must end in /exec.")

        if "authorization is required" in low or "authorisation is required" in low:
            return ("The script has not been authorised yet.\n"
                    "In the Apps Script editor press Run once. Google will warn that the "
                    "app is unverified — choose Advanced → “Go to … (unsafe)” → Allow. "
                    "That grant is for your own script. Then press Connect again.")

        if "script function not found" in low or "requested entity was not found" in low:
            return ("Google found the deployment, but it is serving a snapshot of the "
                    "script from before the code was pasted in.\n"
                    "A deployment is frozen to a version, so pasting the code afterwards "
                    "changes nothing until a new version is published:\n"
                    "1. In the editor press Ctrl+S to save (you should see "
                    "“function doGet”).\n"
                    "2. Deploy → Manage deployments → pencil icon.\n"
                    "3. Set Version to “New version” — this is the step usually missed.\n"
                    "4. Deploy, then press Connect again (the URL stays the same).")

        if "sorry, unable to open the file" in low or "moved temporarily" in low:
            return ("That link does not point at a deployed web app. Use Deploy → Manage "
                    "deployments and copy the Web app URL, which ends in /exec.")

        if "google drive" in low and "sign in" in low:
            return ("Google is asking you to sign in to view this. Re-deploy with "
                    "Who has access = “Anyone”.")

        snippet = re.sub(r"<[^>]+>", " ", body)
        snippet = re.sub(r"\s{2,}", " ", snippet).strip()[:180]
        return ("Google returned a web page instead of data"
                + (f": “{snippet}”" if snippet else ".")
                + "\nSend me this message and I'll pin down the cause.")

    # ------------------------------------------------------------ interface

    def sa_email(self):
        return None

    def info(self) -> dict:
        return self._request("GET")

    def tabs(self) -> list:
        return self.info().get("tabs", [])

    def layout(self, tab: str) -> dict:
        data = self._request("POST", json={
            "key": self.key, "action": "layout", "tab": tab,
            "mapping": _mapping(), "phone_headers": PHONE_HEADERS,
        })
        return {"fields": data.get("fields", []), "headers": data.get("headers", []),
                "columns": data.get("columns", 0)}

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
