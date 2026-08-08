"""SHEET auto FILL — local web app.

Run:  py app.py   then open http://localhost:8765
"""
import json
import os
import re
import secrets

import yaml
from flask import Flask, jsonify, request, send_from_directory

from resources import (bundle_dir, ensure_external_copy, resource,  # noqa: E402
                       sync_asset_set, user_file)

# Refresh files shipped beside the app before anything reads them, so an update's
# new fields and layouts aren't shadowed by copies written by an older build.
sync_asset_set(["mapping.yaml", "post_template.txt"])

with open(ensure_external_copy("config.yaml"), encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

import posts  # noqa: E402
from extractors import extract_file, ocr_available, ExtractionError  # noqa: E402
from normalize import normalize_row  # noqa: E402
from sheets_client import SheetClient, SheetError  # noqa: E402
from webapp_client import WebAppClient, SheetError as WebAppError  # noqa: E402
from fields import FIELD_ORDER, GRID_ORDER, labels  # noqa: E402

app = Flask(__name__, static_folder=os.path.join(bundle_dir(), "static"))
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024

sheet = SheetClient(
    sheet_id=CONFIG.get("sheet_id", ""),
    service_account_file=user_file(CONFIG.get("service_account_file", "service_account.json")),
)
_conn = {}
try:
    with open(user_file("connection.json"), encoding="utf-8") as _fh:
        _conn = json.load(_fh) or {}
except Exception:
    _conn = {}
webapp = WebAppClient(_conn.get("webapp_url", ""), _conn.get("webapp_key", ""))


def backend():
    """The Web App connection wins when set; otherwise the service account."""
    return webapp if webapp.configured() else sheet


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/status")
def status():
    if request.args.get("recheck"):
        sheet.reset()          # pick up a service_account.json added just now
    active = backend()
    info = {
        "fields": GRID_ORDER,          # spreadsheet columns only
        "all_fields": FIELD_ORDER,     # includes post-only fields like rates
        "labels": labels(),
        "ocr_ok": ocr_available(),
        "mode": "webapp" if webapp.configured() else "service_account",
        "sheet_configured": active.configured(),
        "sa_email": sheet.sa_email(),
        "sheet_id": CONFIG.get("sheet_id", ""),
        "webapp_url": webapp.url,
        "sheet_title": None,
        "tabs": [],
        "sheet_error": None,
    }
    if active.configured():
        try:
            if webapp.configured():
                data = webapp.info()
                info["tabs"] = data.get("tabs", [])
                info["sheet_title"] = data.get("title")
            else:
                info["tabs"] = sheet.tabs()
        except (SheetError, WebAppError) as e:
            info["sheet_error"] = str(e)
    return jsonify(info)


SHEET_ID_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})")


CONNECTION_FILE = "connection.json"


def _load_connection() -> dict:
    """Secrets live outside config.yaml so the config can be shared safely."""
    try:
        with open(user_file(CONNECTION_FILE), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_connection(**changes):
    data = _load_connection()
    data.update(changes)
    with open(user_file(CONNECTION_FILE), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return data


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
    active = backend()
    if active.configured():
        try:
            existing = active.existing_jobs(tab)
        except (SheetError, WebAppError):
            pass  # preview still works; push will surface the error

    return jsonify({"rows": rows, "files": file_reports, "existing": list(existing.keys())})


@app.get("/api/connect/script/code")
def script_code():
    """The Apps Script to paste into the user's spreadsheet, keyed to this app."""
    key = webapp.key or secrets.token_urlsafe(24)
    if key != webapp.key:
        _save_connection(webapp_key=key)
        webapp.key = key
    with open(resource("appsscript_template.js"), encoding="utf-8") as fh:
        code = fh.read()
    return jsonify({"code": code.replace("__APP_KEY__", key)})


@app.post("/api/connect/script")
def connect_script():
    """Save the deployed Web App link and prove it works."""
    url = (request.get_json(force=True).get("url") or "").strip()
    if not url:
        _save_connection(webapp_url="")
        webapp.url = ""
        return jsonify({"ok": True, "cleared": True})

    if "script.google.com" not in url:
        return jsonify({"error": "That isn't an Apps Script link. After deploying, copy the "
                                 "URL that ends in /exec."}), 400
    if not url.rstrip("/").endswith("/exec"):
        return jsonify({"error": "That link looks like the editor, not the deployment. "
                                 "Use Deploy → Manage deployments and copy the URL "
                                 "ending in /exec."}), 400

    probe = WebAppClient(url, webapp.key)
    try:
        data = probe.info()
    except WebAppError as e:
        return jsonify({"error": str(e)}), 400

    _save_connection(webapp_url=url)
    webapp.url = url
    return jsonify({"ok": True, "title": data.get("title"), "tabs": data.get("tabs", [])})


@app.post("/api/post")
def make_post():
    """Render the shareable work-order text for one or more jobs."""
    payload = request.get_json(force=True)
    rows = payload.get("rows") or []
    if not rows:
        return jsonify({"error": "Nothing to write up."}), 400
    template = payload.get("template") or None
    return jsonify({"text": posts.render_many(rows, template),
                    "template": template or posts._template()})


@app.get("/api/post/template/default")
def default_template():
    """The layout shipped with the app, for the Reset button."""
    try:
        with open(os.path.join(bundle_dir(), "post_template.txt"), encoding="utf-8") as fh:
            return jsonify({"template": fh.read()})
    except OSError:
        return jsonify({"template": posts.DEFAULT_TEMPLATE})


@app.post("/api/post/template")
def save_template():
    """Persist an edited post layout next to the app."""
    text = request.get_json(force=True).get("template")
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "The template can't be empty."}), 400
    try:
        with open(ensure_external_copy("post_template.txt"), "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as e:
        return jsonify({"error": f"Could not save the template: {e}"}), 500
    return jsonify({"ok": True})


@app.post("/api/push")
def push():
    payload = request.get_json(force=True)
    tab = payload.get("tab") or "latest"
    rows = payload.get("rows") or []
    if not rows:
        return jsonify({"error": "Nothing to push."}), 400
    try:
        results = backend().push_rows(tab, rows)
    except (SheetError, WebAppError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"results": results})


if __name__ == "__main__":
    port = int(CONFIG.get("port", 8765))
    print(f"\n  SHEET auto FILL running at  http://localhost:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
