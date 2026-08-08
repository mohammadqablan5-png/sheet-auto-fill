/* SHEET auto FILL — front end */

let STATUS = null;
let rows = [];
let existing = new Set();
let picked = [];

const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/* ============================ theme ============================ */

function applyTheme() {
  const theme = localStorage.getItem('theme') || 'system';
  const accent = localStorage.getItem('accent') || 'blue';
  const dark = theme === 'dark' ||
    (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  document.documentElement.setAttribute('data-accent', accent);

  document.querySelectorAll('#themeSeg button').forEach(b =>
    b.classList.toggle('on', b.dataset.theme === theme));
  document.querySelectorAll('#accentSw .sw').forEach(s =>
    s.classList.toggle('on', s.dataset.accent === accent));
}
applyTheme();
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);

document.querySelectorAll('#themeSeg button').forEach(b => b.onclick = () => {
  localStorage.setItem('theme', b.dataset.theme); applyTheme();
});
document.querySelectorAll('#accentSw .sw').forEach(s => s.onclick = () => {
  localStorage.setItem('accent', s.dataset.accent); applyTheme();
});

/* ============================ status ============================ */

async function loadStatus(recheck) {
  STATUS = await (await fetch('/api/status' + (recheck ? '?recheck=1' : ''))).json();

  const connected = STATUS.sheet_configured && !STATUS.sheet_error;
  setChip('chipSheet', connected,
    connected ? `Sheet: ${STATUS.sheet_title || 'connected'}` : 'Sheet: not connected');
  setChip('chipOcr', STATUS.ocr_ok,
    STATUS.ocr_ok ? 'Reader: ready (offline)' : 'Reader: not installed');

  const notes = [];
  if (!STATUS.sheet_configured) {
    notes.push('No sheet connected — open <b>⚙ Options → Set up the sheet connection</b>. ' +
      'You can still extract, copy rows, and make work-order text without it.');
  } else if (STATUS.sheet_error) {
    notes.push('Sheet problem: ' + esc(STATUS.sheet_error));
  }
  if (!STATUS.ocr_ok) {
    notes.push('The offline PDF reader is missing, so only CSV files can be read. Install once:<br>' +
      '<code>py -m pip install --user rapidocr-onnxruntime pypdfium2 pdfplumber</code>');
  }
  $('setupNotes').innerHTML = notes.map(n => `<div class="setup">${n}</div>`).join('');

  $('connSummary').innerHTML = connected
    ? `Connected via ${STATUS.mode === 'webapp' ? 'the sheet script' : 'a service account'}` +
      `${STATUS.sheet_title ? ' — <b>' + esc(STATUS.sheet_title) + '</b>' : ''}, ` +
      `${STATUS.tabs.length} tab(s).`
    : 'Not connected yet.';

  const sel = $('tabSelect'), keep = sel.value;
  sel.innerHTML = '';
  if (STATUS.tabs.length) {
    STATUS.tabs.forEach((t, i) => {
      const o = document.createElement('option');
      o.value = t; o.textContent = t;
      if (t === keep || (keep === 'latest' && i === STATUS.tabs.length - 1)) o.selected = true;
      sel.appendChild(o);
    });
  } else {
    sel.innerHTML = '<option value="latest">Latest tab</option>';
  }

  refreshConnectPanel();
  renderStats();
  await loadLayout();
}

$('tabSelect').onchange = () => loadLayout();

function setChip(id, ok, text) {
  const el = $(id);
  el.className = 'chip ' + (ok ? 'ok' : 'bad');
  el.innerHTML = `<i class="dot"></i>${esc(text)}`;
}

/* ============================ stat tiles ============================ */

function renderStats() {
  const box = $('stats');
  if (!rows.length) { box.innerHTML = ''; return; }

  let isNew = 0, isUpd = 0, warned = 0, nte = 0;
  rows.forEach(r => {
    const id = (r.job_id || '').trim();
    if (!id) warned++;
    else if (existing.has(id)) isUpd++; else isNew++;
    if (r._warnings && r._warnings.length) warned++;
    const n = parseFloat(String(r.nte || '').replace(/[^0-9.]/g, ''));
    if (!isNaN(n)) nte += n;
  });

  const tiles = [
    { num: rows.length, lbl: 'jobs ready', cls: '' },
    { num: isNew, lbl: 'to insert', cls: 'is-new' },
    { num: isUpd, lbl: 'to update', cls: 'is-upd' },
    { num: nte.toLocaleString(undefined, { style: 'currency', currency: 'USD',
                                           maximumFractionDigits: 0 }), lbl: 'total NTE', cls: '' },
    { num: warned, lbl: 'need a look', cls: warned ? 'is-warn' : '' },
  ];
  box.innerHTML = tiles.map(t =>
    `<div class="stat ${t.cls}"><div class="num">${esc(t.num)}</div>` +
    `<div class="lbl">${esc(t.lbl)}</div></div>`).join('');
}

