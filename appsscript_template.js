/**
 * SHEET auto FILL — sheet connector
 * -------------------------------------------------------------
 * Paste this into your spreadsheet's Apps Script editor and deploy it as a
 * Web App. It lets the desktop app add and update job rows in THIS sheet only.
 *
 * The app fills in the key below automatically — treat it like a password.
 */
const APP_KEY = "__APP_KEY__";

function doGet(e) {
  if (!e || !e.parameter || e.parameter.key !== APP_KEY) return _json({ error: "Wrong key." });
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  return _json({
    ok: true,
    title: ss.getName(),
    tabs: ss.getSheets().map(function (s) { return s.getName(); })
  });
}

function doPost(e) {
  try {
    const req = JSON.parse(e.postData.contents);
    if (req.key !== APP_KEY) return _json({ error: "Wrong key." });

    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheets = ss.getSheets();
    const sheet = (!req.tab || req.tab === "latest")
      ? sheets[sheets.length - 1]
      : ss.getSheetByName(req.tab);
    if (!sheet) return _json({ error: 'Tab "' + req.tab + '" was not found.' });

    if (req.action === "existing") {
      return _json({ ok: true, job_ids: _jobRows(sheet).ids });
    }

    const values = sheet.getDataRange().getValues();
    const head = _header(values, req.mapping || {}, req.phone_headers || []);
    if (head.error) return _json({ error: head.error });

    if (req.action === "layout") {
      const byCol = {};
      Object.keys(head.cols).forEach(function (f) { byCol[head.cols[f]] = f; });
      const fields = [], headers = [];
      for (let i = 0; i < head.width; i++) {
        fields.push(byCol[i] || "");
        headers.push(String(values[head.row - 1][i] || "").trim());
      }
      return _json({ ok: true, fields: fields, headers: headers, columns: head.width });
    }

    const found = _jobRows(sheet);
    let lastJobRow = found.lastRow || head.row;
    const results = [];

    (req.rows || []).forEach(function (row) {
      const id = String(row.job_id || "").trim();
      if (!id) {
        results.push({ job_id: "", action: "error", message: "Row skipped: no Job ID." });
        return;
      }
      try {
        if (found.map[id]) {
          const r = found.map[id];
          Object.keys(head.cols).forEach(function (field) {
            const v = row[field];
            if (v !== undefined && v !== null && String(v) !== "") {
              sheet.getRange(r, head.cols[field] + 1).setValue(v);
            }
          });
          results.push({ job_id: id, action: "updated", row: r,
                         message: "Updated existing row " + r + "." });
        } else {
          const at = lastJobRow + 1;
          sheet.insertRowAfter(lastJobRow);       // inherits the formatting above
          Object.keys(head.cols).forEach(function (field) {
            const v = row[field];
            if (v !== undefined && v !== null && String(v) !== "") {
              sheet.getRange(at, head.cols[field] + 1).setValue(v);
            }
          });
          found.map[id] = at;
          lastJobRow = at;
          results.push({ job_id: id, action: "inserted", row: at,
                         message: "Inserted as new row " + at + "." });
        }
      } catch (err) {
        results.push({ job_id: id, action: "error", message: String(err) });
      }
    });

    return _json({ ok: true, results: results });
  } catch (err) {
    return _json({ error: String(err) });
  }
}

/**
 * Rows in column A that look like work-order numbers. Most start with "JOB",
 * but other dispatchers use their own prefix (e.g. "NC-260807-0281"), so this
 * matches the shape — otherwise those rows are invisible and get duplicated
 * instead of updated.
 */
const JOB_CELL_RE = /^[A-Za-z]{1,6}[-\s]?\d{4,}/;

function _jobRows(sheet) {
  const col = sheet.getRange(1, 1, Math.max(sheet.getLastRow(), 1), 1).getValues();
  const map = {};
  const ids = [];
  let lastRow = 0;
  for (let i = 0; i < col.length; i++) {
    const v = String(col[i][0] || "").trim();
    if (JOB_CELL_RE.test(v)) {
      map[v] = i + 1;
      ids.push(v);
      lastRow = i + 1;
    }
  }
  return { map: map, ids: ids, lastRow: lastRow };
}

/** Locate the header row and map each field onto its column. */
function _header(values, mapping, phoneHeaders) {
  let rowIdx = -1;
  for (let i = 0; i < Math.min(10, values.length); i++) {
    if (values[i].some(function (c) { return String(c).trim().toLowerCase() === "sow"; })) {
      rowIdx = i;
      break;
    }
  }
  if (rowIdx < 0) return { error: 'Could not find the header row (no "SOW" column) in this tab.' };

  const headers = values[rowIdx].map(function (h) { return String(h).trim().toLowerCase(); });
  const cols = { job_id: 0 };

  const phones = [];
  headers.forEach(function (h, i) { if (phoneHeaders.indexOf(h) >= 0) phones.push(i); });
  if (phones.length >= 1) cols.handyman_phone = phones[0];
  if (phones.length >= 2) cols.assignee_phone = phones[1];

  Object.keys(mapping).forEach(function (field) {
    if (cols[field] !== undefined) return;
    const syns = mapping[field] || [];
    for (let s = 0; s < syns.length; s++) {
      const at = headers.indexOf(String(syns[s]).toLowerCase());
      if (at >= 0) { cols[field] = at; return; }
    }
  });

  return { row: rowIdx + 1, cols: cols, width: headers.length };
}

function _json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
