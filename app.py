"""SHEET auto FILL — local web app.

Run:  py app.py   then open http://localhost:8765
"""
import json
import os
import re

import yaml
from flask import Flask, jsonify, request, send_from_directory

from resources import bundle_dir, ensure_external_copy, user_file

with open(ensure_external_copy("config.yaml"), encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)
ensure_external_copy("mapping.yaml")

from extractors import extract_file, ocr_available, ExtractionError  # noqa: E402
from normalize import normalize_row  # noqa: E402
from sheets_client import SheetClient, SheetError  # noqa: E402
from fields import FIELD_ORDER, labels  # noqa: E402

app = Flask(__name__, static_folder=os.path.join(bundle_dir(), "static"))
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024

sheet = SheetClient(
    sheet_id=CONFIG["sheet_id"],
    service_account_file=user_file(CONFIG.get("service_account_file", "service_account.json")),
)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/status")
def status():
    if request.args.get("recheck"):
        sheet.reset()          # pick up a service_account.json added just now
    info = {
        "fields": FIELD_ORDER,
        "labels": labels(),
        "ocr_ok": ocr_available(),
        "sheet_configured": sheet.configured(),
        "sa_email": sheet.sa_email(),
        "sheet_id": CONFIG["sheet_id"],
        "tabs": [],
        "sheet_error": None,
    }
    if sheet.configured():
        try:
            info["tabs"] = sheet.tabs()
        except SheetError as e:
            info["sheet_error"] = str(e)
    return jsonify(info)


SHEET_ID_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})")


def _save_config_value(key: str, value: str):
    """Update one key in config.yaml, leaving comments and other keys intact."""
    path = ensure_external_copy("config.yaml")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    line = f'{key}: "{value}"'
    if re.search(rf"^{key}\s*:.*$", text, re.M):
        text = re.sub(rf"^{key}\s*:.*$", line, text, count=1, flags=re.M)
    else:
        text = text.rstrip() + "\n" + line + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


@app.post("/api/connect/sheet")
def connect_sheet():
    """Point the app at a spreadsheet, given its link or its ID."""
    value = (request.get_json(force=True).get("sheet") or "").strip()
    if not value:
        return jsonify({"error": "Paste the link to your Google Sheet first."}), 400

    m = SHEET_ID_RE.search(value)
    sheet_id = m.group(1) if m else value
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,}", sheet_id):
        return jsonify({"error": "That doesn't look like a Google Sheets link. Open the "
                                 "sheet in your browser and copy the address bar."}), 400

    _save_config_value("sheet_id", sheet_id)
    CONFIG["sheet_id"] = sheet_id
    sheet.sheet_id = sheet_id
    sheet.reset()
    return jsonify({"sheet_id": sheet_id})


@app.post("/api/connect/key")
def connect_key():
    """Accept the downloaded Google key file and store it beside the app."""
    f = request.files.get("key")
    if not f:
        return jsonify({"error": "No file received."}), 400
    raw = f.read()
    try:
        info = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return jsonify({"error": "That file isn't the JSON key. Pick the .json file that "
                                 "Google downloaded when you created the key."}), 400

    if info.get("type") != "service_account" or not info.get("client_email"):
        return jsonify({"error": "That JSON isn't a service-account key. In Google Cloud, "
                                 "open your service account → Keys → Add key → "
                                 "Create new key → JSON."}), 400

    target = user_file(CONFIG.get("service_account_file", "service_account.json"))
    try:
        with open(target, "wb") as fh:
            fh.write(raw)
    except OSError as e:
        return jsonify({"error": f"Could not save the key next to the app: {e}"}), 500

    sheet.reset()
    return jsonify({"email": info["client_email"]})


@app.post("/api/extract")
def extract():
    tab = request.form.get("tab") or "latest"
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files uploaded."}), 400

    # values the portal never contains — applied to any field left blank
    defaults = {}
    for field in ("company", "team_leader", "dispatcher", "job_status", "jmg"):
        v = (request.form.get("default_" + field) or "").strip()
        if v:
            defaults[field] = v

    rows, file_reports = [], []
    for f in files:
        try:
            raw_jobs = extract_file(f.filename, f.read())
            normalized = []
            for job in raw_jobs:
                for field, value in defaults.items():
                    if not job.get(field):
                        job[field] = value
                normalized.append(normalize_row(job))
            rows.extend(normalized)
            file_reports.append({"name": f.filename, "ok": True,
                                 "message": f"{len(normalized)} job(s) extracted."})
        except ExtractionError as e:
            file_reports.append({"name": f.filename, "ok": False, "message": str(e)})
        except Exception as e:  # keep one bad file from killing the batch
            file_reports.append({"name": f.filename, "ok": False,
                                 "message": f"Unexpected error: {e}"})

    existing = {}
    if sheet.configured():
        try:
            existing = sheet.existing_jobs(tab)
        except SheetError:
            pass  # preview still works; push will surface the error

    return jsonify({"rows": rows, "files": file_reports, "existing": list(existing.keys())})


@app.post("/api/push")
def push():
    payload = request.get_json(force=True)
    tab = payload.get("tab") or "latest"
    rows = payload.get("rows") or []
    if not rows:
        return jsonify({"error": "Nothing to push."}), 400
    try:
        results = sheet.push_rows(tab, rows)
    except SheetError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"results": results})


if __name__ == "__main__":
    port = int(CONFIG.get("port", 8765))
    print(f"\n  SHEET auto FILL running at  http://localhost:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
