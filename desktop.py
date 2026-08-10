"""SHEET auto FILL — desktop app entry point.

Runs the local server in the background and shows it in a native window,
so the whole thing behaves like an ordinary Windows program: one icon,
one window, no console, no browser tab.
"""
import socket
import sys
import threading
import time
import urllib.request

APP_TITLE = "SHEET auto FILL"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_up(port: int, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/status"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(0.25)
    return False


def _show_error(message: str):
    """Show a dialog on any platform, falling back to stderr."""
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, APP_TITLE, 0x10)
            return
        if sys.platform == "darwin":
            import subprocess

            script = (f'display dialog {_as_applescript(message)} '
                      f'with title {_as_applescript(APP_TITLE)} '
                      f'buttons {{"OK"}} with icon caution')
            subprocess.run(["osascript", "-e", script], check=False)
            return
    except Exception:
        pass
    print(message, file=sys.stderr)


def _as_applescript(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def selftest() -> int:
    """Headless check that a packaged build is complete (used by CI)."""
    problems = []
    try:
        from app import app as flask_app  # noqa: F401
    except Exception as e:
        problems.append(f"app import failed: {type(e).__name__}: {e}")
    try:
        from extractors import ocr_available

        if not ocr_available():
            problems.append("OCR engine missing from the bundle")
    except Exception as e:
        problems.append(f"extractors import failed: {type(e).__name__}: {e}")
    try:
        import fields

        if len(fields.FIELD_ORDER) < 10:
            problems.append("mapping.yaml not bundled correctly")
        if "rates" not in fields.FIELD_ORDER:
            problems.append("field mapping is out of date (no 'rates' field)")
    except Exception as e:
        problems.append(f"fields import failed: {type(e).__name__}: {e}")

    # every asset the app reads at runtime must be inside the bundle
    try:
        import os

        from resources import resource

        for asset in ("post_template.txt", "appsscript_template.js",
                      os.path.join("static", "index.html"),
                      os.path.join("static", "app.js")):
            if not os.path.exists(resource(asset)):
                problems.append(f"missing from bundle: {asset}")
    except Exception as e:
        problems.append(f"asset check failed: {type(e).__name__}: {e}")

    # the Rate block must map each label to its own amount, and the store name
    # must survive into the address
    try:
        import portal_parse

        def _b(t, x, y):
            return {"text": t, "x0": x, "x1": x + len(t) * 8, "y0": y, "y1": y + 18, "h": 18}

        # Mirrors the real page: the Rate block is TWO columns, and "Primary
        # Technician" appears earlier naming a person. Collapsing those together
        # used to drop the regular rate entirely.
        parsed = portal_parse.parse_page([
            _b("Work Number", 480, 270), _b("JOB-TEST-1", 480, 292),
            _b("Primary Technician", 480, 357), _b("Omar Ben", 480, 381),
            _b("Target (0366) - 131 W Reynolds Rd", 140, 372),
            _b("131 W Reynolds RD, Lexington, KY 40503", 140, 395),
            _b("Rate", 480, 900),
            _b("Regular Technician", 480, 930), _b("$35.00 per hour", 480, 952),
            _b("Helper Technician", 1000, 930), _b("$18.00 per hour", 1000, 952),
            _b("Trip", 480, 1000), _b("$22.00", 480, 1022),
            _b("NTE", 1000, 1000), _b("$270.00", 1000, 1022),
            # Title + Special Instructions must coexist with the rates: these
            # share the same collected-values structure and once broke it.
            _b("Title", 1400, 270), _b("Fixture Repair", 1400, 292),
            _b("Scope", 140, 1100), _b("Repair the thing properly.", 140, 1128),
            _b("Special Instructions", 140, 1180),
            _b("All parts must be photographed.", 140, 1208),
        ])
        if "Special instructions" not in parsed.get("sow", ""):
            problems.append("special instructions were not appended to the scope")
        if parsed.get("rates", "").splitlines() != [
                "Regular Technician", "$35.00 per hour",
                "Helper Technician", "$18.00 per hour",
                "Trip", "$22.00"]:
            problems.append(f"rate parsing wrong: {parsed.get('rates')!r}")
        if not parsed.get("nte", "").startswith("270"):
            problems.append(f"NTE picked up a rate instead: {parsed.get('nte')!r}")
        if "Target (0366)" not in parsed.get("address", ""):
            problems.append("store name missing from the address")

        # An address split across several text runs is the most common reason a
        # PDF came back with an empty Address cell.
        split = portal_parse.parse_page([
            _b("Work Number", 480, 270), _b("JOB-TEST-2", 480, 292),
            _b("Walgreen's (04216) - 5201 S 3rd St", 145, 372),
            _b("5201 S 3rd ST,", 146, 395), _b("Louisville, KY 40214", 260, 395),
        ])
        if "Louisville, KY" not in split.get("city", ""):
            problems.append(f"split address not read: {split.get('address')!r}")
        if "04216" not in split.get("address", ""):
            problems.append("store number lost on a split address")
    except Exception as e:
        problems.append(f"portal parsing failed: {type(e).__name__}: {e}")

    # work-order numbers: other dispatchers' prefixes count, visit numbers don't
    try:
        import jobid

        if not jobid.looks_like("NC-260807-0281"):
            problems.append("NC- work orders are not recognised")
        if jobid.looks_like("VST-260729-7250"):
            problems.append("visit numbers are being treated as work orders")
        if jobid.find("Jobs / JOB-260729-23617 VST-260729-7250") != "JOB-260729-23617":
            problems.append("job id picked the wrong identifier")
    except Exception as e:
        problems.append(f"job id checks failed: {type(e).__name__}: {e}")

    # the fallback paste layout must match the workbook's current tabs
    try:
        import app as _app

        standard = _app.LAYOUT_PRESETS["standard"]["fields"]
        if len(standard) != 17:
            problems.append("default paste layout no longer matches the sheet")

        import fields as _fields

        for gone in ("cap", "jmg"):
            if gone in _fields.FIELD_ORDER:
                problems.append(f"'{gone}' is still a field — it was removed from the sheet")
    except Exception as e:
        problems.append(f"layout preset check failed: {type(e).__name__}: {e}")

    # A library that silently fails to import inside the bundle degrades
    # extraction instead of erroring, so check the PDF stack explicitly.
    for mod in ("pdfplumber", "pdfminer.high_level", "pypdf", "statistics"):
        try:
            __import__(mod)
        except Exception as e:
            problems.append(f"{mod} unusable in this build: {type(e).__name__}: {e}")

    # Generated PDFs place glyphs one at a time; reading them as flat lines
    # interleaves neighbouring columns, so the rebuild must keep them apart.
    try:
        import local_parse

        def _c(ch, x, y, w=1.8, h=3.1):
            return {"text": ch, "x0": x, "x1": x + w, "top": y, "bottom": y + h}

        chars = []
        for i, ch in enumerate("JOB-1"):          # left column
            chars.append(_c(ch, 50 + i * 1.8, 100))
        for i, ch in enumerate("Aug 7"):          # right column, same row
            chars.append(_c(ch, 200 + i * 1.8, 100))
        rebuilt = [b["text"] for b in local_parse._chars_to_boxes(chars)]
        if rebuilt != ["JOB-1", "Aug 7"]:
            problems.append(f"column rebuild wrong: {rebuilt}")
    except Exception as e:
        problems.append(f"text-layer rebuild failed: {type(e).__name__}: {e}")

    try:
        import posts

        text = posts.render({"job_id": "JOB-1", "sow": "x", "address": "y"})
        if "JOB-1" not in text:
            problems.append("post template did not render")
        if "Work Number" not in text:
            problems.append("work-order layout is out of date (no 'Work Number' heading)")
        if "Rate" in text:
            problems.append("empty Rate section was not dropped")
    except Exception as e:
        problems.append(f"posts failed: {type(e).__name__}: {e}")

    lines = ([f"SELFTEST FAIL: {p}" for p in problems] or
             ["SELFTEST OK: app, OCR engine and field mapping all load"])
    report = "\n".join(lines)

    # A windowed build has no console (sys.stdout can be None), so also leave a log
    # file the build machine can read.
    try:
        if sys.stdout is not None:
            print(report, flush=True)
    except Exception:
        pass
    try:
        import os

        from resources import app_dir

        with open(os.path.join(app_dir(), "selftest.log"), "w", encoding="utf-8") as fh:
            fh.write(report + "\n")
    except Exception:
        pass
    return 1 if problems else 0


def main():
    if "--selftest" in sys.argv:
        return selftest()

    try:
        from app import app as flask_app
    except Exception as e:
        _show_error(f"Could not start {APP_TITLE}.\n\n{type(e).__name__}: {e}")
        return 1

    port = _free_port()

    def serve():
        try:
            from werkzeug.serving import make_server

            make_server("127.0.0.1", port, flask_app, threaded=True).serve_forever()
        except Exception as e:  # surfaced by the readiness check below
            print(f"server error: {e}", file=sys.stderr)

    threading.Thread(target=serve, daemon=True).start()

    if not _wait_until_up(port):
        _show_error(f"{APP_TITLE} could not start its local service.\n"
                    "If a security tool is blocking local connections, allow this app and retry.")
        return 1

    url = f"http://127.0.0.1:{port}/"
    try:
        import webview

        webview.create_window(APP_TITLE, url, width=1400, height=900,
                              min_size=(900, 600), confirm_close=False)
        webview.start()
    except Exception:
        # No WebView2 runtime — fall back to the default browser.
        import webbrowser

        webbrowser.open(url)
        _show_error(f"{APP_TITLE} is running in your browser at:\n{url}\n\n"
                    "Keep this dialog open while you work; closing it stops the app.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