/* ============================ options / dialogs ============================ */

$('optionsBtn').onclick = () => $('optDlg').showModal();
$('openConnBtn').onclick = () => { $('optDlg').close(); $('connDlg').showModal(); };
$('openTplBtn').onclick = async () => { $('optDlg').close(); await openTemplate(); };
$('editTplBtn').onclick = () => openTemplate();

async function openTemplate() {
  const res = await (await fetch('/api/post', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rows: rows.length ? clean([rows[0]]) : [{ job_id: 'JOB-EXAMPLE' }] })
  })).json();
  $('postTpl').value = res.template || '';
  $('tplMsg').textContent = '';
  $('tplDlg').showModal();
}

$('saveTplBtn').onclick = async () => {
  const res = await (await fetch('/api/post/template', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ template: $('postTpl').value })
  })).json();
  if (res.error) { $('tplMsg').innerHTML = `<span class="err-t">${esc(res.error)}</span>`; return; }
  $('tplMsg').innerHTML = '<span class="ok-t">✔ Saved.</span>';
  if (rows.length) await refreshPost();
};

$('resetTplBtn').onclick = async () => {
  const res = await (await fetch('/api/post/template/default')).json();
  $('postTpl').value = res.template || '';
  $('tplMsg').textContent = 'Default restored — press Save layout to keep it.';
};

/* ============================ connect ============================ */

function markStep(pane, n, done) {
  const steps = pane.querySelectorAll('.step');
  if (steps[n - 1]) steps[n - 1].classList.toggle('done', !!done);
}

function refreshConnectPanel() {
  const connected = STATUS.sheet_configured && !STATUS.sheet_error;

  if (STATUS.webapp_url) $('scriptUrl').value = STATUS.webapp_url;
  markStep($('paneEasy'), 3, STATUS.mode === 'webapp' && connected);

  if (STATUS.sheet_id) $('sheetUrl').value =
    `https://docs.google.com/spreadsheets/d/${STATUS.sheet_id}/edit`;
  markStep($('paneAdv'), 1, !!STATUS.sheet_id);
  markStep($('paneAdv'), 2, !!STATUS.sa_email);
  markStep($('paneAdv'), 3, STATUS.mode === 'service_account' && connected);

  if (STATUS.sa_email) {
    $('shareBox').innerHTML =
      `<code id="saEmail">${esc(STATUS.sa_email)}</code> ` +
      `<button class="tiny" onclick="copyEmail()">Copy</button>` +
      (STATUS.sheet_id ? ` <a href="https://docs.google.com/spreadsheets/d/${STATUS.sheet_id}/edit"
         target="_blank">Open the sheet</a>` : '');
  }
}

$('tabEasy').onclick = () => switchPane(true);
$('tabAdv').onclick = () => switchPane(false);
function switchPane(easy) {
  $('tabEasy').classList.toggle('on', easy);
  $('tabAdv').classList.toggle('on', !easy);
  $('paneEasy').style.display = easy ? '' : 'none';
  $('paneAdv').style.display = easy ? 'none' : '';
}

let scriptCode = '';
async function getScript() {
  if (!scriptCode) scriptCode = (await (await fetch('/api/connect/script/code')).json()).code;
  return scriptCode;
}
async function copyScript(msgEl) {
  const code = await getScript();
  try {
    await navigator.clipboard.writeText(code);
    msgEl.innerHTML = '<span class="ok-t">✔ Copied — paste into the Apps Script editor.</span>';
  } catch {
    $('scriptText').value = code; $('scriptDlg').showModal();
    msgEl.innerHTML = 'Select all in the box and copy.';
  }
}
$('copyScriptBtn').onclick = () => copyScript($('scriptMsg'));
$('copyScriptBtn2').onclick = () => copyScript($('scriptMsg'));
$('viewScriptBtn').onclick = async () => {
  $('scriptText').value = await getScript(); $('scriptDlg').showModal();
};

