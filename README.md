# SHEET auto FILL

Reads your **work-order PDFs, screenshots, and CSVs**, pulls out the job details, lets you
**review and correct them in a table**, then writes them into your job-tracking
**Google Sheet** — updating existing jobs by Job ID and inserting new ones right under the
last job row, so the Expenses / Revenue block below stays intact.

**Everything runs on your own PC and is free.** No API keys, no accounts, no per-use
charges. PDFs are read by an offline OCR engine installed with the other packages.

```
PDFs / screenshots / CSVs ──▶ read locally (text layer, or offline OCR)
                                   │
                                   ▼
                        Preview table (you edit/fix)
                                   │  "Push"
                                   ▼
                        Google Sheet (update or insert by Job ID)
```

---

## Quick start — Windows

Open the **`App`** folder and double-click **`SHEET auto FILL.exe`**. That's the whole
app — it opens in its own window, with no console and nothing to install. Close the
window to quit. (Right-click it → *Pin to Start* / *Send to → Desktop* for easy access.)

Keep these next to the .exe (they're created automatically on first run):

| File | What it's for |
|---|---|
| `SHEET auto FILL.exe` | the app |
| `config.yaml` | which spreadsheet to fill, and the OCR resolution |
| `mapping.yaml` | column names and their synonyms |
| `service_account.json` | the Google key — the app writes this for you when you connect |

The app unpacks itself each time it starts, so allow **about 15 seconds** for the window
to appear (a little longer the very first time). Nothing is wrong if there's no
immediate reaction to the double-click.

<details>
<summary>Running from source instead (for development)</summary>

```bash
py -m pip install --user -r requirements.txt
py desktop.py            # same app window
py app.py                # or serve at http://localhost:8765 in a browser
```

To rebuild the .exe after changing the code:

```bash
py -m PyInstaller build_app.spec --noconfirm
```
</details>

---

## Quick start — Mac (MacBook Air etc.)

Two ways. **Option B is the smoother one** — it produces no security warnings at all.

### Option A — download the ready-made app

1. Go to the project's **Releases** page on GitHub.
2. Download the file matching your Mac:
   - **Apple Silicon** (M1/M2/M3/M4 — any Air from 2020 onward) →
     `SHEET-auto-FILL-macOS-AppleSilicon.zip`
   - **Intel** (Airs up to 2020) → `SHEET-auto-FILL-macOS-Intel.zip`

   Not sure which you have?  → menu → *About This Mac*. If the chip line says
   "Apple M…", it's Apple Silicon.
3. Unzip it, and drag **SHEET auto FILL.app** into your **Applications** folder.
4. **First launch only:** right-click (or Control-click) the app → **Open** → **Open**
   again in the dialog. macOS shows a warning because the app isn't signed with a paid
   Apple certificate; opening it this way once tells macOS you trust it, and it opens
   normally forever after. *Double-clicking the first time will just refuse — use
   right-click → Open.*

<details>
<summary>If macOS says the app "is damaged and can't be opened"</summary>

That message means the quarantine flag survived the download. Open **Terminal** and run:

```bash
xattr -dr com.apple.quarantine "/Applications/SHEET auto FILL.app"
```

Then open it normally.
</details>

### Option B — run from the source (no warnings, always works)

Needs the free **Python 3** from [python.org](https://www.python.org/downloads/macos/).

1. Download the project (green **Code** button → *Download ZIP*, then unzip — or
   `git clone` it).
2. Open the **`mac`** folder and double-click **`install_mac.command`**. It builds a
   private environment inside the folder and installs everything — a few minutes, once.
3. From then on, double-click **`mac/run_mac.command`** to start the app.

If macOS blocks a `.command` file, right-click it → **Open** the first time (same as
above), or run `chmod +x mac/*.command` in Terminal.

Everything else — connecting the sheet, dropping PDFs, the preview table — works
identically on both platforms.

---

## Daily use

1. Pick the **target tab** (defaults to the newest month tab).
2. **Drop your files** — portal PDFs, screenshots, or CSV exports. Several at once is fine.
3. Optionally open **Defaults for these jobs** and set *Company*, *Team leader*,
   *Dispatcher*, *Job status*. These are your internal columns that the portal PDF never
   contains, so they get filled in automatically wherever the file has no value.
4. Click **Extract jobs**. Scanned/screenshot PDFs take roughly **15 seconds per page** —
   that's the offline OCR working; there's a live counter so you can see it progressing.
5. **Review** the table. Red cells are missing required values; the Status column shows
   whether each Job ID is *New* (will be inserted) or *Update* (edited in place), and
   flags duplicates. Edit any cell directly. Nothing touches the sheet yet.
6. Click **Push to Google Sheet** and confirm. Each row reports what happened
   (inserted at row N / updated row N / error).

### If Google isn't connected (or you'd rather paste manually)

Use **Copy rows for pasting**, choose the layout that matches the tab (*no CAP* for the
July-onward tabs, *with CAP* for June), then in Google Sheets click the first empty cell
in column A under your last job and press **Ctrl+V**. **Download CSV** saves the same data
as a file.

---

## What gets read from a portal PDF

Verified against a real JOUS/DMG job page:

| Sheet column | Comes from |
|---|---|
| Job ID | **Work Number** |
| SOW | **Scope** + **Special Instructions** |
| NTE | **NTE** |
| Address / City | the store address under the client name |
| Deadline | **Schedule Date** |
| Job status | the status badge (e.g. *On Hold*) |
| Assignee / phone | **DMG Contact** and its **Phone Number** |
| Updates | any open task, e.g. *Technician Requested – NTE Increase* |
| Company | detected when named in the page, otherwise from your defaults |

**Handy man**, **Team leader**, **Dispatcher**, **Payout**, **Cost** and **JMG** are your own
internal columns — the portal doesn't contain them, so they're left blank for you to fill
(or set once per batch in *Defaults for these jobs*). The portal's "Primary Technician" is
deliberately **not** copied into Handy man, because it names your own account rather than
the local tech you assign.

---

## Connecting Google Sheets (one time, free, ~5 minutes)

Do this **inside the app** — the panel **Connect your Google Sheet** walks you through it
and there are no files to rename or move by hand. It costs nothing and Google does **not**
ask for a payment method.

**Step 1 in the app — which sheet.** Open your spreadsheet in a browser, copy the address
bar, paste it into step 1, click **Save**. (A bare sheet ID works too.)

**Step 2 in the app — the key.** You need a free Google "service account", which is just a
robot account the app signs in as. In your browser:

1. Go to <https://console.cloud.google.com> and sign in with the account that owns the sheet.
2. Create a project (any name, e.g. `sheet-auto-fill`) and wait for it to become active.
3. Search for **"Google Sheets API"** and click **Enable**.
4. Search for **Service Accounts** → **+ Create service account** → give it a name →
   **Create and Continue** → **Continue** → **Done**.
5. Click the new account → **Keys** tab → **Add key → Create new key → JSON → Create**.
   A `.json` file downloads.
6. **Drag that file onto step 2 in the app.** It's stored next to the app for you.

**Step 3 in the app — share the sheet.** The app now shows the robot's email address with a
**Copy** button. Copy it, open your Google Sheet, click **Share**, paste it, set it to
**Editor**, and send. Then click **Test the connection** in the app — it should report the
number of tabs it found.

That's it. **Push to Google Sheet** now works, and the panel collapses itself.

---

## How writing works

- The tool reads the tab's **actual header row**, so tabs with different columns
  (June has CAP, July doesn't) map correctly, including the two "Phone N." columns.
- **Existing Job IDs** are updated cell-by-cell; only non-empty values overwrite.
- **New jobs** are inserted directly below the last `JOB-…` row, inheriting the formatting
  of the row above, which keeps the Expenses/Revenue formulas below intact.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Google Sheet: not connected" | Work through **Connect your Google Sheet** in the app — see the section above. |
| "The key file looks corrupted" | Create a fresh JSON key in Google Cloud and drop it on step 2 again. |
| Windows warns "unrecognized app" on first launch | Expected for any unsigned program. Click **More info → Run anyway**. |
| Mac: "cannot be opened because the developer cannot be verified" | Right-click the app → **Open** → **Open**. Only needed once. |
| Mac: "is damaged and can't be opened" | Run `xattr -dr com.apple.quarantine "/Applications/SHEET auto FILL.app"` in Terminal. |
| Mac: `.command` file won't run | `chmod +x mac/*.command` in Terminal, then double-click again. |
| "access is denied" when pushing | Share the spreadsheet with the service-account email as **Editor**, and confirm the Google Sheets API is enabled. |
| "PDF reading: OCR not installed" | Run `py -m pip install --user -r requirements.txt`, then click **Re-check setup**. |
| "No work-order details could be read" | The page image is too low-resolution. Use a full-size screenshot of the portal page rather than a photo of a screen. |
| A field came out wrong | Fix it in the preview table before pushing — that's what the preview is for. If the same field is wrong every time, tell me which label it sits under and I'll add it to the parser. |
| Extraction feels slow | ~15 seconds per page is normal for OCR; the first extraction of a session also spends a few seconds loading the reader. CSV files are instant. |
| The window is blank | The app needs Microsoft Edge WebView2 (standard on Windows 11). If it's missing, the app falls back to opening in your browser instead — that works the same way. |
| Rate limit errors from Google | You pushed a very large batch — wait a minute and push the rest. |

Configuration lives in [config.yaml](config.yaml) (sheet ID, port, OCR resolution) and
[mapping.yaml](mapping.yaml) (column names and synonyms). If you rename a column in the
spreadsheet, add the new header text to that field's `sheet:` list in mapping.yaml.
