"""Build a single self-installing file for macOS.

Produces `dist/Install SHEET auto FILL.command` — one file the user downloads and
double-clicks. It carries the whole app inside itself, then on the Mac it:

  * finds a usable Python 3,
  * unpacks the app into ~/Library/Application Support/SHEET auto FILL/runtime,
  * builds a private virtual environment and installs the packages,
  * creates ~/Applications/SHEET auto FILL.app so there's a normal icon to
    double-click from then on,
  * launches it.

This exists because a compiled .app can only be produced on macOS. The installer
is a shell script, so it can be generated anywhere — including from Windows.
"""
import base64
import io
import os
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "dist")
OUT_FILE = os.path.join(OUT_DIR, "Install SHEET auto FILL.command")

# Everything the app needs to run from source — and nothing else. No build
# output, no samples (real customer data), and no credentials.
INCLUDE_FILES = [
    "app.py", "desktop.py", "resources.py", "extractors.py", "fields.py",
    "jobid.py", "local_parse.py", "normalize.py", "ocr.py", "portal_parse.py",
    "posts.py", "sheets_client.py", "webapp_client.py",
    "config.yaml", "mapping.yaml", "post_template.txt",
    "appsscript_template.js", "requirements.txt", "README.md",
]
INCLUDE_DIRS = ["static"]

EXCLUDE_NAMES = {"service_account.json", "connection.json", ".env"}


def build_payload() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in INCLUDE_FILES:
            path = os.path.join(ROOT, name)
            if os.path.exists(path):
                tar.add(path, arcname=name)
        for folder in INCLUDE_DIRS:
            base = os.path.join(ROOT, folder)
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if d != "__pycache__"]
                for fn in filenames:
                    if fn in EXCLUDE_NAMES:
                        continue
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
                    tar.add(full, arcname=rel)
    return buf.getvalue()


