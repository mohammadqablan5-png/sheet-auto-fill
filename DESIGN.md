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
- **PDF with a text layer** (`local_parse.pdf_word_boxes` → `portal_parse`): these are
  *not* read as flat text. The portal's generated PDFs place each glyph individually, so
  `extract_text()` walks the page row by row and interleaves neighbouring columns
  character by character — the address came out as
  `W 81 a 9 l 3 gr M ee a n l 's l R (5 D 7 , 6 F 3 l ) o - r e…`, which is unparseable
  and was silently producing near-empty rows. Instead the glyph boxes are grouped into
  rows and split into phrases wherever the horizontal gap is far wider than the type
  (measured on a real file: intra-word gaps ≈0.02, spaces ≈0.85, column gaps ≫1), which
  reconstructs `Walgreen's (5763) - 8193 Mall Rd` and its neighbour as separate phrases.
  Those boxes then feed **the same spatial parser used for screenshots**, so both PDF
  kinds share one implementation. Flat-text parsing remains only as a last-resort
  fallback.
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

**The workbook's tabs are not uniform, and that drives the design.** The June tab carries
19 columns while the July and August tabs carry 17. Anything that assumes one fixed order
silently corrupts data: with a hardcoded order, `company` lands in column 8 on one tab and
column 7 on another, so every value from that point rightwards is written one cell off. The
push path always read the target tab's real header row; the **copy/CSV path now does too**
(`/api/layout`, mirrored in the Apps Script), with a single fallback layout used only when
no sheet is connected and the headers can't be read.

**CAP and JMG are not modelled at all.** They were dropped from `mapping.yaml` at the
user's request, so they are never extracted, displayed, or written. The June tab still has
those two physical columns; because the writer maps by header name, they are simply left
untouched and the surrounding values stay under their own headings — verified for both the
19- and 17-column layouts. The self-test fails if either field reappears.

Work-order numbers are likewise not all "JOB-…". The sheet contains `NC-260807-0281`, which
an earlier `startswith("JOB")` test skipped entirely — meaning that row could not be found
for an update and would have been duplicated. `jobid.py` matches the *shape* instead, while
excluding same-shaped identifiers that are not work orders (a visit is `VST-260729-7250`),
and the labelled Work Number still wins over anything found loose in the page text.


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

## 3b. Work-order posts

Extraction feeds a second output besides the spreadsheet: a message the crew can read.
`posts.py` renders each row through `post_template.txt`, which mirrors the portal's own
label-above-value layout so the crew reads it in a familiar shape. The template is parsed
as **blocks separated by blank lines**: a block whose placeholders are all empty is
dropped whole, so a section heading such as "Rate" disappears together with its values
instead of being stranded above nothing; within a surviving block, individual missing
lines are dropped. Money fields are formatted on the way out. The template is a plain
text file beside the app, editable from the dialog, so wording changes need no code.

The portal's **Rate** block (regular tech / helper / trip) exists *only* for this text.
It is `hidden: true` in `mapping.yaml`, which keeps it out of the preview table
(`GRID_ORDER`) while remaining available to the renderer (`FIELD_ORDER`), and it carries
no sheet synonyms, so the push path can never map it to a column. The spreadsheet's shape
is therefore untouched by this feature — an important constraint, since the workbook's
expense and profit formulas depend on its column layout.

Two things about the Rate block bit in practice, and both are now regression-tested:

1. **It is laid out in two columns** — Regular Technician beside Helper Technician, Trip
   beside NTE. Values are found by left-edge alignment under each label, so columns don't
   bleed into one another.
2. **"Regular Technician" appears twice on the page** — once under *Assigned Technicians*
   naming a person, once under *Rate* naming a dollar amount. The first version of this
   code shared one key with "Primary Technician" and kept only the first match, so the
   person's name won and **the regular rate was silently dropped** — the output showed
   Helper and Trip but no Regular. Every occurrence of a label is now retained, each rate
   is read from its own key, and only values that parse as money are accepted as rates.

Each rate therefore comes from its own label: a missing helper rate cannot shift the trip
amount up into its place, and NTE (which sits in the same block) is never mistaken for a
rate.

The **address** deliberately carries both lines the portal shows: the store name and number
("Target (0366) - 131 W Reynolds Rd") and the postal line beneath it. The store line is
matched by pattern rather than pure adjacency, and searched a few rows up with a loose
horizontal tolerance, because OCR row heights vary and the map-pin glyph shifts the left
edge — without that, the brand and store number were at risk of being dropped, which is
exactly the part a dispatcher needs to identify the site.

## 3c. Dashboard

**One job on the main screen: uploading.** Everything configural — the sheet connection,
appearance, the work-order layout — sits behind a single **⚙ Options** dialog, so the
first screen is a drop zone, the per-batch defaults, and one button. Setup is a rare
event; it shouldn't occupy the surface a user sees every day.

Extraction then produces **two outputs, presented as tabs** rather than stacked panels,
because they serve different destinations and are used one at a time: *Rows for the sheet*
(the editable table plus push/copy/CSV) and *Work-order text* (the crew message, with a
per-job or all-jobs picker).

The summary strip is **stat tiles, not charts** — the data is five scalars, so a chart
would add chrome without adding information. Status is carried by a labelled pill
("New" / "Update" / "duplicate"), never by colour alone, and the same information is in
the row text, so the table stays readable in greyscale or with any colour-vision
deficiency. Theme (System/Light/Dark) and accent are token swaps on the root element,
persisted in `localStorage`; the accent choice never touches the status colours, which
stay reserved.

## 4. Google Sheets integration

- **Auth**: a Google Cloud **service account** with a local JSON key; the sheet is shared
  with the service-account email as Editor. No OAuth browser flows, no password handling,
  and access can be revoked by unsharing or deleting the key.
- **Two connection paths, same interface.** `WebAppClient` (webapp_client.py) and
  `SheetClient` (sheets_client.py) expose the same `configured / tabs / existing_jobs /
  push_rows` surface, so `app.backend()` simply returns whichever is configured and the
  rest of the app is unaware of the difference.
  - *Easy path* — the user deploys `appsscript_template.js` inside their own spreadsheet
    as a Web App. No Google Cloud project, no service account, no key file, no sharing
    step. The script runs as the sheet's owner, so no credential ever reaches this
    machine; the app authenticates with a random key it generates and bakes into the
    copied script. The upsert logic (header row discovery, phone-column disambiguation,
    insert-after-last-job) is mirrored in the script, and the field→synonym map is sent
    with each request so `mapping.yaml` stays the single source of truth.
  - *Advanced path* — the original service account, unchanged.
- **In-app connection wizard**: steps inside the window rather than manual file
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
  `service_account.json` / `connection.json` are only ever read from the .exe's folder —
  no credential is compiled into the binary.
- **Upgrades must not be shadowed by first-run copies.** Because an external file wins
  over the bundled one, files written beside the app by an older build silently suppressed
  later changes — first a new field in `mapping.yaml` never appeared, then (after a
  per-file fix) the rewritten `post_template.txt` was still ignored, because a plain text
  file has no version field to compare. The fix versions the **asset set** rather than
  each file: `sync_asset_set()` reads one `schema_version` (from `mapping.yaml`), compares
  it against a `.asset_version` marker beside the app, and refreshes every listed asset
  that differs, keeping a `.bak` of each. The self-test asserts both the newest field and
  the current layout are present, so this whole class of regression fails the build
  instead of shipping — it escaped twice before that check existed.

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
