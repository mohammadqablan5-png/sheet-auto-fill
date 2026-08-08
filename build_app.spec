# PyInstaller spec — builds the desktop app on Windows *and* macOS.
#
#   Windows:  py -m PyInstaller build_app.spec --noconfirm      -> dist/SHEET auto FILL.exe
#   macOS:    python3 -m PyInstaller build_app.spec --noconfirm -> dist/SHEET auto FILL.app
#
# The OCR engine ships ONNX model files and pypdfium2/onnxruntime ship native
# libraries, so those packages are collected whole rather than by import analysis.
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

APP_NAME = "SHEET auto FILL"
IS_MAC = sys.platform == "darwin"

datas = [("static", "static"), ("config.yaml", "."), ("mapping.yaml", "."),
         ("post_template.txt", "."), ("appsscript_template.js", ".")]
binaries = []
hiddenimports = [
    "gspread", "google.auth", "google.oauth2.service_account",
    "pdfplumber", "pypdf", "PIL", "numpy", "yaml",
    "local_parse", "portal_parse", "ocr", "extractors",
    "normalize", "fields", "sheets_client", "webapp_client", "posts", "resources",
    "requests",
]
hiddenimports += collect_submodules("webview")

for package in ("rapidocr_onnxruntime", "onnxruntime", "pypdfium2", "cv2",
                "pdfminer", "pdfplumber", "gspread", "google", "webview"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        pass

a = Analysis(
    ["desktop.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "pytest", "IPython", "notebook",
              "torch", "tensorflow", "scipy", "pandas"],
    noarchive=False,
)

pyz = PYZ(a.pure)

if IS_MAC:
    # A .app bundle is a folder, so it starts fast — no unpacking on each launch.
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP_NAME,
              debug=False, strip=False, upx=False, console=False)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP_NAME)
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier="com.sheetautofill.app",
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": "1.0.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            # local-only server; no outbound cleartext needed beyond loopback
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        },
    )
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=APP_NAME,
              debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
              runtime_tmpdir=None, console=False, icon=None)
