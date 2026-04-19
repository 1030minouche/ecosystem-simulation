'use strict';
// EcoSim Web UI — single-file application

// ── Constants ─────────────────────────────────────────────────────────────────
const CANVAS_W    = 700;
const CANVAS_H    = 560;
const PREVIEW_SZ  = 260;

const GROUPS = [
  ['PLANTES',    ['herbe', 'fougere', 'champignon', 'baies']],
  ['HERBIVORES', ['lapin', 'campagnol', 'cerf', 'sanglier']],
  ['PRÉDATEURS', ['renard', 'loup', 'hibou', 'aigle']],
];

// ── Global state ──────────────────────────────────────────────────────────────
let ws            = null;
let currentPage   = 'setup';
let speciesMap    = new Map();    // name → {color, count_default, params, file}
let runConfig     = null;

// Replay
let replayDb      = null;
let replayMeta    = null;
let terrainBitmap = null;
let kfTicks       = [];          // keyframe tick list
let kfIdx         = 0;           // current keyframe index
let curTick       = 0;
let playing       = false;
let rafId         = null;
let nextTarget    = 0;           // ms, for play drift compensation
let speedLevels   = [0.25, 0.5, 1, 2, 4, 8, 16, 32];
let speedIdx      = 2;           // default ×1
let frameCache    = new Map();
let graphHist     = {};
let popMaxes      = {};
let selectedId    = null;
let lastSnap      = null;

// Setup
let previewTimer  = null;
let previewBitmap = null;

// ── Utility ───────────────────────────────────────────────────────────────────
const $  = (id) => document.getElementById(id);
const q  = (sel) => document.querySelector(sel);
const qa = (sel) => [...document.querySelectorAll(sel)];

function showPage(name) {
  qa('.page').forEach(p => p.classList.remove('active'));
  $(`page-${name}`).classList.add('active');
  currentPage = name;
}

function showToast(msg, isErr = false) {
  const el = $('toast');
  el.textContent = msg;
  el.className = 'toast' + (isErr ? ' error' : '');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add('hidden'), 4000);
}

