"""Google Sheets read/write via a service account (gspread).

The target worksheet's real header row is read at push time, so the tool
adapts to each monthly tab's exact column layout (e.g. tabs with or without
a CAP column). Rows are upserted by Job ID: existing jobs are updated in
place, new jobs are inserted directly under the last job row so the
Expenses/Revenue block and its formulas stay below and intact.
"""
import json
import os
import re

import gspread
from gspread.utils import rowcol_to_a1

from fields import FIELD_ORDER, sheet_synonyms, PHONE_HEADERS

# Column A holds the work-order number. Most are "JOB-260729-23617", but other
# dispatchers use their own prefix (e.g. "NC-260807-0281"), so match the shape
# rather than the word "JOB" — otherwise those rows are invisible and get
# duplicated instead of updated.
JOB_CELL_RE = re.compile(r"^[A-Za-z]{1,6}[-\s]?\d{4,}", re.I)


def looks_like_job_id(value: str) -> bool:
    return bool(JOB_CELL_RE.match((value or "").strip()))


class SheetError(Exception):
    pass


class SheetClient:
    def __init__(self, sheet_id: str, service_account_file: str):
        self.sheet_id = sheet_id
        self.sa_file = service_account_file
        self._gc = None
        self._ss = None

    # ------------------------------------------------------------ setup

    def sa_email(self):
        try:
            with open(self.sa_file, encoding="utf-8") as f:
                return json.load(f).get("client_email")
        except (OSError, json.JSONDecodeError):
            return None

    def configured(self) -> bool:
        return os.path.exists(self.sa_file)

    def reset(self):
        """Drop the cached connection so newly added credentials are picked up."""
        self._gc = None
        self._ss = None

    def _spreadsheet(self):
        if self._ss is None:
            if not self.configured():
                raise SheetError(
                    f"Google credentials not found ({self.sa_file}). Follow the README to "
                    "create a service account and save its key file in this folder."
                )
            try:
                self._gc = gspread.service_account(filename=self.sa_file)
                self._ss = self._gc.open_by_key(self.sheet_id)
            except gspread.exceptions.APIError as e:
                raise SheetError(self._friendly_api_error(e))
            except Exception as e:
                msg = str(e)
                if "deserialize" in msg or "private key" in msg.lower():
                    raise SheetError(
                        "The key file looks corrupted or incomplete. In Google Cloud open your "
                        "service account → Keys → Add key → Create new key → JSON, and drop "
                        "the freshly downloaded file into step 2.")
                if "invalid_grant" in msg or "JWT" in msg:
                    raise SheetError(
                        "Google rejected the key. It may have been deleted or disabled — "
                        "create a new JSON key and drop it into step 2.")
                raise SheetError(f"Could not open the Google Sheet: {msg}")
        return self._ss

    def _friendly_api_error(self, e) -> str:
        msg = str(e)
        if "403" in msg or "PERMISSION_DENIED" in msg:
            email = self.sa_email() or "the service account"
            return (f"Google says access is denied. Share the spreadsheet with {email} "
                    "as an Editor, and make sure the Google Sheets API is enabled for the project.")
        if "404" in msg:
            return "Spreadsheet not found — check sheet_id in config.yaml."
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            return "Google Sheets rate limit hit — wait a minute and try again."
        return f"Google Sheets error: {msg}"

    # ------------------------------------------------------------ reads

    def tabs(self) -> list:
        return [ws.title for ws in self._spreadsheet().worksheets()]

    def _ws(self, tab: str):
        ss = self._spreadsheet()
        if not tab or tab == "latest":
            return ss.worksheets()[-1]
        try:
            return ss.worksheet(tab)
        except gspread.exceptions.WorksheetNotFound:
            raise SheetError(f'Tab "{tab}" was not found in the spreadsheet.')

    def _header(self, values: list):
        """-> (header_row_index_1based, {field: col_index_0based}, ncols)"""
        header_idx, headers = None, None
        for i, row in enumerate(values[:10]):
            if any(str(c).strip().lower() == "sow" for c in row):
                header_idx, headers = i + 1, row
                break
        if header_idx is None:
            raise SheetError('Could not find the header row (no "SOW" column) in this tab.')

        normed = [str(h).strip().lower() for h in headers]
        colmap = {"job_id": 0}

        # phone columns are matched by occurrence order: 1st -> handyman, 2nd -> assignee
        phone_cols = [i for i, h in enumerate(normed) if h in PHONE_HEADERS]
        if len(phone_cols) >= 1:
            colmap["handyman_phone"] = phone_cols[0]
        if len(phone_cols) >= 2:
            colmap["assignee_phone"] = phone_cols[1]

        for field in FIELD_ORDER:
            if field in colmap:
                continue
            for syn in sheet_synonyms(field):
                if syn in normed:
                    colmap[field] = normed.index(syn)
                    break
        return header_idx, colmap, max(len(headers), 1)

    def layout(self, tab: str) -> dict:
        """The tab's real column order — what a pasted row has to line up with."""
        ws = self._ws(tab)
        values = ws.get_all_values()
        header_idx, colmap, ncols = self._header(values)
        by_col = {col: field for field, col in colmap.items()}
        headers = values[header_idx - 1] if header_idx <= len(values) else []
        return {
            "fields": [by_col.get(i, "") for i in range(ncols)],
            "headers": [str(h).strip() for h in headers[:ncols]],
            "columns": ncols,
        }

    def existing_jobs(self, tab: str) -> dict:
        """job_id -> row number (1-based) for the given tab."""
        ws = self._ws(tab)
        col_a = ws.col_values(1)
        return {
            v.strip(): i + 1
            for i, v in enumerate(col_a)
            if looks_like_job_id(v)
        }

    # ------------------------------------------------------------ writes

    def push_rows(self, tab: str, rows: list) -> list:
        ws = self._ws(tab)
        values = ws.get_all_values()
        header_idx, colmap, ncols = self._header(values)

        existing = {}
        for i, row in enumerate(values):
            cell = (row[0] if row else "").strip()
            if looks_like_job_id(cell):
                existing[cell] = i + 1
        last_job_row = max(existing.values(), default=header_idx)

        results = []
        for row in rows:
            jid = (row.get("job_id") or "").strip()
            if not jid:
                results.append({"job_id": "", "action": "error", "message": "Row skipped: no Job ID."})
                continue
            try:
                if jid in existing:
                    r = existing[jid]
                    updates = []
                    for field, col in colmap.items():
                        val = row.get(field)
                        if val not in (None, ""):
                            updates.append({"range": rowcol_to_a1(r, col + 1), "values": [[val]]})
                    if updates:
                        ws.batch_update(updates, value_input_option="USER_ENTERED")
                    results.append({"job_id": jid, "action": "updated", "row": r,
                                    "message": f"Updated existing row {r}."})
                else:
                    new_row = [""] * ncols
                    for field, col in colmap.items():
                        val = row.get(field)
                        if val not in (None, "") and col < ncols:
                            new_row[col] = val
                    insert_at = last_job_row + 1
                    ws.insert_row(new_row, index=insert_at,
                                  value_input_option="USER_ENTERED",
                                  inherit_from_before=True)
                    for k in existing:
                        if existing[k] >= insert_at:
                            existing[k] += 1
                    existing[jid] = insert_at
                    last_job_row = insert_at
                    results.append({"job_id": jid, "action": "inserted", "row": insert_at,
                                    "message": f"Inserted as new row {insert_at}."})
            except gspread.exceptions.APIError as e:
                results.append({"job_id": jid, "action": "error",
                                "message": self._friendly_api_error(e)})
        return results
