/* SHEET auto FILL — front end */

let STATUS = null;
let rows = [];
let existing = new Set();
let picked = [];

const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

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
    notes.push('Not connected to a sheet yet — use <b>Connect your Google Sheet</b> below. ' +
      'Extracting, previewing, <b>Copy rows</b> and <b>Work-order posts</b> all work without it.');
  } else if (STATUS.sheet_error) {
    notes.push('Sheet problem: ' + esc(STATUS.sheet_error));
  }
  if (!STATUS.ocr_ok) {
    notes.push('The offline PDF reader is missing, so only CSV files can be read. Install once:<br>' +
      '<code>py -m pip install --user rapidocr-onnxruntime pypdfium2 pdfplumber</code>');
  }
  $('setupNotes').innerHTML = notes.map(n => `<div class="setup">${n}</div>`).join('');

  const sel = $('tabSelect');
  const keep = sel.value;
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
}

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

  const money = nte.toLocaleString(undefined, { style: 'currency', currency: 'USD',
                                                maximumFractionDigits: 0 });
  const tiles = [
    { num: rows.length, lbl: 'jobs ready', cls: '' },
    { num: isNew, lbl: 'to insert', cls: 'is-new' },
    { num: isUpd, lbl: 'to update', cls: 'is-upd' },
    { num: money, lbl: 'total NTE', cls: '' },
    { num: warned, lbl: 'need a look', cls: warned ? 'is-warn' : '' },
  ];
  box.innerHTML = tiles.map(t =>
    `<div class="stat ${t.cls}"><div class="num">${esc(t.num)}</div>` +
    `<div class="lbl">${esc(t.lbl)}</div></div>`).join('');
}

/* ============================ connect panel ============================ */

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
  if (connected) {
    const where = STATUS.mode === 'webapp' ? 'script' : 'service account';
    $('testMsg').innerHTML = `<span class="ok-t">✔ Connected via ${where}.</span>`;
    $('connectBody').style.display = 'none';
    $('connectToggle').textContent = 'Show';
  }
}

$('connectToggle').onclick = () => {
  const b = $('connectBody');
  const hidden = b.style.display === 'none';
  b.style.display = hidden ? '' : 'none';
  $('connectToggle').textContent = hidden ? 'Hide' : 'Show';
};

$('tabEasy').onclick = () => switchPane(true);
$('tabAdv').onclick = () => switchPane(false);
function switchPane(easy) {
  $('tabEasy').classList.toggle('on', easy);
  $('tabAdv').classList.toggle('on', !easy);
  $('paneEasy').style.display = easy ? '' : 'none';
  $('paneAdv').style.display = easy ? 'none' : '';
}

/* --- easy path --- */
let scriptCode = '';
async function getScript() {
  if (!scriptCode) scriptCode = (await (await fetch('/api/connect/script/code')).json()).code;
  return scriptCode;
}
async function copyScript(msgEl) {
  const code = await getScript();
  try {
    await navigator.clipboard.writeText(code);
    msgEl.innerHTML = '<span class="ok-t">✔ Copied — paste it into the Apps Script editor.</span>';
  } catch {
    $('scriptText').value = code;
    $('scriptDlg').showModal();
    msgEl.innerHTML = 'Select all in the box and copy.';
  }
}
$('copyScriptBtn').onclick = () => copyScript($('scriptMsg'));
$('copyScriptBtn2').onclick = () => copyScript($('scriptMsg'));
$('viewScriptBtn').onclick = async () => {
  $('scriptText').value = await getScript();
  $('scriptDlg').showModal();
};

$('saveScriptBtn').onclick = async () => {
  const msg = $('scriptUrlMsg');
  msg.innerHTML = 'Checking the link…';
  const res = await (await fetch('/api/connect/script', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: $('scriptUrl').value })
  })).json();
  if (res.error) { msg.innerHTML = `<span class="err-t">${esc(res.error)}</span>`; return; }
  msg.innerHTML = `<span class="ok-t">✔ Connected to “${esc(res.title)}” — ` +
                  `${res.tabs.length} tab(s).</span>`;
  await loadStatus(true);
};

/* --- advanced path --- */
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
    ? `<span class="ok-t">✔ Connected — ${STATUS.tabs.length} tab(s) found.</span>`
    : `<span class="err-t">${esc(STATUS.sheet_error || 'No key yet — do step 2.')}</span>`;
};

function copyEmail() {
  const el = $('saEmail');
  if (el) navigator.clipboard.writeText(el.textContent.trim())
    .then(() => { el.style.background = 'var(--good-soft)'; }).catch(() => {});
}

$('recheckBtn').onclick = async () => {
  $('recheckBtn').textContent = '…';
  await loadStatus(true);
  if (rows.length) renderGrid();
  $('recheckBtn').textContent = 'Re-check';
};

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
  const t0 = Date.now();
  const spin = $('extractSpin');
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
  } catch (e) {
    alert('Extraction failed: ' + e);
  } finally {
    if (timer) clearInterval(timer);
    $('extractBtn').disabled = picked.length === 0;
    spin.textContent = '';
  }
};

