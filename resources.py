"""File locations that work from source and from the packaged app on any OS.

Read-only assets (static/, the default YAML files) live inside the bundle.
Anything the user edits or supplies — config.yaml, mapping.yaml,
connection.json, service_account.json — lives in a writable folder outside it.

Where that folder is differs by platform, and getting it wrong on macOS is not
cosmetic: inside a .app, ``sys.executable`` points at
``…/SHEET auto FILL.app/Contents/MacOS/``, so writing there would put the user's
Google key *inside the application bundle* — discarded on every update, refused
outright when the app sits in /Applications, and enough to invalidate the code
signature. macOS therefore uses Application Support, which is the documented
home for exactly this.
"""
import os
import sys

APP_NAME = "SHEET auto FILL"


def frozen() -> bool:
    return getattr(sys, "frozen", False)


def bundle_dir() -> str:
    """Where bundled read-only assets live."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def _mac_support_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Library",
                        "Application Support", APP_NAME)


def _linux_config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(base, "sheet-auto-fill")


def app_dir() -> str:
    """The writable folder holding the user's own files."""
    if not frozen():
        return os.path.dirname(os.path.abspath(__file__))

    if sys.platform == "darwin":
        target = _mac_support_dir()
    elif sys.platform.startswith("linux"):
        target = _linux_config_dir()
    else:
        target = os.path.dirname(sys.executable)      # beside the .exe

    try:
        os.makedirs(target, exist_ok=True)
    except OSError:
        return os.path.dirname(sys.executable)
    return target


def resource(name: str) -> str:
    """A user-supplied copy next to the app wins; otherwise the bundled default."""
    external = os.path.join(app_dir(), name)
    if os.path.exists(external):
        return external
    return os.path.join(bundle_dir(), name)


def user_file(name: str) -> str:
    """Always the user-visible location (used for writing / credentials)."""
    return os.path.join(app_dir(), name)


def _schema_version(path: str) -> int:
    """Reads 'schema_version: N' without needing a YAML parse."""
    import re

    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\s*schema_version\s*:\s*(\d+)", line)
                if m:
                    return int(m.group(1))
    except OSError:
        pass
    return 0


ASSET_MARKER = ".asset_version"


def sync_asset_set(names, version_from: str = "mapping.yaml"):
    """Refresh files shipped beside the app when the bundle is newer.

    A file written next to the app on first run shadows the bundled one forever,
    so anything added in an update would silently never appear. Versioning the
    whole asset set (rather than each file) means plain-text assets with nowhere
    to put a version number are covered too.
    """
    for name in names:
        ensure_external_copy(name)            # first-run copy
    if not frozen():
        return

    bundled = _schema_version(os.path.join(bundle_dir(), version_from))
    marker = user_file(ASSET_MARKER)
    try:
        with open(marker, encoding="utf-8") as fh:
            applied = int((fh.read() or "0").strip() or 0)
    except (OSError, ValueError):
        applied = 0
    if bundled <= applied:
        return

    import shutil

    for name in names:
        source = os.path.join(bundle_dir(), name)
        target = user_file(name)
        if not (os.path.exists(source) and os.path.exists(target)):
            continue
        try:
            with open(source, "rb") as a, open(target, "rb") as b:
                if a.read() == b.read():
                    continue
            shutil.copyfile(target, target + ".bak")      # keep any local edits
            shutil.copyfile(source, target)
        except OSError:
            pass
    try:
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(str(bundled))
    except OSError:
        pass


def ensure_external_copy(name: str) -> str:
    """Copy a bundled default next to the .exe on first run so it can be edited."""
    target = user_file(name)
    if frozen() and not os.path.exists(target):
        source = os.path.join(bundle_dir(), name)
        if os.path.exists(source):
            try:
                import shutil

                shutil.copyfile(source, target)
            except OSError:
                return source
    return target if os.path.exists(target) else os.path.join(bundle_dir(), name)
