"""File locations that work both from source and from the packaged .exe.

When frozen by PyInstaller, read-only assets (static/, the default YAML files)
live inside the bundle, while anything the user edits or supplies —
config.yaml, mapping.yaml, service_account.json — is read from the folder
containing the .exe so it stays visible and editable.
"""
import os
import sys


def frozen() -> bool:
    return getattr(sys, "frozen", False)


def bundle_dir() -> str:
    """Where bundled read-only assets live."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def app_dir() -> str:
    """The folder the user sees: next to the .exe, or the project folder."""
    if frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


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


def sync_external(name: str) -> str:
    """Like ensure_external_copy, but refreshes a copy left over from an older build.

    Without this, a file written beside the app on first run would shadow the
    bundled one forever, so new fields shipped in an update would never appear.
    """
    target = user_file(name)
    source = os.path.join(bundle_dir(), name)
    if not frozen() or not os.path.exists(source):
        return ensure_external_copy(name)

    if os.path.exists(target) and _schema_version(source) > _schema_version(target):
        try:
            import shutil

            shutil.copyfile(target, target + ".bak")   # keep any local edits
            shutil.copyfile(source, target)
        except OSError:
            return source
    return ensure_external_copy(name)


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