/* ============================ grid ============================ */

function renderGrid() {
  $('previewCard').style.display = rows.length ? '' : 'none';
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
    tdAct.querySelector('button').onclick = () => { rows.splice(idx, 1); renderGrid(); };
    tr.appendChild(tdAct);

    const jid = (r.job_id || '').trim();
    const tdSt = document.createElement('td');
    tdSt.className = 'act';
    let cls, txt;
    if (!jid) { cls = 'err'; txt = 'No ID'; }
    else if (existing.has(jid)) { cls = 'upd'; txt = 'Update'; }
    else { cls = 'new'; txt = 'New'; }
    tdSt.innerHTML = `<span class="pill ${cls}">${txt}</span>` +
      (jid && seen[jid] > 1 ? ' <span class="pill err">duplicate</span>' : '') +
      `<div style="margin-top:5px"><button class="tiny" data-post="${idx}">Post</button></div>`;
    if (r._warnings && r._warnings.length) {
      tdSt.innerHTML += `<div class="warnlist">${esc(r._warnings.join(' · '))}</div>`;
    }
    tdSt.querySelector('[data-post]').onclick = () => showPost([r]);
    tr.appendChild(tdSt);

    STATUS.fields.forEach(f => {
      const td = document.createElement('td');
      const long = (f === 'sow' || f === 'address' || f === 'updates');
      const el = document.createElement(long ? 'textarea' : 'input');
      el.value = r[f] || '';
      if (long) { el.rows = 2; el.style.minWidth = f === 'sow' ? '320px' : '230px'; }
      else { el.style.minWidth = f === 'job_id' ? '155px' : '105px'; }
      el.oninput = () => { r[f] = el.value; };
      el.onchange = () => renderGrid();
      if ((r._warnings || []).some(w => w.startsWith(STATUS.labels[f]))) td.className = 'miss';
      td.appendChild(el);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

$('addRowBtn').onclick = () => {
  const empty = {}; STATUS.fields.forEach(f => empty[f] = '');
  empty._warnings = [];
  rows.push(empty); renderGrid();
};

/* ============================ work-order posts ============================ */

function clean(rs) {
  return rs.map(r => { const c = { ...r }; delete c._warnings; return c; });
}

async function showPost(subset) {
  const res = await (await fetch('/api/post', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rows: clean(subset) })
  })).json();
  if (res.error) { alert(res.error); return; }
  $('postTitle').textContent = subset.length === 1
    ? `Work-order post — ${subset[0].job_id || 'job'}`
    : `Work-order posts — ${subset.length} jobs`;
  $('postText').value = res.text;
  $('postTpl').value = res.template;
  $('tplMsg').textContent = '';
  $('postDlg').showModal();
}

$('postAllBtn').onclick = () => rows.length && showPost(rows);

$('copyPostBtn').onclick = async () => {
  try {
    await navigator.clipboard.writeText($('postText').value);
    $('copyPostBtn').textContent = '✔ Copied';
    setTimeout(() => { $('copyPostBtn').textContent = 'Copy to clipboard'; }, 1600);
  } catch {
    $('postText').select();
    $('tplMsg').textContent = 'Press Ctrl+C to copy.';
  }
};

$('saveTplBtn').onclick = async () => {
  const res = await (await fetch('/api/post/template', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ template: $('postTpl').value })
  })).json();
  $('tplMsg').innerHTML = res.error ? `<span class="err-t">${esc(res.error)}</span>`
                                    : '<span class="ok-t">✔ Saved.</span>';
};

/* ============================ export ============================ */

const LAYOUTS = {
  nocap: ['job_id','sow','nte','cost','address','city','deadline','company','jmg',
          'team_leader','job_status','dispatcher','payout','handyman','handyman_phone',
          'assignee','assignee_phone','updates'],
  cap:   ['job_id','sow','nte','cap','cost','address','city','deadline','company','jmg',
          'team_leader','job_status','dispatcher','payout','handyman','handyman_phone',
          'assignee','assignee_phone','updates'],
};
const cell = v => (v == null ? '' : String(v).replace(/[\t\r\n]+/g, ' ').trim());
const exportMatrix = () =>
  rows.map(r => LAYOUTS[$('layoutSel').value].map(f => cell(r[f])));

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
  const q = v => `"${v.replace(/"/g, '""')}"`;
  const cols = LAYOUTS[$('layoutSel').value];
  const csv = [cols.map(f => q(STATUS.labels[f] || f)).join(',')]
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
    $('previewCard').style.display = '';
  } catch (e) {
    $('pushResults').innerHTML = `<div class="err-t">✖ Push failed: ${esc(e)}</div>`;
  } finally {
    $('pushBtn').disabled = false; $('pushSpin').textContent = '';
  }
};

loadStatus();
