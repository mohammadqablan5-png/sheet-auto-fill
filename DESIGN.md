# Design — PDF/CSV → Google Sheets auto-fill

This document covers the design decisions behind the tool in this folder, organized by
the seven concerns raised in the requirements.

## Architecture at a glance

```
┌─────────────┐   upload   ┌────────────────────────────────────┐
│  Browser    │ ─────────▶ │  Flask app (app.py, 127.0.0.1)     │
│  preview &  │            │  extractors.py                     │
│  edit UI    │ ◀───────── │   ├─ CSV: header mapping           │
│(index.html) │ rows JSON  │   ├─ PDF text: local_parse.py      │
└─────┬───────┘            │   └─ image PDF: ocr.py (300 DPI)   │
      │ push               │        └─ portal_parse.py (spatial)│
      ▼                    │  normalize.py (validation)         │
┌────────────┐             │  sheets_client.py (gspread)        │
│  Google    │ ◀────────── └────────────────────────────────────┘
│  Sheet     │   upsert
└────────────┘
```

Everything runs locally and free. The only outbound network call in the whole system is
the Google Sheets write.

## 1. Data extraction

**Constraint: zero running cost.** No hosted API is used; everything runs locally.
Three tiers, chosen per file:

- **CSV** (`extractors.extract_csv`): delimiter sniffing, UTF-8-BOM tolerant, and
  header→field mapping from the synonym lists in `mapping.yaml`. Instant and fully
  deterministic.
- **PDF with a text layer** (`local_parse`): text is pulled with pdfplumber (pypdf as
  fallback) and fields are located by labelled-value lookup plus patterns for job
  numbers, money, dates, phones, and `City, ST ZIP` lines.
- **Image-only PDF / screenshot** (`ocr` + `portal_parse`): pypdfium2 renders each page
  at 300 DPI and rapidocr-onnxruntime (ONNX, offline, no account) reads it. The real
  work-order PDFs are portal screenshots with no text layer, so this is the primary path.

**Why a spatial parser rather than text scraping.** OCR output of a multi-column page
interleaves badly when flattened to lines, and it drops spaces ("ScheduleDate",
"Connormccoy"). `portal_parse` therefore keeps each text box's coordinates and reads the
layout directly: the portal renders every field as a **label with its value directly
underneath**, so `_value_below()` finds the value by left-edge alignment and vertical
proximity, and `_paragraph_below()` collects multi-line blocks (Scope) until the next
label or a paragraph gap. Label matching folds OCR look-alikes (I/l/1/| and O/0) on both
sides of the comparison, so "Speciallnstructions" still matches.

Resolution was chosen empirically: at 220 DPI the detector dropped alternate lines of the
Scope paragraph; at 400 DPI it dropped a different line and ran ~65% slower. 300 DPI
captured every line with correct word spacing, at ~15 s/page.

Multi-page documents are merged into one job; a page carrying a different work number
starts a new job, so both single-job and multi-job PDFs work.

Data integrity: nothing is inferred that the document doesn't state. The portal's
"Primary Technician" is deliberately **not** mapped to the sheet's Handy man column,
because it names the account holder rather than the assigned local tech — mapping it
would inject systematically wrong data. Internal-only columns are instead filled from
user-supplied batch defaults.

## 2. Data mapping

A single canonical field list (`mapping.yaml`) drives everything: the extraction schema,
the CSV header synonyms, the preview column order, and the sheet column lookup. Schema
variations are absorbed at two points:

- **Input side**: synonym lists per field (`csv:` + `sheet:` labels) map arbitrary
  export headers onto canonical fields; unknown layouts fall back to LLM mapping.
- **Output side**: the target tab's real header row is located (the row containing
  "SOW") and parsed *at push time*, so each monthly tab's exact layout is respected —
  including the June tab's extra CAP column and the two ambiguous "Phone N." columns,
  which are resolved by position (1st → handyman, 2nd → assignee).

Adding a field or synonym is a YAML edit, no code change.

## 3. Data preview

Extraction never writes directly. All rows land in an editable grid where the user can:

- fix any cell inline (SOW/address as multi-line editors),
- see validation flags — missing required fields (red), unparseable money/dates/phones,
  suspicious Job IDs,
- see the **action preview** per row: *New* (insert) vs *Update* (Job ID already in the
  target tab) vs duplicate-within-batch warnings,
- delete rows or add blank ones.

Only "Push" (with a confirmation dialog) touches the sheet, and each row reports its
outcome afterwards. Successfully pushed rows leave the grid; failed ones stay for retry.

## 4. Google Sheets integration

- **Auth**: a Google Cloud **service account** with a local JSON key; the sheet is shared
  with the service-account email as Editor. No OAuth browser flows, no password handling,
  and access can be revoked by unsharing or deleting the key.