$('saveScriptBtn').onclick = async () => {
  const msg = $('scriptUrlMsg');
  msg.innerHTML = 'Checking the link…';
  const res = await (await fetch('/api/connect/script', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: $('scriptUrl').value })
  })).json();
  if (res.error) { msg.innerHTML = `<span class="err-t">${esc(res.error)}</span>`; return; }
  msg.innerHTML = `<span class="ok-t">✔ Connected to “${esc(res.title)}” — ${res.tabs.length} tab(s).</span>`;
  await loadStatus(true);
};

$('saveSheetBtn').onclick = async () => {
  const msg = $('sheetMsg');
  msg.innerHTML = 'Saving…';
  const res = await (await fetch('/api/connect/sheet', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sheet: $('sheetUrl').value })
  })).json();
  msg.innerHTML = res.error ? `<span class="err-t">${esc(res.error)}</span>`
                            : '<span class="ok-t">✔ Saved.</span>';
  if (!res.error) await loadStatus(true);
};

const keyDrop = $('keyDrop'), keyInput = $('keyInput');
keyDrop.onclick = () => keyInput.click();
keyDrop.ondragover = e => { e.preventDefault(); keyDrop.classList.add('hover'); };
keyDrop.ondragleave = () => keyDrop.classList.remove('hover');
keyDrop.ondrop = e => { e.preventDefault(); keyDrop.classList.remove('hover');
                        sendKey(e.dataTransfer.files[0]); };
keyInput.onchange = () => sendKey(keyInput.files[0]);

async function sendKey(file) {
  if (!file) return;
  const msg = $('keyMsg');
  msg.innerHTML = 'Reading the key…';
  const fd = new FormData(); fd.append('key', file);
  const res = await (await fetch('/api/connect/key', { method: 'POST', body: fd })).json();
  msg.innerHTML = res.error ? `<span class="err-t">${esc(res.error)}</span>`
                            : '<span class="ok-t">✔ Key saved. Now do step 3.</span>';
  if (!res.error) await loadStatus(true);
}

$('testBtn').onclick = async () => {
  $('testMsg').textContent = ' Checking…';
  await loadStatus(true);
  $('testMsg').innerHTML = (STATUS.sheet_configured && !STATUS.sheet_error)
    ? `<span class="ok-t">✔ Connected — ${STATUS.tabs.length} tab(s).</span>`
    : `<span class="err-t">${esc(STATUS.sheet_error || 'No key yet — do step 2.')}</span>`;
};

function copyEmail() {
  const el = $('saEmail');
  if (el) navigator.clipboard.writeText(el.textContent.trim())
    .then(() => { el.style.background = 'var(--good-soft)'; }).catch(() => {});
}

/* ============================ files ============================ */

const drop = $('drop'), fi = $('fileInput');
drop.onclick = () => fi.click();
drop.ondragover = e => { e.preventDefault(); drop.classList.add('hover'); };
drop.ondragleave = () => drop.classList.remove('hover');
drop.ondrop = e => { e.preventDefault(); drop.classList.remove('hover'); addFiles(e.dataTransfer.files); };
fi.onchange = () => addFiles(fi.files);

function addFiles(list) {
  for (const f of list) picked.push(f);
  $('fileReports').innerHTML = picked.map(f => `<div>📄 ${esc(f.name)}</div>`).join('');
  $('extractBtn').disabled = picked.length === 0;
}

$('extractBtn').onclick = async () => {
  const fd = new FormData();
  picked.forEach(f => fd.append('files', f));
  fd.append('tab', $('tabSelect').value);
  ['company', 'team_leader', 'dispatcher', 'job_status'].forEach(f => {
    const v = $('d_' + f).value.trim();
    if (v) fd.append('default_' + f, v);
  });

  const scanning = picked.some(f => !/\.csv$/i.test(f.name));
  const t0 = Date.now(), spin = $('extractSpin');
  spin.textContent = scanning ? ' Reading the pages… about 15s per page, all offline.' : ' Working…';
  const timer = scanning ? setInterval(() => {
    spin.textContent = ` Reading the pages… ${Math.round((Date.now() - t0) / 1000)}s ` +
                       `(about 15s per page, all offline).`;
  }, 1000) : null;
  $('extractBtn').disabled = true;

  try {
    const res = await (await fetch('/api/extract', { method: 'POST', body: fd })).json();
    if (res.error) { alert(res.error); return; }
    $('fileReports').innerHTML = res.files.map(r =>
      `<div class="${r.ok ? 'ok-t' : 'err-t'}">${r.ok ? '✔' : '✖'} ${esc(r.name)} — ${esc(r.message)}</div>`
    ).join('');
    existing = new Set(res.existing || []);
    rows = rows.concat(res.rows);
    picked = [];
    renderGrid();
    await refreshPost();
  } catch (e) {
    alert('Extraction failed: ' + e);
  } finally {
    if (timer) clearInterval(timer);
    $('extractBtn').disabled = picked.length === 0;
    spin.textContent = '';
  }
};

