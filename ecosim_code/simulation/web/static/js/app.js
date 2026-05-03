'use strict';
// ══════════════════════════════════════════════════════════════════════════════
// EcoSim — Application web complète
// Pages : SETUP → RUNNING → ANALYSE (tabs: REPLAY | GRAPHES | GÉNÉALOGIE | JOURS)
// ══════════════════════════════════════════════════════════════════════════════

// ── Constantes ────────────────────────────────────────────────────────────────
const CANVAS_W   = 720;
const CANVAS_H   = 576;
const PREVIEW_SZ = 260;
const DAY_LENGTH = 1200;

const SPEED_LEVELS = [0.25, 0.5, 1, 2, 4, 8, 16, 32];
const GROUPS = [
  ['PLANTES',    ['herbe', 'fougere', 'champignon', 'baies']],
  ['HERBIVORES', ['lapin', 'campagnol', 'cerf', 'sanglier']],
  ['PRÉDATEURS', ['renard', 'loup', 'hibou', 'aigle']],
];

// ── État global ───────────────────────────────────────────────────────────────
let ws            = null;
let currentPage   = 'setup';
let currentTab    = 'replay';
let speciesMap    = new Map();   // name → {name, color, params, ...}

// SETUP
let previewTimer  = null;

// RUNNING
let runConfig     = null;

// ANALYSE — commun
let analyseDb     = null;   // chemin .db actif
let analyseMeta   = null;   // métadonnées replay
let timeseriesData = null;  // [{tick, counts}]

// REPLAY tab
let kfTicks       = [];
let kfIdx         = 0;
let frameImgs     = [];
let jsonCache     = new Map();
let popMaxes      = {};
let graphHist     = {};
let graphHidden   = new Set();
let _graphChipsBuilt = false;
let selectedId    = null;
let lastJsonSnap  = null;
let playing       = false;
let rafId         = null;
let nextTarget    = 0;
let speedIdx      = 2;
let playFps       = 1;

// GRAPHS tab
let customCharts  = [];   // [{id, canvasEl, species, type, normalize}]
let gcNextId      = 1;

// GENEALOGY tab
let geneData      = null;

// DAYS tab
let dayCache      = new Map();   // day → {counts, tick}
let statsData     = null;

// ── DOM helpers ───────────────────────────────────────────────────────────────
const $   = id  => document.getElementById(id);
const q   = sel => document.querySelector(sel);
const qq  = sel => document.querySelectorAll(sel);

function setText(id, v) { const e = $(id); if (e) e.textContent = v; }
function setStyle(id, p, v) { const e = $(id); if (e) e.style[p] = v; }

function toast(msg, err = false) {
  const el = $('toast');
  el.textContent = msg;
  el.className   = 'toast' + (err ? ' error' : '');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add('hidden'), 4500);
}

// ── Pages ─────────────────────────────────────────────────────────────────────
function showPage(name) {
  qq('.page').forEach(p => p.classList.remove('active'));
  $(`page-${name}`).classList.add('active');
  currentPage = name;
}

// ── Tabs (ANALYSE page) ───────────────────────────────────────────────────────
function showTab(name) {
  qq('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  qq('.tab-panel').forEach(p => p.classList.toggle('active', p.id === `tab-${name}`));
  currentTab = name;
  if (name === 'graphs' && timeseriesData === null && analyseDb) {
    loadTimeseries();
  }
  if (name === 'days' && timeseriesData === null && analyseDb) {
    loadTimeseries().then(() => renderDayChart());
  }
}

// ── WebSocket ─────────────────────────────────────────────────────────────────
let _ka = null;
function connectWS() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => {
    clearInterval(_ka);
    _ka = setInterval(() => {
      if (ws?.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ type: 'ping' }));
    }, 20000);
  };
  ws.onclose  = () => setTimeout(connectWS, 2000);
  ws.onerror  = () => {};
  ws.onmessage = e => { try { dispatch(JSON.parse(e.data)); } catch (_) {} };
}

function dispatch(msg) {
  switch (msg.type) {
    case 'progress':  onProgress(msg);  break;
    case 'done':      onSimDone(msg);   break;
    case 'error':     onSimError(msg);  break;
    case 'cancelled': showPage('setup'); loadRuns(); break;
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════════════════════════════════
async function init() {
  connectWS();
  await loadSpecies();
  await loadRuns();
  wireSetup();
  wireRunning();
  wireAnalyse();
  schedulePreview(80);
}

// ══════════════════════════════════════════════════════════════════════════════
// SETUP
// ══════════════════════════════════════════════════════════════════════════════
async function loadSpecies() {
  const items = await fetch('/api/species').then(r => r.json()).catch(() => []);
  speciesMap.clear();
  items.forEach(s => speciesMap.set(s.name, s));
  renderSpeciesList(items);
}

function renderSpeciesList(items) {
  const cont   = $('species-list');
  cont.innerHTML = '';
  const byFile = Object.fromEntries(items.map(s => [s.file, s]));
  GROUPS.forEach(([grp, files]) => {
    const t = document.createElement('div');
    t.className = 'sp-group-lbl'; t.textContent = grp;
    cont.appendChild(t);
    files.forEach(file => {
      const sp = byFile[file]; if (!sp) return;
      const row = document.createElement('div');
      row.className = 'sp-row';
      row.innerHTML = `
        <input type="checkbox" class="sp-check" data-name="${sp.name}" checked>
        <span class="sp-dot" style="background:${sp.color}"></span>
        <span class="sp-name">${sp.name}</span>
        <span class="form-hint">init:</span>
        <input type="number" class="sp-count" data-name="${sp.name}"
               value="${sp.count_default}" min="0" max="500">`;
      cont.appendChild(row);
    });
  });
}

async function loadRuns() {
  const runs = await fetch('/api/runs').then(r => r.json()).catch(() => []);
  const list = $('runs-list');
  list.innerHTML = '';
  if (!runs.length) { list.innerHTML = '<p class="no-runs">Aucun enregistrement</p>'; return; }
  runs.slice(0, 8).forEach(run => {
    const el = document.createElement('div');
    el.className = 'run-item';
    const idChip = run.run_id ? `<span class="run-id-chip">#${run.run_id}</span>` : '';
    el.innerHTML = `
      <div class="run-info">
        <span class="run-name">${run.name}</span>${idChip}
      </div>
      <div class="run-meta">
        <span class="run-size">${run.size_mb} MB</span>
        <span class="run-open">▶ Replay</span>
      </div>`;
    el.addEventListener('click', () => openAnalyse(run.path));
    list.appendChild(el);
  });
}

function wireSetup() {
  $('seed-input').addEventListener('input',    () => schedulePreview());
  $('preset-select').addEventListener('change', () => schedulePreview(0));
  qq('input[name="gs"]').forEach(r => r.addEventListener('change', () => schedulePreview(0)));
  $('regen-btn').addEventListener('click',  () => schedulePreview(0));
  $('launch-btn').addEventListener('click', onLaunch);
}

function currentGridSize() {
  return parseInt(q('input[name="gs"]:checked')?.value || '500');
}

function schedulePreview(delay = 380) {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(generatePreview, delay);
}

async function generatePreview() {
  const seed = parseInt($('seed-input').value) || 42;
  const preset = $('preset-select').value;
  const gridSize = currentGridSize();
  $('terrain-spinner').classList.remove('hidden');
  try {
    const resp = await fetch('/api/terrain/preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seed, preset, size: PREVIEW_SZ, grid_size: gridSize }),
    });
    const bmp = await createImageBitmap(await resp.blob());
    const cv  = $('terrain-preview');
    cv.getContext('2d').drawImage(bmp, 0, 0, cv.width, cv.height);
    $('terrain-info').textContent = `seed ${seed}  ·  ${preset}  ·  ${gridSize}×${gridSize}`;
  } catch { $('terrain-info').textContent = 'Erreur preview'; }
  finally  { $('terrain-spinner').classList.add('hidden'); }
}

function onLaunch() {
  const seed     = parseInt($('seed-input').value) || 42;
  const ticks    = parseInt($('ticks-input').value);
  const outPath  = $('out-input').value.trim() || 'runs/sim.db';
  const preset   = $('preset-select').value;
  const gridSize = currentGridSize();
  const species  = [];
  qq('.sp-row').forEach(row => {
    const cb  = row.querySelector('.sp-check');
    const cnt = row.querySelector('.sp-count');
    if (!cb) return;
    const sp = speciesMap.get(cb.dataset.name);
    if (!sp) return;
    species.push({ enabled: cb.checked, count: parseInt(cnt.value) || 0, params: sp.params });
  });
  runConfig = { seed, ticks, grid_size: gridSize, preset, out_path: outPath, species };
  $('run-config-lbl').textContent =
    `${gridSize}×${gridSize} · seed=${seed} · ${ticks.toLocaleString()} ticks · ${outPath}`;
  $('prog-total').textContent = ticks.toLocaleString();
  resetProgressUI();
  showPage('running');
  fetch('/api/sim/start', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(runConfig),
  });
}