- **In-app connection wizard**: three steps inside the window rather than manual file
  surgery. `POST /api/connect/sheet` accepts a pasted spreadsheet URL *or* a bare ID,
  extracts the ID, and rewrites only that key in `config.yaml` (regex line replacement, so
  comments and other settings survive). `POST /api/connect/key` accepts the downloaded
  JSON, validates it is `type: service_account` with a `client_email` before storing it
  beside the app, and returns only the email — the private key is never echoed back to the
  page. Each step reports its own failure in plain language (wrong file type, wrong JSON
  kind, corrupted key, sheet not shared), and **Test the connection** proves the whole
  chain by listing the tabs it can see.
- **Writes** (`sheets_client.py`, gspread over the official Sheets REST API):
  - *Upsert by Job ID*: column A is scanned for `JOB…` values; existing rows are
    updated via a single `batch_update` per row (only non-empty values overwrite).
  - *Inserts* go directly below the last job row via `insert_row(...,
    inherit_from_before=True)`, which pushes the Expenses/Revenue block down and lets
    `SUM` ranges auto-expand, and inherits the currency/date formatting of the row above.
  - `USER_ENTERED` value input so numbers and dates take the sheet's native types.
- **Real-time enough**: writes are synchronous; results (row numbers) are reported per row.

## 5. Error handling

- Per-file isolation: one unreadable file reports its error; the rest of the batch
  still extracts.
- Typed error paths with human-readable messages: OCR not installed (with the exact pip
  command), image-only PDF that yields no fields, unrecognized CSV headers, Google 403
  (with the exact share-this-email fix), 404 (bad sheet id), 429 (rate limit).
- Layered fallback on read: text layer → spatial OCR parse → flattened-text parse. A page
  the spatial parser can't interpret still gets a generic pass before the file is
  reported as unreadable.
- Per-row push isolation: a failing row doesn't abort the batch; each row returns
  `inserted` / `updated` / `error` with a message, and failed rows remain in the
  preview for correction and retry.
- Validation before write, not after: required-field and format issues are surfaced in
  the preview so bad data is caught by a human before it reaches the sheet.

## 6. Automation & scalability

Current scale (dozens of jobs/week) is handled comfortably; the design leaves clear
seams for growth:

- **Batching**: multiple files per extraction round; row updates are one API call each,
  inserts one each — well inside Google's 60 write-requests/min quota for typical
  batches. For much larger batches, the insert path can be switched to a single
  `insertDimension` + `values.batchUpdate` request pair.
- **Scheduling / watch-folder**: the extraction and push layers are plain functions
  (`extract_file`, `SheetClient.push_rows`), so a headless mode (e.g. a Windows Task
  Scheduler job watching an `inbox/` folder, auto-pushing rows with zero warnings and
  parking the rest for review) is an incremental addition, not a rewrite.
- **Throughput**: OCR is CPU-bound at ~15 s/page and single-threaded per request. Batches
  of many PDFs can be parallelized across cores with a process pool, since page parsing
  is independent — the natural next step if daily volume grows.
- **Multi-sheet**: `sheet_id` is config; running against a new month/workbook needs no
  code change.

## 6b. Packaging as a desktop app

The tool ships as a single `SHEET auto FILL.exe` (PyInstaller onefile, `build_exe.spec`)
so the end user never installs Python or runs a command. `desktop.py` starts the Flask
app on an ephemeral loopback port in a daemon thread, waits for `/api/status` to answer,
then displays it in a native window via pywebview (Edge WebView2). If WebView2 is
unavailable it falls back to the default browser rather than failing.

Two packaging details matter for correctness:

- **ONNX models and native DLLs** (rapidocr-onnxruntime, onnxruntime, pypdfium2, cv2)
  are pulled in with `collect_all` rather than left to module analysis, which only
  follows imports and would miss the model files.
- **User-owned files stay outside the bundle.** `resources.py` distinguishes the
  read-only bundle (`sys._MEIPASS`) from the folder holding the .exe. `config.yaml` and
  `mapping.yaml` are copied out on first run so they remain editable, and
  `service_account.json` is only ever read from the .exe's folder — the Google key is
  never compiled into the binary.

## 7. Security & compliance

- **Credential handling**: the only credential is the Google service-account key, held in
  a local `.gitignore`d file; nothing is hardcoded.
- **Least privilege**: the service account has access to exactly the spreadsheets you
  share with it — not your Drive. Revoke by unsharing or deleting the key in Google
  Cloud Console.
- **Data flows**: work-order contents are never transmitted anywhere — parsing and OCR run
  entirely on the local CPU. The single outbound connection is to Google Sheets when you
  press Push. The app binds to `127.0.0.1` only, so it is not reachable from the network.
- **PII**: rows contain names and phone numbers of technicians/contacts. Keeping the
  workbook's own sharing settings tight is the main control; the tool adds no extra
  storage — uploaded files are processed in memory and not saved.
- **Auditability**: every push reports exactly which rows were inserted/updated, and
  Google Sheets version history provides rollback for any bad write.
