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
