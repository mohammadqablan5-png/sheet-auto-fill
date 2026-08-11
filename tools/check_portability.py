"""Catch Windows-only assumptions before they reach the macOS build.

Run locally or in CI:  python tools/check_portability.py

These are the mistakes that actually bit this project, or would have:
  * writing user data next to sys.executable — inside a .app bundle on macOS
  * Windows-only calls without a platform guard
  * text files opened without an explicit encoding (Windows defaults differ)
  * absolute drive-letter paths
  * shell scripts committed with CRLF, which macOS refuses to run
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY_FILES = []
for base, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs
               if d not in {".git", "build", "dist", "App", "__pycache__",
                            ".venv", "venv", "samples", "tools"}]
    PY_FILES += [os.path.join(base, f) for f in files if f.endswith(".py")]

problems = []


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


for path in PY_FILES:
    rel = os.path.relpath(path, ROOT)
    text = read(path)
    lines = text.splitlines()

    for n, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        # user data must not be written beside the executable on macOS
        if "sys.executable" in line and "resources.py" not in rel:
            problems.append(f"{rel}:{n}: uses sys.executable directly — "
                            "use resources.app_dir() so macOS gets a writable folder")

        # Windows-only APIs need a platform guard
        for api in ("windll", "winreg", "os.startfile"):
            if api in line:
                window = "\n".join(lines[max(0, n - 6):n])
                if 'sys.platform == "win32"' not in window and "win32" not in window:
                    problems.append(f"{rel}:{n}: {api} without a win32 guard")

        # drive-letter paths
        if re.search(r"[\"'][A-Za-z]:\\\\", line):
            problems.append(f"{rel}:{n}: hard-coded Windows drive path")

        # text-mode open() must state its encoding
        m = re.search(r"\bopen\s*\(", line)
        if m and "encoding=" not in line and '"rb"' not in line and "'rb'" not in line \
                and '"wb"' not in line and "'wb'" not in line:
            if re.search(r"open\s*\(\s*(io\.BytesIO|BytesIO)", line):
                pass                                  # not a filesystem open
            elif "pdfplumber.open" in line or "Image.open" in line or \
                    "webbrowser.open" in line or "urlopen" in line:
                pass
            else:
                problems.append(f"{rel}:{n}: open() without encoding= "
                                "(Windows and macOS default differently)")

# shell scripts must keep Unix line endings and be executable
for base, dirs, files in os.walk(os.path.join(ROOT, "mac")):
    for f in files:
        if f.endswith(".command") or f.endswith(".sh"):
            with open(os.path.join(base, f), "rb") as fh:
                blob = fh.read()
            if b"\r\n" in blob:
                problems.append(f"mac/{f}: CRLF line endings — macOS cannot run this")
            if not blob.startswith(b"#!"):
                problems.append(f"mac/{f}: missing shebang")

# The build workflow must be valid, or GitHub rejects the file and no job runs
# at all — which looks like a build failure with nothing to read. The matrix
# context does not exist yet when a job-level "if" is evaluated; that mistake
# cost a whole run once.
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "build.yml")
if os.path.exists(WORKFLOW):
    try:
        import yaml
    except ImportError:
        pass
    else:
        try:
            flow = yaml.safe_load(read(WORKFLOW))
        except yaml.YAMLError as e:
            problems.append(f".github/workflows/build.yml: invalid YAML — {e}")
        else:
            for name, job in (flow.get("jobs") or {}).items():
                if "matrix" in str(job.get("if", "")):
                    problems.append(
                        f".github/workflows/build.yml: job '{name}' uses the matrix "
                        "context in a job-level if — only github/needs/vars/inputs "
                        "exist there. Put the condition on the steps instead.")

# macOS needs pyobjc for the native window
reqs = read(os.path.join(ROOT, "requirements.txt"))
if 'sys_platform == "darwin"' not in reqs:
    problems.append("requirements.txt: no macOS-only pyobjc entries")

if problems:
    print("PORTABILITY PROBLEMS:")
    for p in problems:
        print("  -", p)
    sys.exit(1)

print(f"portability OK — {len(PY_FILES)} python files checked")
