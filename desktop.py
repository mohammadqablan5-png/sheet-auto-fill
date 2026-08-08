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

    try:
        import posts

        text = posts.render({"job_id": "JOB-1", "sow": "x", "address": "y"})
        if "JOB-1" not in text:
            problems.append("post template did not render")
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