SCRIPT = r'''#!/bin/bash
# ============================================================
#  SHEET auto FILL — installer for macOS
#  Double-click this file. It sets everything up on its own.
# ============================================================
set -u

APP_NAME="SHEET auto FILL"
SUPPORT="$HOME/Library/Application Support/$APP_NAME"
RUNTIME="$SUPPORT/runtime"
APPDIR="$HOME/Applications/$APP_NAME.app"

say()  { printf "%s\n" "$*"; }
fail() {
    say ""
    say "-----------------------------------------------"
    say "  Setup could not finish."
    say "  $*"
    say "-----------------------------------------------"
    say ""
    read -r -p "Press Return to close this window."
    exit 1
}

clear
say "==============================================="
say "  Installing $APP_NAME"
say "==============================================="
say ""

# ---- 1. find a usable Python ------------------------------------------
PY=""
for c in python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1; then
        v=$("$c" -c 'import sys; print(sys.version_info[0]*100+sys.version_info[1])' 2>/dev/null || echo 0)
        if [ "$v" -ge 309 ]; then PY="$c"; break; fi
    fi
done

if [ -z "$PY" ]; then
    say "Python 3 is needed and was not found."
    say ""
    say "macOS can install it for you. A dialog may appear now —"
    say "choose Install, wait for it to finish, then run this file again."
    say ""
    xcode-select --install 2>/dev/null
    fail "Or download Python from https://www.python.org/downloads/macos/"
fi
say "Using $("$PY" --version 2>&1)"

PYMINOR=$("$PY" -c 'import sys; print(sys.version_info[1])')
if [ "$PYMINOR" -ge 13 ]; then
    say ""
    say "Note: Python 3.$PYMINOR is very new and some packages may not have"
    say "      ready-made builds for it yet. If the install fails, install"
    say "      Python 3.12 from python.org and run this file again."
fi

# ---- 2. unpack the app ------------------------------------------------
say ""
say "Unpacking…"
mkdir -p "$RUNTIME" || fail "Could not create $RUNTIME"

PAYLOAD_START=$(awk '/^__PAYLOAD_BELOW__$/ {print NR + 1; exit 0; }' "$0")
[ -n "$PAYLOAD_START" ] || fail "This installer file looks incomplete — download it again."

tail -n +"$PAYLOAD_START" "$0" \
  | "$PY" -c 'import sys,base64; sys.stdout.buffer.write(base64.b64decode(sys.stdin.buffer.read()))' \
  | tar xzf - -C "$RUNTIME" || fail "Could not unpack the application files."

# ---- 3. private environment + packages --------------------------------
say "Preparing a private Python environment (first time only)…"
if [ ! -x "$RUNTIME/.venv/bin/python" ]; then
    "$PY" -m venv "$RUNTIME/.venv" || fail "Could not create the environment."
fi

say "Downloading the packages — this takes a few minutes the first time."
say "(About 200 MB. Leave this window open.)"
say ""
"$RUNTIME/.venv/bin/python" -m pip install --upgrade pip --quiet
if ! "$RUNTIME/.venv/bin/python" -m pip install -r "$RUNTIME/requirements.txt"; then
    fail "Installing the packages failed. Scroll up for the first error —
  the most common cause is no internet connection."
fi

# ---- 4. make a normal app icon ----------------------------------------
say ""
say "Creating the app icon…"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/Contents/MacOS"

cat > "$APPDIR/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>com.sheetautofill.app</string>
  <key>CFBundleVersion</key><string>1.0.0</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>run</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict></plist>
PLIST

cat > "$APPDIR/Contents/MacOS/run" <<'LAUNCH'
#!/bin/bash
RUNTIME="$HOME/Library/Application Support/SHEET auto FILL/runtime"
cd "$RUNTIME" || exit 1
exec "$RUNTIME/.venv/bin/python" desktop.py
LAUNCH
chmod +x "$APPDIR/Contents/MacOS/run"

# a freshly built bundle is not quarantined, but be certain
xattr -dr com.apple.quarantine "$APPDIR" 2>/dev/null

# ---- 5. done ----------------------------------------------------------
say ""
say "==============================================="
say "  Done."
say ""
say "  $APP_NAME is now in your Applications folder."
say "  Double-click it any time to start."
say ""
say "  Settings are kept in:"
say "  ~/Library/Application Support/$APP_NAME"
say "==============================================="
say ""
say "Starting it now…"
open "$APPDIR" 2>/dev/null || "$APPDIR/Contents/MacOS/run" &
sleep 2
say ""
read -r -p "Press Return to close this window."
exit 0

__PAYLOAD_BELOW__
'''


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    payload = base64.b64encode(build_payload())

    # LF endings throughout: macOS cannot run a script containing CR characters.
    script = SCRIPT.replace("\r\n", "\n").encode("utf-8")
    with open(OUT_FILE, "wb") as fh:
        fh.write(script)
        for i in range(0, len(payload), 76):
            fh.write(payload[i:i + 76])
            fh.write(b"\n")

    with open(OUT_FILE, "rb") as fh:
        blob = fh.read()
    assert b"\r\n" not in blob, "CRLF found — macOS would refuse to run this"
    assert b"service_account.json" not in blob[:len(script)], "credential leaked"

    # A file downloaded straight from a browser arrives without the executable
    # bit, and macOS then opens it in TextEdit instead of running it. Shipping it
    # inside a zip preserves the permission, so a double-click works.
    zip_path = OUT_FILE + ".zip"
    import zipfile

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo(os.path.basename(OUT_FILE))
        info.external_attr = (0o755 << 16)          # rwxr-xr-x
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, blob)

    print(f"wrote {OUT_FILE}")
    print(f"  size: {os.path.getsize(OUT_FILE)/1024:.0f} KB")
    print(f"  payload: {len(payload)/1024:.0f} KB base64")
    print("  line endings: LF only")
    print(f"wrote {zip_path}")
    print(f"  size: {os.path.getsize(zip_path)/1024:.0f} KB  (executable bit preserved)")


if __name__ == "__main__":
    main()