/* ============================ output tabs ============================ */

$('oTabSheet').onclick = () => showOut('sheet');
$('oTabPost').onclick = () => showOut('post');
function showOut(which) {
  const isSheet = which === 'sheet';
  $('oTabSheet').classList.toggle('on', isSheet);
  $('oTabPost').classList.toggle('on', !isSheet);
  $('paneSheet').style.display = isSheet ? '' : 'none';
  $('panePost').style.display = isSheet ? 'none' : '';
}

/* ============================ output 1: grid ============================ */

function renderGrid() {
  $('outCard').style.display = rows.length ? '' : 'none';
  renderStats();

  const thead = $('grid').querySelector('thead');
  const tbody = $('grid').querySelector('tbody');
  thead.innerHTML = '<tr><th></th><th>Status</th>' +
    STATUS.fields.map(f => `<th>${esc(STATUS.labels[f])}</th>`).join('') + '</tr>';
  tbody.innerHTML = '';

  const seen = {};
  rows.forEach(r => { const j = (r.job_id || '').trim(); if (j) seen[j] = (seen[j] || 0) + 1; });

  rows.forEach((r, idx) => {
    const tr = document.createElement('tr');

    const tdAct = document.createElement('td');
    tdAct.className = 'act';
    tdAct.innerHTML = `<button class="iconbtn" title="Remove">✕</button>`;
    tdAct.querySelector('button').onclick = () => {
      rows.splice(idx, 1); renderGrid(); refreshPost();
    };
    tr.appendChild(tdAct);

    const jid = (r.job_id || '').trim();
    const tdSt = document.createElement('td');
    tdSt.className = 'act';
    let cls, txt;
    if (!jid) { cls = 'err'; txt = 'No ID'; }
    else if (existing.has(jid)) { cls = 'upd'; txt = 'Update'; }
    else { cls = 'new'; txt = 'New'; }
    tdSt.innerHTML = `<span class="pill ${cls}">${txt}</span>` +
      (jid && seen[jid] > 1 ? ' <span class="pill err">duplicate</span>' : '');
    if (r._warnings && r._warnings.length) {
      tdSt.innerHTML += `<div class="warnlist">${esc(r._warnings.join(' · '))}</div>`;
    }
    tr.appendChild(tdSt);

    STATUS.fields.forEach(f => {
      const td = document.createElement('td');
      const long = (f === 'sow' || f === 'address' || f === 'updates');
      const el = document.createElement(long ? 'textarea' : 'input');
      el.value = r[f] || '';
      if (long) { el.rows = 2; el.style.minWidth = f === 'sow' ? '320px' : '230px'; }
      else { el.style.minWidth = f === 'job_id' ? '155px' : '105px'; }
      el.oninput = () => { r[f] = el.value; };
      el.onchange = () => { renderGrid(); refreshPost(); };
      if ((r._warnings || []).some(w => w.startsWith(STATUS.labels[f]))) td.className = 'miss';
      td.appendChild(el);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

$('addRowBtn').onclick = () => {
  const empty = {}; (STATUS.all_fields || STATUS.fields).forEach(f => empty[f] = '');
  empty._warnings = [];
  rows.push(empty); renderGrid(); refreshPost();
};

/* ============================ output 2: work-order text ============================ */

function clean(rs) {
  return rs.map(r => { const c = { ...r }; delete c._warnings; return c; });
}

async function refreshPost() {
  if (!rows.length) return;
  const sel = $('postWhich'), keep = sel.value;
  sel.innerHTML = '<option value="all">All jobs</option>' + rows.map((r, i) =>
    `<option value="${i}">${esc(r.job_id || '(no ID)')}</option>`).join('');
  sel.value = (keep && [...sel.options].some(o => o.value === keep)) ? keep : (rows.length > 1 ? 'all' : '0');
  await renderPostText();
}

$('postWhich').onchange = () => renderPostText();

async function renderPostText() {
  const which = $('postWhich').value;
  const subset = which === 'all' ? rows : [rows[Number(which)]].filter(Boolean);
  if (!subset.length) return;
  const res = await (await fetch('/api/post', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rows: clean(subset) })
  })).json();
  if (res.error) { $('postMsg').innerHTML = `<span class="err-t">${esc(res.error)}</span>`; return; }
  $('postText').value = res.text;
  $('postMsg').textContent = '';
}

$('copyPostBtn').onclick = async () => {
  try {
    await navigator.clipboard.writeText($('postText').value);
    $('copyPostBtn').textContent = '✔ Copied';
    setTimeout(() => { $('copyPostBtn').textContent = 'Copy for Discord'; }, 1600);
  } catch {
    $('postText').select();
    $('postMsg').textContent = 'Press Ctrl+C to copy.';
  }
};

/* ============================ export ============================ */

// The column order is read from the target tab, because tabs can differ and a
// guessed order silently shifts everything after the first mismatched column.
let LAYOUT = { fields: [], headers: [], source: 'preset', presets: {} };

async function loadLayout() {
  const tab = $('tabSelect').value;
  LAYOUT = await (await fetch(`/api/layout?tab=${encodeURIComponent(tab)}`)).json();

  $('layoutNote').innerHTML = LAYOUT.source === 'sheet'
    ? `<span class="ok-t">Columns read from “${esc($('tabSelect').value)}” — ` +
      `${LAYOUT.columns} columns.</span>`
    : `Not connected — using the standard ${LAYOUT.columns}-column layout.`;
}

const cell = v => (v == null ? '' : String(v).replace(/[\t\r\n]+/g, ' ').trim());
const exportMatrix = () =>
  rows.map(r => LAYOUT.fields.map(f => (f ? cell(r[f]) : '')));

$('copyBtn').onclick = async () => {
  const tsv = exportMatrix().map(r => r.join('\t')).join('\n');
  try {
    await navigator.clipboard.writeText(tsv);
    $('pushResults').innerHTML = `<div class="ok-t">✔ ${rows.length} row(s) copied. ` +
      `In Google Sheets click the first empty cell in column A under your last job, then Ctrl+V.</div>`;
  } catch {
    $('pushResults').innerHTML = `<div class="warn-t">Clipboard blocked — use Download CSV.</div>`;
  }
};

$('csvBtn').onclick = () => {
  const q = v => `"${String(v).replace(/"/g, '""')}"`;
  const head = LAYOUT.headers.length
    ? LAYOUT.headers
    : LAYOUT.fields.map(f => STATUS.labels[f] || f);
  const csv = [head.map(q).join(',')]
    .concat(exportMatrix().map(r => r.map(q).join(','))).join('\r\n');
  const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: 'text/csv' }));
  const a = document.createElement('a');
  a.href = url; a.download = `jobs_${new Date().toISOString().slice(0, 10)}.csv`; a.click();
  URL.revokeObjectURL(url);
};