function fmtEta(s) {
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${(s % 60).toString().padStart(2, '0')}s`;
}

function cssEscape(name) { return name.replace(/[^a-zA-Z0-9_-]/g, '_'); }

// ── WebSocket ─────────────────────────────────────────────────────────────────
let _keepAliveTimer = null;

function connectWS() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen  = () => {
    // keep-alive unique — annuler l'ancien avant d'en créer un nouveau
    if (_keepAliveTimer) clearInterval(_keepAliveTimer);
    _keepAliveTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ type: 'ping' }));
    }, 20000);
  };
  ws.onclose = () => setTimeout(connectWS, 2000);
  ws.onerror = () => {};
  ws.onmessage = e => {
    try { dispatch(JSON.parse(e.data)); } catch (_) {}
  };
}

function dispatch(msg) {
  switch (msg.type) {
    case 'progress': onProgress(msg);  break;
    case 'done':     onSimDone(msg);   break;
    case 'error':    onSimError(msg);  break;
    case 'cancelled': showPage('setup'); loadRuns(); break;
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  connectWS();
  await loadSpecies();
  await loadRuns();
  wireSetup();
  wireRunning();
  wireReplay();
  schedulePreview(50);
}

// ── SETUP page ────────────────────────────────────────────────────────────────
async function loadSpecies() {
  const items = await fetch('/api/species').then(r => r.json()).catch(() => []);
  speciesMap.clear();
  items.forEach(s => speciesMap.set(s.name, s));
  renderSpeciesList(items);
}

function renderSpeciesList(items) {
  const cont = $('species-list');
  cont.innerHTML = '';
  const byFile = Object.fromEntries(items.map(s => [s.file, s]));

  GROUPS.forEach(([grpName, files]) => {
    const t = document.createElement('div');
    t.className = 'sp-group-title';
    t.textContent = grpName;
    cont.appendChild(t);

    files.forEach(file => {
      const sp = byFile[file];
      if (!sp) return;
      const row = document.createElement('div');
      row.className = 'sp-row';
      row.innerHTML = `
        <input type="checkbox" class="sp-check" data-name="${sp.name}" checked>
        <span class="sp-dot" style="background:${sp.color}"></span>
        <span class="sp-name">${sp.name}</span>
        <span style="font-size:10px;color:var(--sub)">init:</span>
        <input type="number" class="sp-count" data-name="${sp.name}"
               value="${sp.count_default}" min="0" max="500">
      `;
      cont.appendChild(row);
    });
  });
}

async function loadRuns() {
  const runs = await fetch('/api/runs').then(r => r.json()).catch(() => []);
  const list = $('runs-list');
  list.innerHTML = '';
  if (!runs.length) {
    list.innerHTML = '<p style="font-size:11px;color:var(--border);padding:4px 0">Aucun enregistrement</p>';
    return;
  }
  runs.slice(0, 8).forEach(run => {
    const el = document.createElement('div');
    el.className = 'run-item';
    el.innerHTML = `
      <span class="run-name">${run.name}</span>
      <span class="run-size">${run.size_mb} MB</span>
      <span class="run-open">▶ Replay</span>
    `;
    el.addEventListener('click', () => openReplay(run.path));
    list.appendChild(el);
  });
}

function wireSetup() {
  $('seed-input').addEventListener('input',  () => schedulePreview());
  $('preset-select').addEventListener('change', () => schedulePreview(0));
  qa('input[name="gs"]').forEach(r => r.addEventListener('change', () => {}));
  $('regen-btn').addEventListener('click', () => schedulePreview(0));
  $('launch-btn').addEventListener('click', onLaunch);
}

function schedulePreview(delay = 400) {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(generatePreview, delay);
}

async function generatePreview() {
  const seed   = parseInt($('seed-input').value)   || 42;
  const preset = $('preset-select').value;

  $('terrain-spinner').classList.remove('hidden');
  try {
    const resp   = await fetch('/api/terrain/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seed, preset, size: PREVIEW_SZ }),
    });
    const blob   = await resp.blob();
    previewBitmap = await createImageBitmap(blob);
    drawPreview();
    $('terrain-info').textContent = `seed ${seed}  ·  preset: ${preset}`;
  } catch (e) {
    $('terrain-info').textContent = 'Erreur preview';
  } finally {
    $('terrain-spinner').classList.add('hidden');
  }
}

function drawPreview() {
  const cv  = $('terrain-preview');
  const ctx = cv.getContext('2d');
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (previewBitmap) ctx.drawImage(previewBitmap, 0, 0, cv.width, cv.height);
}

function onLaunch() {
  const seed     = parseInt($('seed-input').value)  || 42;
  const ticks    = parseInt($('ticks-input').value) || 10000;
  const outPath  = $('out-input').value.trim()      || 'runs/sim.db';
  const preset   = $('preset-select').value;
  const gridSize = parseInt(q('input[name="gs"]:checked').value);

  const species = [];
  qa('.sp-row').forEach(row => {
    const cb  = row.querySelector('.sp-check');
    const cnt = row.querySelector('.sp-count');
    if (!cb) return;
    const sp = speciesMap.get(cb.dataset.name);
    if (!sp) return;
    species.push({ enabled: cb.checked, count: parseInt(cnt.value) || 0, params: sp.params });
  });

  runConfig = { seed, ticks, grid_size: gridSize, preset, out_path: outPath, species };

  // Prepare RUNNING page
  $('run-config-lbl').textContent =
    `${gridSize}×${gridSize}  ·  seed=${seed}  ·  ${ticks.toLocaleString()} ticks  ·  ${outPath}`;
  $('prog-total').textContent = ticks.toLocaleString();
  resetProgressUI();

  showPage('running');
  fetch('/api/sim/start', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(runConfig),
  });
}

function resetProgressUI() {
  $('progress-bar').style.width  = '0%';
  $('prog-tick').textContent     = '0';
  $('prog-pct').textContent      = '0%';
  $('prog-tps').textContent      = '— ticks/s';
  $('prog-eta').textContent      = '—';
  $('running-grid').innerHTML    = '';
}

// ── RUNNING page ──────────────────────────────────────────────────────────────
function wireRunning() {
  $('cancel-btn').addEventListener('click', () => {
    fetch('/api/sim/cancel', { method: 'POST' });
  });
}

function onProgress(msg) {
  if (currentPage !== 'running') return;
  const pct = Math.min(100, Math.round((msg.done / msg.ticks) * 100));
  $('progress-bar').style.width = pct + '%';
  $('prog-tick').textContent    = msg.tick.toLocaleString();
  $('prog-pct').textContent     = pct + '%';
  $('prog-tps').textContent     = msg.tps.toLocaleString() + ' ticks/s';
  $('prog-eta').textContent     = msg.eta_s !== null ? 'ETA ' + fmtEta(msg.eta_s) : '—';
  updateRunGrid(msg.counts);
}

function updateRunGrid(counts) {
  const grid = $('running-grid');
  Object.entries(counts).forEach(([name, n]) => {
    const id  = 'rsg-' + cssEscape(name);
    const sp  = speciesMap.get(name);
    const col = sp ? sp.color : '#888';
    let card  = document.getElementById(id);
    if (!card) {
      card = document.createElement('div');
      card.className = 'run-sp-card';
      card.id        = id;
      card.style.borderLeftColor = col;
      card.innerHTML = `
        <span class="run-sp-dot" style="background:${col}"></span>
        <span class="run-sp-name">${name}</span>
        <span class="run-sp-count">0</span>
      `;
      grid.appendChild(card);
    }
    card.querySelector('.run-sp-count').textContent = n.toLocaleString();
    card.style.opacity = n > 0 ? '1' : '0.35';
  });
}

function onSimDone(msg) {
  $('progress-bar').style.width = '100%';
  $('prog-pct').textContent     = '100%';
  setTimeout(() => openReplay(msg.db_path), 700);
}

function onSimError(msg) {
  showToast('Erreur simulation : ' + msg.message, true);
  showPage('setup');
}

// ── REPLAY page ───────────────────────────────────────────────────────────────
function wireReplay() {
  $('back-btn').addEventListener('click', () => {
    stopPlay();
    showPage('setup');
    loadRuns();
  });

  $('open-btn').addEventListener('click', () => {
    const db = prompt('Chemin du fichier .db :', 'runs/sim.db');
    if (db) openReplay(db.trim());
  });

  // Timeline controls
  $('tl-play').addEventListener ('click', togglePlay);
  $('tl-first').addEventListener('click', () => gotoIdx(0));
  $('tl-last').addEventListener ('click', () => gotoIdx(kfTicks.length - 1));
  $('tl-prev').addEventListener ('click', () => gotoIdx(kfIdx - 1));
  $('tl-next').addEventListener ('click', () => gotoIdx(kfIdx + 1));
  $('tl-slider').addEventListener('input', e => {
    const i = parseInt(e.target.value);
    if (i !== kfIdx) gotoIdx(i);
  });
  $('spd-up').addEventListener  ('click', speedUp);
  $('spd-down').addEventListener('click', speedDown);

  // Canvas interaction
  $('sim-canvas').addEventListener('click',     onCanvasClick);
  $('sim-canvas').addEventListener('mousemove', onCanvasHover);

  // Keyboard shortcuts
  document.addEventListener('keydown', e => {
    if (currentPage !== 'replay') return;
    if (e.target.tagName === 'INPUT') return;
    if (e.key === ' ')           { e.preventDefault(); togglePlay(); return; }
    if (e.key === 'ArrowLeft')   { e.preventDefault();
      e.ctrlKey ? gotoIdx(0) : e.shiftKey ? gotoIdx(kfIdx-10) : gotoIdx(kfIdx-1); return; }
    if (e.key === 'ArrowRight')  { e.preventDefault();
      e.ctrlKey ? gotoIdx(kfTicks.length-1) : e.shiftKey ? gotoIdx(kfIdx+10) : gotoIdx(kfIdx+1); return; }
    if (e.key === '+' || e.key === '=') speedUp();
    if (e.key === '-') speedDown();
  });
}

async function openReplay(dbPath) {
  // Reset state
  stopPlay();
  replayDb  = dbPath;
  replayMeta = null;
  terrainBitmap = null;
  kfTicks = []; kfIdx = 0; curTick = 0;
  frameCache.clear();
  graphHist = {}; popMaxes = {};
  selectedId = null; lastSnap = null;

  $('replay-title').textContent = 'EcoSim — ' + dbPath.split('/').pop().split('\\').pop();
  $('pop-panel').innerHTML = '';
  $('entity-card').innerHTML = '<p class="entity-placeholder">— cliquez une entité</p>';
  clearGraph();

  showPage('replay');
  showCanvasOverlay(true);

  try {
    replayMeta = await fetch(`/api/replay/meta?db=${encodeURIComponent(dbPath)}`).then(r => r.json());
    kfTicks    = replayMeta.keyframe_ticks;

    $('replay-meta').textContent =
      `seed=${replayMeta.seed} · ${replayMeta.preset} · ` +
      `${replayMeta.world_w}×${replayMeta.world_h} · ` +
      `${replayMeta.n_keyframes} keyframes · v${replayMeta.version}`;

    const slider = $('tl-slider');
    slider.min = 0;
    slider.max = Math.max(0, kfTicks.length - 1);
    slider.value = 0;
    $('tl-label').textContent = `0 / ${replayMeta.total_ticks.toLocaleString()}`;

    // Load terrain
    const resp = await fetch(
      `/api/replay/terrain?db=${encodeURIComponent(dbPath)}&w=${CANVAS_W}&h=${CANVAS_H}`
    );
    terrainBitmap = await createImageBitmap(await resp.blob());

    showCanvasOverlay(false);
    await gotoIdx(0);

  } catch (err) {
    showCanvasOverlay(false);
    showToast('Erreur replay : ' + err, true);
  }
}

function showCanvasOverlay(on) {
  $('canvas-loading').classList.toggle('hidden', !on);
}

// ── Frame navigation ──────────────────────────────────────────────────────────
async function gotoIdx(idx) {
  if (!replayDb || kfTicks.length === 0) return;
  idx    = Math.max(0, Math.min(kfTicks.length - 1, idx));
  kfIdx  = idx;
  curTick = kfTicks[idx];

  $('tl-slider').value  = idx;
  $('tl-label').textContent =
    `${curTick.toLocaleString()} / ${replayMeta.total_ticks.toLocaleString()}`;
  $('hud-tick').textContent = `tick ${curTick.toLocaleString()}`;

  const snap = await fetchFrame(curTick);
  if (!snap) return;
  lastSnap = snap;

  renderFrame(snap);
  updatePopPanel(snap.counts);
  updateGraph(snap.counts);
  if (selectedId !== null) updateEntityCard(snap);

  // background pre-fetch
  [idx+1, idx+2, idx-1].forEach(i => {
    if (i >= 0 && i < kfTicks.length) fetchFrame(kfTicks[i]);
  });
}

async function fetchFrame(tick) {
  if (frameCache.has(tick)) return frameCache.get(tick);
  const data = await fetch(
    `/api/replay/frame?db=${encodeURIComponent(replayDb)}&tick=${tick}`
  ).then(r => r.json()).catch(() => null);
  if (data) {
    frameCache.set(tick, data);
    if (frameCache.size > 60) frameCache.delete(frameCache.keys().next().value);
  }
  return data;
}

// ── Canvas render ─────────────────────────────────────────────────────────────
function renderFrame(snap) {
  const cv  = $('sim-canvas');
  const ctx = cv.getContext('2d');
  const cw = cv.width, ch = cv.height;
  const ww = replayMeta.world_w, wh = replayMeta.world_h;
  const sx = cw / ww, sy = ch / wh;

  // terrain
  if (terrainBitmap) ctx.drawImage(terrainBitmap, 0, 0, cw, ch);
  else { ctx.fillStyle = '#050d18'; ctx.fillRect(0, 0, cw, ch); }

  // plants — 1×1 px
  snap.plants.forEach(p => {
    const sp = speciesMap.get(p.sp);
    ctx.fillStyle = sp ? sp.color : '#44aa44';
    ctx.fillRect(Math.round(p.x * sx), Math.round(p.y * sy), 1, 1);
  });

  // animals — 5×5 px
  snap.individuals.forEach(ind => {
    const sp  = speciesMap.get(ind.sp);
    const col = sp ? sp.color : '#ff8800';
    const px  = Math.round(ind.x * sx);
    const py  = Math.round(ind.y * sy);

    if (ind.id === selectedId) {
      ctx.strokeStyle = 'rgba(255,255,200,0.9)';
      ctx.lineWidth   = 1.5;
      ctx.beginPath();
      ctx.arc(px, py, 7, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.fillStyle = col;
    ctx.fillRect(px - 2, py - 2, 5, 5);
  });
}

// ── Population panel ──────────────────────────────────────────────────────────
function updatePopPanel(counts) {
  const panel = $('pop-panel');
  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);

  sorted.forEach(([name, n]) => {
    popMaxes[name] = Math.max(popMaxes[name] || 1, n, 1);
    const sp    = speciesMap.get(name);
    const color = sp ? sp.color : '#888';
    const id    = 'pp-' + cssEscape(name);

    let row = document.getElementById(id);
    if (!row) {
      row = document.createElement('div');
      row.className = 'pop-row';
      row.id = id;
      row.innerHTML = `
        <span class="pop-dot" style="background:${color}"></span>
        <span class="pop-name">${name}</span>
        <div class="pop-bar-wrap">
          <div class="pop-bar-fill" style="background:${color};width:0%"></div>
        </div>
        <span class="pop-count">0</span>
      `;
      panel.appendChild(row);
    }
    const pct = Math.round(n / popMaxes[name] * 100);
    row.querySelector('.pop-bar-fill').style.width = pct + '%';
    const countEl = row.querySelector('.pop-count');
    countEl.textContent  = n.toLocaleString();
    countEl.style.color  = n > 0 ? 'var(--success)' : 'var(--danger)';
  });
}

// ── Graph ─────────────────────────────────────────────────────────────────────
function clearGraph() {
  const gc  = $('graph-canvas');
  const ctx = gc.getContext('2d');
  ctx.clearRect(0, 0, gc.width, gc.height);
}

function updateGraph(counts) {
  Object.entries(counts).forEach(([name, n]) => {
    if (!graphHist[name]) graphHist[name] = [];
    graphHist[name].push(n);
    if (graphHist[name].length > 350) graphHist[name].splice(0, 100);
  });
  drawGraph();
}

function drawGraph() {
  const gc  = $('graph-canvas');
  const ctx = gc.getContext('2d');
  const gw  = gc.width, gh = gc.height;
  ctx.clearRect(0, 0, gw, gh);

  const allVals = Object.values(graphHist).flat();
  if (!allVals.length) return;
  const maxVal = Math.max(1, ...allVals);
  const nPts   = Math.max(...Object.values(graphHist).map(h => h.length));
  if (nPts < 2) return;

  Object.entries(graphHist).forEach(([name, hist]) => {
    if (hist.length < 2) return;
    const sp  = speciesMap.get(name);
    ctx.strokeStyle = sp ? sp.color : '#888';
    ctx.lineWidth   = 1;
    ctx.globalAlpha = 0.85;
    ctx.beginPath();
    hist.forEach((v, i) => {
      const x = 2 + (i / (nPts - 1)) * (gw - 4);
      const y = gh - 3 - (v / maxVal) * (gh - 6);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
  });
  ctx.globalAlpha = 1;
}

// ── Entity card ───────────────────────────────────────────────────────────────
function onCanvasClick(ev) {
  if (!lastSnap || !replayMeta) return;
  const cv   = $('sim-canvas');
  const rect = cv.getBoundingClientRect();
  const cx   = ev.clientX - rect.left;
  const cy   = ev.clientY - rect.top;
  const ww   = replayMeta.world_w, wh = replayMeta.world_h;
  const wx   = (cx / cv.width)  * ww;
  const wy   = (cy / cv.height) * wh;

  let bestId = null, bestD = 12;
  [...lastSnap.plants, ...lastSnap.individuals].forEach(e => {
    const d = Math.hypot(e.x - wx, e.y - wy);
    if (d < bestD) { bestD = d; bestId = e.id; }
  });

  selectedId = bestId;
  renderFrame(lastSnap);
  updateEntityCard(lastSnap);
}

function onCanvasHover(ev) {
  if (!lastSnap || !replayMeta) return;
  const cv   = $('sim-canvas');
  const rect = cv.getBoundingClientRect();
  const cx   = ev.clientX - rect.left;
  const cy   = ev.clientY - rect.top;
  const ww   = replayMeta.world_w, wh = replayMeta.world_h;
  const wx   = (cx / cv.width)  * ww;
  const wy   = (cy / cv.height) * wh;

  let bestName = '', bestD = 8;
  [...lastSnap.plants, ...lastSnap.individuals].forEach(e => {
    const d = Math.hypot(e.x - wx, e.y - wy);
    if (d < bestD) { bestD = d; bestName = e.sp; }
  });
  $('hud-hover').textContent = bestName;
}

function updateEntityCard(snap) {
  const card = $('entity-card');
  if (selectedId === null) {
    card.innerHTML = '<p class="entity-placeholder">— cliquez une entité</p>';
    return;
  }
  const entity = [...snap.plants, ...snap.individuals].find(e => e.id === selectedId);
  if (!entity) {
    card.innerHTML = '<p class="entity-placeholder" style="color:var(--danger)">✝ disparu</p>';
    return;
  }
  const sp    = speciesMap.get(entity.sp);
  const color = sp ? sp.color : '#888';
  const maxE  = 200;
  const ratio = Math.max(0, Math.min(1, entity.energy / maxE));
  const barCol = ratio > 0.5 ? 'var(--success)' : ratio > 0.2 ? 'var(--warn)' : 'var(--danger)';

  card.innerHTML = `
    <div class="entity-name" style="color:${color}">
      <span class="sp-dot" style="background:${color};display:inline-block;margin-right:6px;vertical-align:middle"></span>${entity.sp}
    </div>
    <div class="energy-bar-wrap">
      <div class="energy-bar-fill" style="width:${Math.round(ratio*100)}%;background:${barCol}"></div>
    </div>
    <div class="entity-info">
      x: ${entity.x?.toFixed(1)}&nbsp;&nbsp;y: ${entity.y?.toFixed(1)}<br>
      énergie: ${entity.energy?.toFixed(1)}<br>
      âge: ${entity.age?.toLocaleString()} ticks<br>
      état: ${entity.state || '—'}
    </div>
  `;
}

// ── Playback ──────────────────────────────────────────────────────────────────
function togglePlay() {
  playing ? stopPlay() : startPlay();
}

function startPlay() {
  if (!replayDb || kfTicks.length === 0) return;
  playing     = true;
  nextTarget  = performance.now();
  $('tl-play').classList.add('playing');
  $('tl-play').textContent = '⏸';
  rafId = requestAnimationFrame(playLoop);
}

function stopPlay() {
  playing = false;
  if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null; }
  $('tl-play').classList.remove('playing');
  $('tl-play').textContent = '▶';
}

function playLoop(now) {
  if (!playing) return;
  if (now >= nextTarget) {
    const nextIdx = kfIdx + 1;
    if (nextIdx >= kfTicks.length) { stopPlay(); return; }
    gotoIdx(nextIdx);
    const speed = speedLevels[speedIdx];
    nextTarget += 1000 / Math.max(speed, 0.1);
  }
  rafId = requestAnimationFrame(playLoop);
}

function speedUp() {
  speedIdx = Math.min(speedLevels.length - 1, speedIdx + 1);
  updateSpeedLabel();
}
function speedDown() {
  speedIdx = Math.max(0, speedIdx - 1);
  updateSpeedLabel();
}
function updateSpeedLabel() {
  const s = speedLevels[speedIdx];
  $('spd-label').textContent = s >= 1 ? `×${s}` : `×${s}`;
}

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