function resetProgressUI() {
  $('progress-bar').style.width = '0%';
  $('prog-tick').textContent    = '0';
  $('prog-pct').textContent     = '0%';
  $('prog-tps').textContent     = '—';
  $('prog-eta').textContent     = '—';
  $('running-grid').innerHTML   = '';
}

// ══════════════════════════════════════════════════════════════════════════════
// RUNNING
// ══════════════════════════════════════════════════════════════════════════════
function wireRunning() {
  $('cancel-btn').addEventListener('click', () =>
    fetch('/api/sim/cancel', { method: 'POST' })
  );
}

function onProgress(msg) {
  if (currentPage !== 'running') return;
  const pct = Math.min(100, Math.round(msg.done / msg.ticks * 100));
  $('progress-bar').style.width = pct + '%';
  $('prog-tick').textContent    = msg.done.toLocaleString();
  $('prog-pct').textContent     = pct + '%';
  $('prog-tps').textContent     = msg.tps.toLocaleString() + ' ticks/s';
  $('prog-eta').textContent     = msg.eta_s != null ? 'ETA ' + fmtEta(msg.eta_s) : '—';
  updateRunGrid(msg.counts);
}

function fmtEta(s) {
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${(s % 60).toString().padStart(2, '0')}s`;
}

function updateRunGrid(counts) {
  const grid = $('running-grid');
  Object.entries(counts).forEach(([name, n]) => {
    const id  = 'rsg-' + CSS.escape(name);
    const sp  = speciesMap.get(name);
    const col = sp ? sp.color : '#888';
    let card  = document.getElementById(id);
    if (!card) {
      card = document.createElement('div');
      card.id = id; card.className = 'run-sp-card';
      card.style.borderLeftColor = col;
      card.innerHTML = `
        <span class="run-sp-dot" style="background:${col}"></span>
        <span class="run-sp-name">${name}</span>
        <span class="run-sp-count">0</span>`;
      grid.appendChild(card);
    }
    card.querySelector('.run-sp-count').textContent = n.toLocaleString();
    card.style.opacity = n > 0 ? '1' : '0.3';
  });
}

function onSimDone(msg) {
  $('progress-bar').style.width = '100%';
  $('prog-pct').textContent     = '100%';
  setTimeout(() => openAnalyse(msg.db_path), 700);
}

function onSimError(msg) {
  toast('Erreur : ' + msg.message, true);
  showPage('setup');
}

// ══════════════════════════════════════════════════════════════════════════════
// ANALYSE — ouverture
// ══════════════════════════════════════════════════════════════════════════════
function wireAnalyse() {
  $('back-btn').addEventListener('click', () => {
    stopPlay();
    showPage('setup');
    loadRuns();
  });
  $('open-btn').addEventListener('click', () => {
    const db = prompt('Chemin du fichier .db :', 'runs/sim.db');
    if (db) openAnalyse(db.trim());
  });
  qq('.tab-btn').forEach(btn =>
    btn.addEventListener('click', () => showTab(btn.dataset.tab))
  );
  wireReplayTab();
  wireGraphsTab();
  wireGenealogyTab();
  wireDaysTab();
}

async function openAnalyse(dbPath) {
  stopPlay();
  showPage('analyse');
  showTab('replay');

  // Reset
  analyseDb      = dbPath;
  analyseMeta    = null;
  timeseriesData = null;
  statsData      = null;
  dayCache.clear();
  kfTicks        = [];
  kfIdx          = 0;
  frameImgs      = [];
  jsonCache.clear();
  popMaxes       = {};
  graphHist      = {};
  graphHidden.clear();
  _graphChipsBuilt = false;
  selectedId     = null;
  lastJsonSnap   = null;
  geneData       = null;

  const shortName = dbPath.split('/').pop().split('\\').pop();
  setText('analyse-title', 'EcoSim — ' + shortName);
  setText('replay-meta', '—');
  const ridBadge = $('replay-run-id');
  if (ridBadge) ridBadge.classList.add('hidden');

  ['si-frame','si-tick','si-day','si-speed',
   'si-runid','si-seed','si-preset','si-grid','si-maxTicks','si-kf','si-ver']
    .forEach(id => setText(id, '—'));
  setStyle('sim-track-fill', 'width', '0%');
  const popEl = $('pop-panel'); if (popEl) popEl.innerHTML = '';
  const entEl = $('entity-card');
  if (entEl) entEl.innerHTML = '<p class="entity-ph">— cliquez une entité</p>';
  const gf = $('graph-filter'); if (gf) gf.innerHTML = '';
  clearGraphCanvas();
  setCanvasOverlay('Chargement…');

  playFps  = SPEED_LEVELS[speedIdx];
  syncSpeedDisplay();

  try {
    analyseMeta = await fetch(
      `/api/replay/meta?db=${encodeURIComponent(dbPath)}`
    ).then(r => { if (!r.ok) throw new Error('meta 404'); return r.json(); });

    kfTicks = analyseMeta.keyframe_ticks;
    $('replay-meta').textContent =
      `seed=${analyseMeta.seed} · ${analyseMeta.preset} · ` +
      `${analyseMeta.world_w}×${analyseMeta.world_h} · ` +
      `${analyseMeta.n_keyframes} frames · v${analyseMeta.version}`;

    if (analyseMeta.run_id && ridBadge) {
      ridBadge.textContent = '#' + analyseMeta.run_id;
      ridBadge.classList.remove('hidden');
    }
    setText('si-runid',    analyseMeta.run_id || '—');
    setText('si-seed',     analyseMeta.seed);
    setText('si-preset',   analyseMeta.preset);
    setText('si-grid',     `${analyseMeta.world_w}×${analyseMeta.world_h}`);
    setText('si-maxTicks', (analyseMeta.max_ticks ?? analyseMeta.total_ticks).toLocaleString() + ' ticks');
    setText('si-kf',       analyseMeta.n_keyframes);
    setText('si-ver',      `v${analyseMeta.version}`);

    const slider = $('tl-slider');
    slider.min = 0; slider.max = Math.max(0, kfTicks.length - 1); slider.value = 0;
    updateTickLabel(0);

    const ver = Date.now();
    await loadFirstFrame(dbPath, kfTicks, ver);
    setCanvasOverlay(null);
    renderIdx(0);
    loadRemainingFrames(dbPath, kfTicks, ver);

    // Pré-charge timeseries en arrière-plan
    loadTimeseries().then(() => {
      buildGcSpeciesList();
      loadStats();
    });

  } catch (err) {
    setCanvasOverlay(null);
    toast('Erreur : ' + err, true);
    console.error(err);
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB REPLAY — viewer
// ══════════════════════════════════════════════════════════════════════════════
function wireReplayTab() {
  $('tl-play').addEventListener ('click', togglePlay);
  $('tl-first').addEventListener('click', () => gotoIdx(0));
  $('tl-last').addEventListener ('click', () => gotoIdx(kfTicks.length - 1));
  $('tl-prev').addEventListener ('click', () => gotoIdx(kfIdx - 1));
  $('tl-next').addEventListener ('click', () => gotoIdx(kfIdx + 1));
  $('tl-slider').addEventListener('input', e => gotoIdx(parseInt(e.target.value)));
  $('spd-up').addEventListener  ('click', speedUp);
  $('spd-down').addEventListener('click', speedDown);
  $('spd-input').addEventListener('change', () => {
    const v = parseFloat($('spd-input').value);
    if (v > 0 && isFinite(v)) { playFps = v; syncSpeedDisplay(); }
    else $('spd-input').value = playFps;
  });
  $('sim-canvas').addEventListener('click',     onCanvasClick);
  $('sim-canvas').addEventListener('mousemove', onCanvasHover);
  document.addEventListener('keydown', e => {
    if (currentPage !== 'analyse' || currentTab !== 'replay') return;
    if (e.target.tagName === 'INPUT') return;
    if (e.key === ' ')            { e.preventDefault(); togglePlay(); }
    else if (e.key === 'ArrowLeft')  { e.preventDefault(); e.ctrlKey ? gotoIdx(0) : e.shiftKey ? gotoIdx(kfIdx-10) : gotoIdx(kfIdx-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); e.ctrlKey ? gotoIdx(kfTicks.length-1) : e.shiftKey ? gotoIdx(kfIdx+10) : gotoIdx(kfIdx+1); }
    else if (e.key === '+' || e.key === '=') speedUp();
    else if (e.key === '-') speedDown();
  });
}

function setCanvasOverlay(text) {
  const el = $('canvas-loading');
  if (text) {
    el.querySelector('span:last-child').textContent = text;
    el.classList.remove('hidden');
  } else {
    el.classList.add('hidden');
  }
}

function _makeFrameLoader(db, tick, i, ver) {
  return new Promise(resolve => {
    const img = new Image();
    img.onload  = () => { frameImgs[i] = img; resolve(); };
    img.onerror = () => resolve();
    img.src = `/api/replay/frame_img?db=${encodeURIComponent(db)}&tick=${tick}&_v=${ver}&w=${CANVAS_W}&h=${CANVAS_H}`;
  });
}

async function loadFirstFrame(db, ticks, ver) {
  frameImgs = new Array(ticks.length).fill(null);
  setCanvasOverlay(`Chargement…`);
  if (ticks.length > 0) await _makeFrameLoader(db, ticks[0], 0, ver);
}

async function loadRemainingFrames(db, ticks, ver) {
  let loaded = 1;
  const BATCH = 8;
  for (let i = 1; i < ticks.length; i += BATCH) {
    await Promise.all(ticks.slice(i, i + BATCH).map((tick, j) => {
      const idx = i + j;
      return _makeFrameLoader(db, tick, idx, ver).then(() => {
        loaded++;
        if (loaded % 10 === 0 || loaded === ticks.length) {
          const bar = $('sim-track-fill');
          if (bar) bar.style.opacity = loaded < ticks.length ? '0.6' : '1';
        }
      });
    }));
  }
}

function gotoIdx(idx) {
  if (!analyseDb || !kfTicks.length) return;
  idx   = Math.max(0, Math.min(kfTicks.length - 1, idx));
  kfIdx = idx;
  $('tl-slider').value = idx;
  updateTickLabel(idx);
  renderIdx(idx);
  loadJsonLazy(kfTicks[idx]);
}

function updateTickLabel(idx) {
  const tick   = kfTicks[idx] ?? 0;
  const minT   = analyseMeta?.min_tick ?? 0;
  const maxT   = analyseMeta?.max_ticks ?? analyseMeta?.total_ticks ?? 0;
  const rel    = tick - minT;
  const pct    = maxT > 0 ? Math.min(100, Math.round(rel / maxT * 100)) : 0;
  const day    = Math.floor(rel / DAY_LENGTH) + 1;
  $('tl-label').textContent   = `${rel.toLocaleString()} / ${maxT.toLocaleString()}`;
  $('hud-tick').textContent   = `tick ${rel.toLocaleString()}`;
  setText('si-frame',  `${idx + 1} / ${kfTicks.length}`);
  setText('si-tick',   `${rel.toLocaleString()} / ${maxT.toLocaleString()}`);
  setText('si-day',    `Jour ${day.toLocaleString()}`);
  setText('si-speed',  `${playFps} fps`);
  $('sim-track-fill').style.width = pct + '%';
}

function renderIdx(idx) {
  const cv  = $('sim-canvas');
  const ctx = cv.getContext('2d');
  const img = frameImgs[idx];
  if (img?.complete && img.naturalWidth > 0) {
    ctx.drawImage(img, 0, 0, cv.width, cv.height);
  } else {
    ctx.fillStyle = '#050d18';
    ctx.fillRect(0, 0, cv.width, cv.height);
  }
  if (selectedId !== null && lastJsonSnap) drawSelectionRing(ctx, lastJsonSnap, cv.width, cv.height);
}

function drawSelectionRing(ctx, snap, cw, ch) {
  if (!analyseMeta) return;
  const entity = snap.individuals.find(e => e.id === selectedId);
  if (!entity) return;
  const px = entity.x / analyseMeta.world_w * cw;
  const py = entity.y / analyseMeta.world_h * ch;
  ctx.strokeStyle = 'rgba(255,255,200,.95)'; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.arc(px, py, 8, 0, Math.PI * 2); ctx.stroke();
  const sp = speciesMap.get(entity.sp);
  if (sp) {
    ctx.strokeStyle = sp.color; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(px, py, 11, 0, Math.PI * 2); ctx.stroke();
  }
}

function loadJsonLazy(tick) {
  if (jsonCache.has(tick)) {
    const snap = jsonCache.get(tick);
    lastJsonSnap = snap;
    updatePopPanel(snap.counts);
    updateReplayGraph(snap.counts);
    if (selectedId !== null) updateEntityCard(snap);
    return;
  }
  fetch(`/api/replay/frame_json?db=${encodeURIComponent(analyseDb)}&tick=${tick}`)
    .then(r => r.json())
    .then(snap => {
      jsonCache.set(tick, snap);
      if (jsonCache.size > 60) jsonCache.delete(jsonCache.keys().next().value);
      if (tick === kfTicks[kfIdx]) {
        lastJsonSnap = snap;
        updatePopPanel(snap.counts);
        updateReplayGraph(snap.counts);
        if (selectedId !== null) updateEntityCard(snap);
      }
    }).catch(() => {});
}

// ── Playback ──────────────────────────────────────────────────────────────────
function togglePlay() { playing ? stopPlay() : startPlay(); }

function startPlay() {
  if (!analyseDb || !kfTicks.length) return;
  playing = true; nextTarget = performance.now();
  $('tl-play').classList.add('playing'); $('tl-play').textContent = '⏸';
  rafId = requestAnimationFrame(playLoop);
}

function stopPlay() {
  playing = false;
  if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null; }
  const btn = $('tl-play');
  if (btn) { btn.classList.remove('playing'); btn.textContent = '▶'; }
}

function playLoop(now) {
  if (!playing) return;
  if (now >= nextTarget) {
    const next = kfIdx + 1;
    if (next >= kfTicks.length) { stopPlay(); return; }
    const img = frameImgs[next];
    if (img?.complete && img.naturalWidth > 0) {
      kfIdx = next;
      $('tl-slider').value = next;
      updateTickLabel(next);
      renderIdx(next);
      loadJsonLazy(kfTicks[next]);
    }
    nextTarget += 1000 / Math.max(playFps, 0.05);
  }
  rafId = requestAnimationFrame(playLoop);
}

function syncSpeedDisplay() {
  $('spd-input').value      = playFps;
  setText('si-speed', `${playFps} fps`);
}
function speedUp()   { speedIdx = Math.min(SPEED_LEVELS.length-1, speedIdx+1); playFps = SPEED_LEVELS[speedIdx]; syncSpeedDisplay(); }
function speedDown() { speedIdx = Math.max(0, speedIdx-1); playFps = SPEED_LEVELS[speedIdx]; syncSpeedDisplay(); }

// ── Pop panel ─────────────────────────────────────────────────────────────────
function updatePopPanel(counts) {
  const panel  = $('pop-panel');
  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  sorted.forEach(([name, n]) => {
    popMaxes[name] = Math.max(popMaxes[name] || 1, n, 1);
    const sp    = speciesMap.get(name);
    const color = sp ? sp.color : '#888';
    const id    = 'pp-' + CSS.escape(name);
    let row = document.getElementById(id);
    if (!row) {
      row = document.createElement('div'); row.className = 'pop-row'; row.id = id;
      row.innerHTML = `
        <span class="pop-dot" style="background:${color}"></span>
        <span class="pop-name">${name}</span>
        <div class="pop-bar-wrap"><div class="pop-bar-fill" style="background:${color};width:0%"></div></div>
        <span class="pop-count">0</span>`;
      panel.appendChild(row);
    }
    const pct = Math.round(n / popMaxes[name] * 100);
    row.querySelector('.pop-bar-fill').style.width = pct + '%';
    const cnt = row.querySelector('.pop-count');
    cnt.textContent = n.toLocaleString();
    cnt.style.color = n > 0 ? 'var(--ok)' : 'var(--err)';
  });
}

// ── Replay graph (mini) ───────────────────────────────────────────────────────
function clearGraphCanvas() {
  const gc = $('graph-canvas');
  if (gc) gc.getContext('2d').clearRect(0, 0, gc.width, gc.height);
}

let _gcChipsDone = false;
function updateReplayGraph(counts) {
  Object.entries(counts).forEach(([name, n]) => {
    if (!graphHist[name]) graphHist[name] = [];
    graphHist[name].push(n);
    if (graphHist[name].length > 600) graphHist[name].splice(0, 150);
  });
  if (!_gcChipsDone) {
    buildGraphChips(Object.keys(counts));
    _gcChipsDone = true;
  }
  drawMiniGraph();
}

function buildGraphChips(names) {
  const cont = $('graph-filter'); if (!cont) return;
  cont.innerHTML = '';
  names.forEach(name => {
    const sp    = speciesMap.get(name);
    const color = sp ? sp.color : '#7a9abc';
    const chip  = document.createElement('button');
    chip.className = 'graph-chip'; chip.dataset.name = name; chip.textContent = name;
    chip.style.setProperty('--chip-color', color);
    chip.addEventListener('click', () => {
      if (graphHidden.has(name)) graphHidden.delete(name);
      else graphHidden.add(name);
      chip.classList.toggle('hidden-chip', graphHidden.has(name));
      drawMiniGraph();
    });
    cont.appendChild(chip);
  });
}

function drawMiniGraph() {
  const gc  = $('graph-canvas'); if (!gc) return;
  const ctx = gc.getContext('2d');
  const gw  = gc.width, gh = gc.height;
  ctx.clearRect(0, 0, gw, gh);
  const vis = Object.entries(graphHist).filter(([n]) => !graphHidden.has(n));
  if (!vis.length) return;
  const all = vis.flatMap(([,h]) => h);
  if (!all.length) return;
  const maxV = Math.max(1, ...all);
  const nPts = Math.max(...vis.map(([,h]) => h.length));
  if (nPts < 2) return;

  // grid
  ctx.strokeStyle = 'rgba(255,255,255,.04)'; ctx.lineWidth = 1;
  for (let i=1; i<4; i++) { const y = Math.round(gh - i*(gh/4)) + .5; ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(gw,y); ctx.stroke(); }
  ctx.fillStyle = 'rgba(122,154,188,.5)'; ctx.font = '9px Consolas,monospace';
  ctx.fillText(maxV.toLocaleString(), 3, 10);

  ctx.globalAlpha = 0.9;
  vis.forEach(([name, hist]) => {
    if (hist.length < 2) return;
    const sp = speciesMap.get(name);
    ctx.strokeStyle = sp ? sp.color : '#888'; ctx.lineWidth = 1.4;
    ctx.beginPath();
    hist.forEach((v, i) => {
      const x = 1 + (i / (nPts-1)) * (gw-2);
      const y = gh - 2 - (v / maxV) * (gh-12);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
  });
  ctx.globalAlpha = 1;
}

// ── Canvas click / hover ──────────────────────────────────────────────────────
function onCanvasClick(ev) {
  if (!lastJsonSnap || !analyseMeta) return;
  const cv = $('sim-canvas'); const rect = cv.getBoundingClientRect();
  const scX = cv.width / rect.width, scY = cv.height / rect.height;
  const cx  = (ev.clientX - rect.left) * scX, cy = (ev.clientY - rect.top) * scY;
  const wx  = cx / cv.width * analyseMeta.world_w, wy = cy / cv.height * analyseMeta.world_h;
  let bestId = null, bestD = 14;
  lastJsonSnap.individuals.forEach(e => {
    const d = Math.hypot(e.x - wx, e.y - wy);
    if (d < bestD) { bestD = d; bestId = e.id; }
  });
  selectedId = bestId;
  renderIdx(kfIdx);
  if (lastJsonSnap) updateEntityCard(lastJsonSnap);
}

let _hoverRafPending = false;
function onCanvasHover(ev) {
  if (!lastJsonSnap || !analyseMeta || _hoverRafPending) return;
  _hoverRafPending = true;
  const cv = $('sim-canvas'); const rect = cv.getBoundingClientRect();
  const scX = cv.width / rect.width, scY = cv.height / rect.height;
  const cx  = (ev.clientX - rect.left) * scX, cy = (ev.clientY - rect.top) * scY;
  const wx  = cx / cv.width * analyseMeta.world_w, wy = cy / cv.height * analyseMeta.world_h;
  requestAnimationFrame(() => {
    _hoverRafPending = false;
    let best = '', bestD = 10;
    lastJsonSnap.individuals.forEach(e => {
      const d = Math.hypot(e.x - wx, e.y - wy);
      if (d < bestD) { bestD = d; best = e.sp; }
    });
    $('hud-hover').textContent = best;
  });
}

function updateEntityCard(snap) {
  const card = $('entity-card');
  if (selectedId === null) { card.innerHTML = '<p class="entity-ph">— cliquez une entité</p>'; return; }
  const entity = snap.individuals.find(e => e.id === selectedId);
  if (!entity) { card.innerHTML = '<p class="entity-ph" style="color:var(--err)">✝ disparu</p>'; return; }
  const sp    = speciesMap.get(entity.sp);
  const color = sp ? sp.color : '#888';
  const maxE  = 200; const ratio = Math.max(0, Math.min(1, entity.energy / maxE));
  const barC  = ratio > .5 ? 'var(--ok)' : ratio > .2 ? 'var(--warn)' : 'var(--err)';
  card.innerHTML = `
    <div class="entity-name" style="color:${color}">
      <span class="sp-dot" style="background:${color}"></span>${entity.sp}
    </div>
    <div class="nrg-wrap"><div class="nrg-fill" style="width:${Math.round(ratio*100)}%;background:${barC}"></div></div>
    <div class="entity-info">
      id: ${entity.id}<br>
      x: ${entity.x?.toFixed(1)} &nbsp; y: ${entity.y?.toFixed(1)}<br>
      énergie: ${entity.energy?.toFixed(1)} &nbsp; âge: ${entity.age?.toLocaleString()}<br>
      état: ${entity.state || '—'}
    </div>
    <button class="btn btn-ghost btn-sm" style="margin-top:8px;width:100%"
            onclick="searchGenealogyById(${entity.id})">🌳 Voir l'arbre généalogique</button>`;
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB GRAPHES — custom chart builder
// ══════════════════════════════════════════════════════════════════════════════
function wireGraphsTab() {
  $('gc-add-btn').addEventListener('click', addCustomChart);
  $('gc-clear-btn').addEventListener('click', clearCustomCharts);
}

async function loadTimeseries() {
  if (!analyseDb) return;
  try {
    timeseriesData = await fetch(
      `/api/analyse/timeseries?db=${encodeURIComponent(analyseDb)}`
    ).then(r => r.json());
  } catch (e) { console.error('timeseries:', e); }
}

function buildGcSpeciesList() {
  const cont = $('gc-species-list'); if (!cont || !timeseriesData?.length) return;
  cont.innerHTML = '';
  const names = Object.keys(timeseriesData[timeseriesData.length - 1]?.counts || {});
  names.forEach(name => {
    const sp    = speciesMap.get(name);
    const color = sp ? sp.color : '#7a9abc';
    const row   = document.createElement('div');
    row.className = 'gc-sp-row';
    row.innerHTML = `
      <label>
        <input type="checkbox" class="gc-sp-cb" data-name="${name}" checked>
        <span class="sp-dot" style="background:${color}"></span>
        ${name}
      </label>`;
    cont.appendChild(row);
  });
}

function addCustomChart() {
  if (!timeseriesData?.length) {
    toast('Aucune donnée — lancez d\'abord une simulation', true); return;
  }
  const species    = [...qq('.gc-sp-cb:checked')].map(cb => cb.dataset.name);
  if (!species.length) { toast('Sélectionnez au moins une espèce', true); return; }
  const type       = q('input[name="gc-type"]:checked')?.value || 'line';
  const normalize  = $('gc-normalize').checked;
  const chartId    = gcNextId++;

  const main  = $('graphs-main');
  const empty = $('graphs-empty');
  if (empty) empty.remove();

  const wrap = document.createElement('div');
  wrap.className = 'custom-chart'; wrap.id = `cc-${chartId}`;
  wrap.style.minHeight = '260px';
  const title = species.slice(0, 4).join(', ') + (species.length > 4 ? '…' : '');
  wrap.innerHTML = `
    <div class="custom-chart-header">
      <span class="custom-chart-title">${type === 'line' ? '📈' : type === 'area' ? '📊' : '📉'} ${title} ${normalize ? '(normalisé)' : ''}</span>
      <button class="chart-close-btn" onclick="removeChart(${chartId})">✕</button>
    </div>
    <canvas id="cc-canvas-${chartId}" class="chart-canvas" width="800" height="220" style="width:100%;height:220px"></canvas>`;
  main.appendChild(wrap);

  const canvas = $(`cc-canvas-${chartId}`);
  const chart  = { id: chartId, canvasEl: canvas, species, type, normalize };
  customCharts.push(chart);
  renderCustomChart(chart);
}

function removeChart(id) {
  customCharts = customCharts.filter(c => c.id !== id);
  const el = $(`cc-${id}`); if (el) el.remove();
  if (!$('graphs-main').children.length) {
    const main = $('graphs-main');
    main.innerHTML = `<div class="graphs-empty" id="graphs-empty"><div class="graphs-empty-icon">📈</div><p>Sélectionnez des espèces et cliquez <strong>Ajouter ce graphe</strong></p></div>`;
  }
}

function clearCustomCharts() {
  customCharts = []; gcNextId = 1;
  const main = $('graphs-main');
  main.innerHTML = `<div class="graphs-empty" id="graphs-empty"><div class="graphs-empty-icon">📈</div><p>Sélectionnez des espèces et cliquez <strong>Ajouter ce graphe</strong></p></div>`;
}

function renderCustomChart(chart) {
  const data = timeseriesData; if (!data?.length) return;
  const cv   = chart.canvasEl; if (!cv) return;
  // Synchronise la résolution logique avec l'affichage CSS
  cv.width  = cv.offsetWidth  || 800;
  cv.height = cv.offsetHeight || 220;
  const ctx = cv.getContext('2d');
  const w = cv.width, h = cv.height;
  ctx.clearRect(0, 0, w, h);

  const PAD = { l: 50, r: 12, t: 18, b: 30 };
  const cw = w - PAD.l - PAD.r, ch = h - PAD.t - PAD.b;

  // Séries
  const series = chart.species.map(name => ({
    name,
    color: speciesMap.get(name)?.color || '#888',
    values: data.map(d => d.counts[name] || 0),
  }));

  // Max Y
  let maxY = 1;
  series.forEach(s => { const m = Math.max(...s.values); if (m > maxY) maxY = m; });
  if (chart.normalize) maxY = 1;

  const nPts = data.length;
  const xOf  = i => PAD.l + (i / Math.max(nPts - 1, 1)) * cw;
  const yOf  = v => PAD.t + ch - (chart.normalize ? v / Math.max(...series.find(s=>s.values.includes(v))?.values||[1], 1) : v / maxY) * ch;
  // simplified yOf
  const yOfV = v => PAD.t + ch - (v / maxY) * ch;

  // Grid
  ctx.strokeStyle = 'rgba(255,255,255,.05)'; ctx.lineWidth = 1;
  for (let i = 1; i <= 4; i++) {
    const y = PAD.t + (ch / 4) * i;
    ctx.beginPath(); ctx.moveTo(PAD.l, y); ctx.lineTo(PAD.l + cw, y); ctx.stroke();
  }
  // Axes
  ctx.strokeStyle = 'rgba(122,154,188,.3)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(PAD.l, PAD.t); ctx.lineTo(PAD.l, PAD.t + ch); ctx.lineTo(PAD.l + cw, PAD.t + ch); ctx.stroke();

  // Y labels
  ctx.fillStyle = 'rgba(122,154,188,.6)'; ctx.font = '10px Consolas,monospace'; ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const v = maxY * (1 - i/4);
    const y = PAD.t + (ch / 4) * i;
    ctx.fillText(chart.normalize ? Math.round(v*100) + '%' : Math.round(v).toLocaleString(), PAD.l - 4, y + 3);
  }

  // X labels (every N ticks)
  ctx.textAlign = 'center';
  const step = Math.max(1, Math.floor(nPts / 8));
  for (let i = 0; i < nPts; i += step) {
    const tick = data[i].tick;
    const day  = Math.floor(tick / DAY_LENGTH);
    ctx.fillText(`J${day}`, xOf(i), PAD.t + ch + 18);
  }

  // Series lines / areas
  series.forEach(s => {
    const vals = chart.normalize
      ? (v => { const mx = Math.max(...s.values, 1); return v / mx; })
      : (v => v / maxY);
    ctx.beginPath();
    s.values.forEach((v, i) => {
      const x = xOf(i), y = PAD.t + ch - vals(v) * ch;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    if (chart.type === 'area') {
      ctx.lineTo(xOf(nPts-1), PAD.t + ch);
      ctx.lineTo(xOf(0), PAD.t + ch);
      ctx.closePath();
      ctx.fillStyle = s.color + '28';
      ctx.fill();
    }
    ctx.strokeStyle = s.color; ctx.lineWidth = chart.type === 'bar' ? 0 : 1.8;
    if (chart.type !== 'area') { ctx.stroke(); }
    else {
      ctx.beginPath();
      s.values.forEach((v, i) => {
        const x = xOf(i), y = PAD.t + ch - vals(v) * ch;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.stroke();
    }
    // Bars
    if (chart.type === 'bar') {
      const bw = Math.max(1, cw / nPts * 0.6);
      ctx.fillStyle = s.color + 'aa';
      s.values.forEach((v, i) => {
        const x = xOf(i) - bw / 2;
        const y = PAD.t + ch - vals(v) * ch;
        ctx.fillRect(x, y, bw, PAD.t + ch - y);
      });
    }
  });

  // Legend
  ctx.textAlign = 'left'; let lx = PAD.l;
  series.forEach(s => {
    ctx.fillStyle = s.color + 'cc'; ctx.fillRect(lx, PAD.t - 14, 10, 10);
    ctx.fillStyle = 'rgba(220,232,248,.8)'; ctx.font = '10px Consolas,monospace';
    ctx.fillText(s.name, lx + 13, PAD.t - 5);
    lx += ctx.measureText(s.name).width + 30;
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB GÉNÉALOGIE
// ══════════════════════════════════════════════════════════════════════════════
function wireGenealogyTab() {
  $('gene-search-btn').addEventListener('click', () => {
    const id = parseInt($('gene-id-input').value);
    if (id) searchGenealogyById(id);
    else toast('Entrez un ID valide', true);
  });
  $('gene-id-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') $('gene-search-btn').click();
  });
}

async function searchGenealogyById(entityId) {
  if (!analyseDb) { toast('Aucune simulation chargée', true); return; }
  showTab('genealogy');
  $('gene-id-input').value = entityId;
  $('gene-subject-info').innerHTML = '<p class="entity-ph">Chargement…</p>';
  try {
    geneData = await fetch(
      `/api/analyse/genealogy?db=${encodeURIComponent(analyseDb)}&id=${entityId}`
    ).then(r => r.json());
    updateGenealogyPanel();
    renderGeneTree();
  } catch (e) { toast('Erreur généalogie : ' + e, true); }
}

function updateGenealogyPanel() {
  if (!geneData) return;
  const s = geneData.subject;
  const sp = speciesMap.get(s.species);
  const color = sp ? sp.color : '#7a9abc';
  $('gene-subject-info').innerHTML = `
    <span class="sp-dot" style="background:${color};display:inline-block;margin-right:6px;vertical-align:middle"></span>
    <strong style="color:${color}">${s.species}</strong><br>
    <span style="color:var(--t2);font-family:var(--mono);font-size:10px">ID: ${s.id}</span>`;
  const minT = analyseMeta?.min_tick || 0;
  setText('gs-birth', s.birth_tick >= 0 ? `Jour ${Math.floor((s.birth_tick - minT) / DAY_LENGTH) + 1}` : 'Fondateur');
  setText('gs-anc',  geneData.ancestors.length);
  const directChildren = geneData.descendants.filter(d => d.parent_id === s.id).length;
  setText('gs-children', directChildren);
  setText('gs-desc', geneData.descendants.length);
  // Hide empty placeholder
  const ge = $('gene-empty'); if (ge) ge.style.display = 'none';
}

function renderGeneTree() {
  if (!geneData) return;
  const wrap  = document.querySelector('.gene-canvas-wrap');
  const gc    = $('gene-canvas');
  if (!wrap || !gc) return;

  const W = wrap.offsetWidth  || 800;
  const H = wrap.offsetHeight || 500;
  gc.width  = W;
  gc.height = H;
  const ctx = gc.getContext('2d');
  ctx.clearRect(0, 0, W, H);

  const BOX_W = 140, BOX_H = 50, VERT = 80;
  const minT  = analyseMeta?.min_tick || 0;

  function dayStr(tick) {
    return tick < 0 ? 'Fondateur' : `Jour ${Math.floor((tick - minT) / DAY_LENGTH) + 1}`;
  }

  function drawBox(entity, cx, cy, highlight = false) {
    const sp    = speciesMap.get(entity.species);
    const color = sp ? sp.color : '#7a9abc';
    const bx = cx - BOX_W / 2, by = cy - BOX_H / 2;
    // Shadow
    ctx.shadowColor = highlight ? color : 'rgba(0,0,0,.6)';
    ctx.shadowBlur  = highlight ? 18 : 6;
    // Box
    ctx.fillStyle   = highlight ? color + '22' : 'rgba(15,27,48,.95)';
    ctx.strokeStyle = color + (highlight ? 'ff' : '88');
    ctx.lineWidth   = highlight ? 2 : 1;
    roundRect(ctx, bx, by, BOX_W, BOX_H, 6);
    ctx.fill(); ctx.stroke();
    ctx.shadowBlur = 0;
    // Text
    ctx.textAlign  = 'center';
    ctx.fillStyle  = highlight ? color : 'rgba(220,232,248,.9)';
    ctx.font       = highlight ? 'bold 12px Consolas,monospace' : '11px Consolas,monospace';
    ctx.fillText(entity.species, cx, cy - 8);
    ctx.fillStyle  = 'rgba(122,154,188,.75)';
    ctx.font       = '9px Consolas,monospace';
    ctx.fillText(dayStr(entity.birth_tick), cx, cy + 6);
    ctx.fillText(`👶 ${entity.children_count}`, cx, cy + 18);
    ctx.shadowBlur = 0;
  }

  function drawLine(x1, y1, x2, y2, color = 'rgba(74,143,255,.4)') {
    ctx.strokeStyle = color; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(x1, y1);
    ctx.bezierCurveTo(x1, (y1 + y2) / 2, x2, (y1 + y2) / 2, x2, y2);
    ctx.stroke();
  }

  const subject = geneData.subject;
  const ancs    = geneData.ancestors;       // oldest → newest
  const descs   = geneData.descendants;
  const directC = descs.filter(d => d.parent_id === subject.id);
  const grandC  = descs.filter(d => d.parent_id !== subject.id);

  const cx = W / 2;

  // Row positions
  const rows = {
    grandparent: H * 0.08 + BOX_H / 2,
    parent:      H * 0.22 + BOX_H / 2,
    subject:     H * 0.44,
    children:    H * 0.63 + BOX_H / 2,
    grandch:     H * 0.82 + BOX_H / 2,
  };

  // Ancestors
  const ancNodes = [];
  if (ancs.length === 1) {
    ancNodes.push({ ...ancs[0], cx, cy: rows.parent });
  } else if (ancs.length >= 2) {
    ancNodes.push({ ...ancs[0], cx, cy: rows.grandparent });
    ancNodes.push({ ...ancs[1], cx, cy: rows.parent });
  }

  // Subject
  const subjNode = { ...subject, cx, cy: rows.subject };

  // Children (spread horizontally)
  const SPREAD = Math.min(200, (W - 80) / Math.max(directC.length, 1));
  const childNodes = directC.slice(0, 7).map((c, i) => ({
    ...c,
    cx: cx + (i - (Math.min(directC.length, 7) - 1) / 2) * SPREAD,
    cy: rows.children,
  }));

  // Grandchildren (one per child)
  const gcNodes = [];
  childNodes.forEach(child => {
    const gc2 = grandC.filter(g => g.parent_id === child.id).slice(0, 2);
    const gSpread = 70;
    gc2.forEach((g, i) => {
      gcNodes.push({
        ...g,
        cx: child.cx + (i - (gc2.length - 1) / 2) * gSpread,
        cy: rows.grandch,
      });
    });
  });

  // Draw lines
  ancNodes.forEach((anc, idx) => {
    if (idx === 0 && ancNodes.length > 1) drawLine(anc.cx, anc.cy + BOX_H/2, ancNodes[1].cx, ancNodes[1].cy - BOX_H/2);
    if (idx === ancNodes.length - 1)      drawLine(anc.cx, anc.cy + BOX_H/2, subjNode.cx,    subjNode.cy - BOX_H/2 - 4);
  });
  childNodes.forEach(child => drawLine(subjNode.cx, subjNode.cy + BOX_H/2 + 4, child.cx, child.cy - BOX_H/2));
  gcNodes.forEach(gc2 => {
    const parent = childNodes.find(c => c.id === gc2.parent_id);
    if (parent) drawLine(parent.cx, parent.cy + BOX_H/2, gc2.cx, gc2.cy - BOX_H/2);
  });

  // Draw boxes
  gcNodes.forEach(n   => drawBox(n, n.cx, n.cy));
  childNodes.forEach(n => drawBox(n, n.cx, n.cy));
  drawBox(subjNode, subjNode.cx, subjNode.cy, true);
  ancNodes.forEach(n  => drawBox(n, n.cx, n.cy));

  // Labels count
  if (directC.length > 7 || grandC.length) {
    ctx.textAlign  = 'center';
    ctx.fillStyle  = 'rgba(122,154,188,.6)';
    ctx.font       = '10px Consolas,monospace';
    if (directC.length > 7) ctx.fillText(`+ ${directC.length - 7} enfants non affichés`, cx, rows.children + BOX_H/2 + 15);
  }
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y); ctx.arcTo(x + w, y, x + w, y + r, r);
  ctx.lineTo(x + w, y + h - r); ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
  ctx.lineTo(x + r, y + h); ctx.arcTo(x, y + h, x, y + h - r, r);
  ctx.lineTo(x, y + r); ctx.arcTo(x, y, x + r, y, r);
  ctx.closePath();
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB JOURS
// ══════════════════════════════════════════════════════════════════════════════
function wireDaysTab() {
  $('day-go-btn').addEventListener('click',  goDayInput);
  $('day-input').addEventListener('keydown', e => { if (e.key === 'Enter') goDayInput(); });
  $('day-prev-btn').addEventListener('click', () => {
    $('day-input').value = Math.max(1, parseInt($('day-input').value) - 1);
    goDayInput();
  });
  $('day-next-btn').addEventListener('click', () => {
    $('day-input').value = parseInt($('day-input').value) + 1;
    goDayInput();
  });
}

function goDayInput() {
  const day = parseInt($('day-input').value);
  if (!analyseDb || !day || day < 1) return;
  loadDayInfo(day);
}

async function loadDayInfo(day) {
  if (dayCache.has(day)) {
    renderDayPanel(dayCache.get(day));
    return;
  }
  try {
    const data = await fetch(
      `/api/analyse/day_info?db=${encodeURIComponent(analyseDb)}&day=${day}`
    ).then(r => r.json());
    dayCache.set(day, data);
    renderDayPanel(data);
  } catch (e) { toast('Erreur : ' + e, true); }
}

async function loadStats() {
  if (!analyseDb || statsData) return;
  try {
    statsData = await fetch(
      `/api/analyse/stats?db=${encodeURIComponent(analyseDb)}`
    ).then(r => r.json());
    renderBirthsPanel();
  } catch {}
}

function renderDayPanel(data) {
  const minT  = analyseMeta?.min_tick || 0;
  const maxT  = analyseMeta?.max_ticks || 0;
  const maxDay = Math.floor(maxT / DAY_LENGTH) + 1;
  setText('day-tick-lbl', `→ tick ${(data.tick - minT).toLocaleString()}`);
  setText('day-range-lbl', `(simulation : jours 1 – ${maxDay})`);
  $('day-input').value = data.day;

  const panel = $('day-pop-panel');
  panel.innerHTML = '';
  const sorted = Object.entries(data.counts).sort((a, b) => b[1] - a[1]);
  sorted.forEach(([name, n]) => {
    const sp    = speciesMap.get(name);
    const color = sp ? sp.color : '#888';
    const row   = document.createElement('div');
    row.className = 'day-sp-row';
    row.innerHTML = `
      <span class="day-sp-dot" style="background:${color}"></span>
      <span class="day-sp-name">${name}</span>
      <span class="day-sp-count" style="color:${n > 0 ? 'var(--ok)' : 'var(--err)'}">
        ${n.toLocaleString()}
      </span>`;
    panel.appendChild(row);
  });
  renderDayChart(data.tick);
}

function renderBirthsPanel() {
  if (!statsData) return;
  const panel = $('day-births-panel'); if (!panel) return;
  panel.innerHTML = '';
  const sorted = Object.entries(statsData.births_by_species || {}).sort((a, b) => b[1] - a[1]);
  if (!sorted.length) { panel.innerHTML = '<p style="color:var(--t3);font-size:11px">Aucune naissance enregistrée</p>'; return; }
  sorted.forEach(([name, n]) => {
    const sp    = speciesMap.get(name);
    const color = sp ? sp.color : '#888';
    const row   = document.createElement('div');
    row.className = 'day-birth-row';
    row.innerHTML = `
      <span class="sp-dot" style="background:${color}"></span>
      <span class="day-birth-name">${name}</span>
      <span class="day-birth-cnt">+${n.toLocaleString()}</span>`;
    panel.appendChild(row);
  });
}

function renderDayChart(highlightTick = null) {
  const cv = $('day-chart'); if (!cv || !timeseriesData?.length) return;
  cv.width  = cv.offsetWidth  || 600;
  cv.height = cv.offsetHeight || 200;
  const ctx = cv.getContext('2d');
  const w = cv.width, h = cv.height;
  ctx.clearRect(0, 0, w, h);

  const PAD = { l: 46, r: 10, t: 16, b: 26 };
  const cw  = w - PAD.l - PAD.r, ch = h - PAD.t - PAD.b;
  const data = timeseriesData;
  const nPts = data.length;

  // Max
  let maxY = 1;
  data.forEach(d => Object.values(d.counts).forEach(v => { if (v > maxY) maxY = v; }));

  const xOf = i => PAD.l + (i / Math.max(nPts - 1, 1)) * cw;
  const yOfV = v => PAD.t + ch - (v / maxY) * ch;

  // Grid
  ctx.strokeStyle = 'rgba(255,255,255,.04)'; ctx.lineWidth = 1;
  for (let i = 1; i <= 3; i++) { const y = PAD.t + (ch / 3) * i; ctx.beginPath(); ctx.moveTo(PAD.l, y); ctx.lineTo(PAD.l + cw, y); ctx.stroke(); }

  // Lines
  const names = Object.keys(data[data.length - 1]?.counts || {});
  ctx.globalAlpha = 0.85;
  names.forEach(name => {
    const sp = speciesMap.get(name);
    ctx.strokeStyle = sp ? sp.color : '#888'; ctx.lineWidth = 1.2;
    ctx.beginPath();
    data.forEach((d, i) => {
      const v = d.counts[name] || 0;
      i === 0 ? ctx.moveTo(xOf(i), yOfV(v)) : ctx.lineTo(xOf(i), yOfV(v));
    });
    ctx.stroke();
  });
  ctx.globalAlpha = 1;

  // Highlight line for current tick
  if (highlightTick != null) {
    const best = data.reduce((best, d, i) =>
      Math.abs(d.tick - highlightTick) < Math.abs(data[best.idx].tick - highlightTick)
        ? {idx: i} : best, {idx: 0});
    const hx = xOf(best.idx);
    ctx.strokeStyle = 'rgba(255,255,200,.6)'; ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    ctx.beginPath(); ctx.moveTo(hx, PAD.t); ctx.lineTo(hx, PAD.t + ch); ctx.stroke();
    ctx.setLineDash([]);
  }

  // X axis labels
  ctx.fillStyle = 'rgba(122,154,188,.5)'; ctx.font = '9px Consolas,monospace'; ctx.textAlign = 'center';
  const step = Math.max(1, Math.floor(nPts / 6));
  for (let i = 0; i < nPts; i += step) {
    const tick = data[i].tick;
    const day  = Math.floor(tick / DAY_LENGTH);
    ctx.fillText(`J${day}`, xOf(i), PAD.t + ch + 18);
  }

  // Y labels
  ctx.textAlign = 'right';
  for (let i = 0; i <= 3; i++) {
    const v = maxY * (1 - i/3);
    ctx.fillText(Math.round(v).toLocaleString(), PAD.l - 4, PAD.t + (ch/3)*i + 4);
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// BOOT
// ══════════════════════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', init);