/* ============================ push ============================ */

$('pushBtn').onclick = async () => {
  if (!rows.length) return;
  const tab = $('tabSelect').value;
  const where = tab === 'latest' ? 'the latest tab' : `tab "${tab}"`;
  if (!confirm(`Write ${rows.length} job(s) to ${where}?`)) return;

  $('pushBtn').disabled = true; $('pushSpin').textContent = ' Writing…';
  try {
    const res = await (await fetch('/api/push', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tab, rows: clean(rows) })
    })).json();
    if (res.error) { $('pushResults').innerHTML = `<div class="err-t">✖ ${esc(res.error)}</div>`; return; }
    $('pushResults').innerHTML = res.results.map(x => {
      const c = x.action === 'error' ? 'err-t' : (x.action === 'updated' ? 'warn-t' : 'ok-t');
      return `<div class="${c}">${x.action === 'error' ? '✖' : '✔'} ` +
             `${esc(x.job_id || '(no id)')} — ${esc(x.message)}</div>`;
    }).join('');
    const ok = new Set(res.results.filter(x => x.action !== 'error').map(x => x.job_id));
    rows = rows.filter(r => !ok.has((r.job_id || '').trim()));
    ok.forEach(id => existing.add(id));
    renderGrid();
    if (rows.length) refreshPost();
    $('outCard').style.display = '';
  } catch (e) {
    $('pushResults').innerHTML = `<div class="err-t">✖ Push failed: ${esc(e)}</div>`;
  } finally {
    $('pushBtn').disabled = false; $('pushSpin').textContent = '';
  }
};

loadStatus();
