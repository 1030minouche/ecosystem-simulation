'use strict';
/**
 * EcoSim Web UI
 *
 * Architecture de rendu :
 *   Les frames PNG sont pré-rendues pendant la simulation et stockées dans le
 *   .db (table renders).  Au replay, le serveur les sert directement.
 *   Le client fait uniquement ctx.drawImage() → 60 fps, zéro re-calcul.
 *
 * Cycle de vie du replay :
 *   1. openReplay(db) → metadata
 *   2. Charge toutes les frames en parallèle (avec progress)
 *   3. Play loop synchrone (RAF) : drawImage(frameImgs[kfIdx], 0, 0)
 *   4. Clic entité → fetch JSON lazy (positions + énergie)
 */

// ── Constantes ────────────────────────────────────────────────────────────────
const CANVAS_W   = 720;
const CANVAS_H   = 576;
const PREVIEW_SZ = 260;
const DAY_LENGTH = 1200;   // doit correspondre à engine_const.DAY_LENGTH

const SPEED_LEVELS = [0.25, 0.5, 1, 2, 4, 8, 16, 32];
const GROUPS = [
  ['PLANTES',    ['herbe', 'fougere', 'champignon', 'baies']],
  ['HERBIVORES', ['lapin', 'campagnol', 'cerf', 'sanglier']],
  ['PRÉDATEURS', ['renard', 'loup', 'hibou', 'aigle']],
];

// ── État global ───────────────────────────────────────────────────────────────
let ws             = null;
let currentPage    = 'setup';
let speciesMap     = new Map();

// SETUP
let previewTimer   = null;

// RUNNING
let runConfig      = null;

// REPLAY — state machine
let replayDb       = null;
let replayMeta     = null;
let kfTicks        = [];          // liste des ticks keyframe
let kfIdx          = 0;           // index courant
let frameImgs      = [];          // HTMLImageElement pré-chargés (index = kfIdx)
let jsonCache      = new Map();   // tick → données JSON (lazy)
let popMaxes       = {};
let graphHist      = {};
let selectedId     = null;
let lastJsonSnap   = null;        // dernier JSON snap affiché

// Playback
let playing        = false;
let rafId          = null;
let nextTarget     = 0;
let speedIdx       = 2;           // ×1 par défaut

// ── DOM ───────────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const q = sel => document.querySelector(sel);

// ── Navigation ────────────────────────────────────────────────────────────────
function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  $(`page-${name}`).classList.add('active');
  currentPage = name;
}

function toast(msg, isErr = false) {
  const el = $('toast');
  el.textContent = msg;
  el.className = 'toast' + (isErr ? ' error' : '');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add('hidden'), 4500);
}

// ── WebSocket ─────────────────────────────────────────────────────────────────
let _keepAlive = null;
function connectWS() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => {
    clearInterval(_keepAlive);
    _keepAlive = setInterval(() => {
      if (ws?.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ type: 'ping' }));
    }, 20000);
  };
  ws.onclose   = () => setTimeout(connectWS, 2000);
  ws.onerror   = () => {};
  ws.onmessage = e => { try { dispatch(JSON.parse(e.data)); } catch (_) {} };
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
        <span class="form-hint">init:</span>
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
    list.innerHTML = '<p class="no-runs">Aucun enregistrement</p>';
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
  $('seed-input').addEventListener('input',    () => schedulePreview());
  $('preset-select').addEventListener('change', () => schedulePreview(0));
  document.querySelectorAll('input[name="gs"]')
    .forEach(r => r.addEventListener('change', () => schedulePreview(0)));
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
  const seed      = parseInt($('seed-input').value) || 42;
  const preset    = $('preset-select').value;
  const gridSize  = currentGridSize();

  $('terrain-spinner').classList.remove('hidden');
  try {
    const resp = await fetch('/api/terrain/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seed, preset, size: PREVIEW_SZ, grid_size: gridSize }),
    });
    const bmp = await createImageBitmap(await resp.blob());
    const cv  = $('terrain-preview');
    const ctx = cv.getContext('2d');
    ctx.drawImage(bmp, 0, 0, cv.width, cv.height);
    $('terrain-info').textContent = `seed ${seed}  ·  preset: ${preset}  ·  ${gridSize}×${gridSize}`;
  } catch {
    $('terrain-info').textContent = 'Erreur preview';
  } finally {
    $('terrain-spinner').classList.add('hidden');
  }
}

function onLaunch() {
  const seed     = parseInt($('seed-input').value)  || 42;
  const ticks    = Math.max(100, parseInt($('ticks-input').value) || 1000);
  const outPath  = $('out-input').value.trim()      || 'runs/sim.db';
  const preset   = $('preset-select').value;
  const gridSize = currentGridSize();

  const species  = [];
  document.querySelectorAll('.sp-row').forEach(row => {
    const cb  = row.querySelector('.sp-check');
    const cnt = row.querySelector('.sp-count');
    if (!cb) return;
    const sp = speciesMap.get(cb.dataset.name);
    if (!sp) return;
    species.push({ enabled: cb.checked, count: parseInt(cnt.value) || 0, params: sp.params });
  });

  runConfig = { seed, ticks, grid_size: gridSize, preset, out_path: outPath, species };

  $('run-config-lbl').textContent =
    `${gridSize}×${gridSize}  ·  seed=${seed}  ·  ${ticks.toLocaleString()} ticks  ·  ${outPath}`;
  $('prog-total').textContent = ticks.toLocaleString();
  resetProgressUI();
  showPage('running');

  fetch('/api/sim/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(runConfig),
  });
}

function resetProgressUI() {
  $('progress-bar').style.width = '0%';
  $('prog-tick').textContent    = '0';
  $('prog-pct').textContent     = '0%';
  $('prog-tps').textContent     = '— ticks/s';
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
  const pct = Math.min(100, Math.round((msg.done / msg.ticks) * 100));
  $('progress-bar').style.width = pct + '%';
  $('prog-tick').textContent    = msg.tick.toLocaleString();
  $('prog-pct').textContent     = pct + '%';
  $('prog-tps').textContent     = msg.tps.toLocaleString() + ' ticks/s';
  $('prog-eta').textContent     = msg.eta_s != null ? 'ETA ' + fmtEta(msg.eta_s) : '—';
  updateRunGrid(msg.counts);
}

function fmtEta(s) {
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${(s % 60).toString().padStart(2, '0')}s`;
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
    card.style.opacity = n > 0 ? '1' : '0.3';
  });
}

function onSimDone(msg) {
  $('progress-bar').style.width = '100%';
  $('prog-pct').textContent     = '100%';
  setTimeout(() => openReplay(msg.db_path), 700);
}

function onSimError(msg) {
  toast('Erreur simulation : ' + msg.message, true);
  showPage('setup');
}

// ══════════════════════════════════════════════════════════════════════════════
// REPLAY — openReplay + pré-chargement
// ══════════════════════════════════════════════════════════════════════════════

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

  $('tl-play').addEventListener ('click', togglePlay);
  $('tl-first').addEventListener('click', () => gotoIdx(0));
  $('tl-last').addEventListener ('click', () => gotoIdx(kfTicks.length - 1));
  $('tl-prev').addEventListener ('click', () => gotoIdx(kfIdx - 1));
  $('tl-next').addEventListener ('click', () => gotoIdx(kfIdx + 1));
  $('tl-slider').addEventListener('input', e => gotoIdx(parseInt(e.target.value)));

  $('spd-up').addEventListener  ('click', speedUp);
  $('spd-down').addEventListener('click', speedDown);

  $('sim-canvas').addEventListener('click',     onCanvasClick);
  $('sim-canvas').addEventListener('mousemove', onCanvasHover);

  document.addEventListener('keydown', e => {
    if (currentPage !== 'replay') return;
    if (e.target.tagName === 'INPUT') return;
    if (e.key === ' ')          { e.preventDefault(); togglePlay(); }
    else if (e.key === 'ArrowLeft')  { e.preventDefault();
      e.ctrlKey ? gotoIdx(0) : e.shiftKey ? gotoIdx(kfIdx-10) : gotoIdx(kfIdx-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault();
      e.ctrlKey ? gotoIdx(kfTicks.length-1) : e.shiftKey ? gotoIdx(kfIdx+10) : gotoIdx(kfIdx+1); }
    else if (e.key === '+' || e.key === '=') speedUp();
    else if (e.key === '-') speedDown();
  });
}

// Helper null-safe pour les éléments optionnels
function setText(id, val) { const el = $(id); if (el) el.textContent = val; }
function setStyle(id, prop, val) { const el = $(id); if (el) el.style[prop] = val; }

async function openReplay(dbPath) {
  stopPlay();

  // Afficher la page replay EN PREMIER — avant tout accès DOM risqué
  showPage('replay');
  setCanvasOverlay('Chargement…');

  // Réinitialisation de l'état
  replayDb    = dbPath;
  replayMeta  = null;
  kfTicks     = [];
  kfIdx       = 0;
  frameImgs   = [];
  jsonCache.clear();
  popMaxes    = {};
  graphHist   = {};
  selectedId  = null;
  lastJsonSnap = null;

  const shortName = dbPath.split('/').pop().split('\\').pop();
  setText('replay-title', 'EcoSim — ' + shortName);
  setText('replay-meta',  '—');
  const popEl = $('pop-panel'); if (popEl) popEl.innerHTML = '';
  const entEl = $('entity-card');
  if (entEl) entEl.innerHTML = '<p class="entity-placeholder">— cliquez une entité</p>';
  clearGraphCanvas();

  // Réinitialiser le bloc progression (null-safe)
  setText('si-frame', '— / —');
  setText('si-tick',  '—');
  setText('si-day',   '—');
  setText('si-speed', `×${SPEED_LEVELS[speedIdx]}`);
  setStyle('sim-track-fill', 'width', '0%');
  ['si-seed','si-preset','si-grid','si-maxTicks','si-kf','si-ver']
    .forEach(id => setText(id, '—'));

  setCanvasOverlay('Chargement des métadonnées…');

  try {
    // 1. Métadonnées
    replayMeta = await fetch(`/api/replay/meta?db=${encodeURIComponent(dbPath)}`)
      .then(r => { if (!r.ok) throw new Error('meta 404'); return r.json(); });
    kfTicks = replayMeta.keyframe_ticks;

    $('replay-meta').textContent =
      `seed=${replayMeta.seed} · ${replayMeta.preset} · ` +
      `${replayMeta.world_w}×${replayMeta.world_h} · ` +
      `${replayMeta.n_keyframes} keyframes · v${replayMeta.version}`;

    // Bloc CONFIG SIMULATION
    $('si-seed').textContent    = replayMeta.seed;
    $('si-preset').textContent  = replayMeta.preset;
    $('si-grid').textContent    = `${replayMeta.world_w}×${replayMeta.world_h}`;
    $('si-maxTicks').textContent = (replayMeta.max_ticks ?? replayMeta.total_ticks).toLocaleString() + ' ticks';
    $('si-kf').textContent      = replayMeta.n_keyframes;
    $('si-ver').textContent     = `v${replayMeta.version}`;

    const slider = $('tl-slider');
    slider.min   = 0;
    slider.max   = Math.max(0, kfTicks.length - 1);
    slider.value = 0;
    updateTickLabel(0);

    // 2. Charge toutes les frames images en parallèle (servies depuis la BD)
    await loadAllFrameImages(dbPath, kfTicks);

    setCanvasOverlay(null);
    renderIdx(0);

  } catch (err) {
    setCanvasOverlay(null);
    toast('Erreur replay : ' + err, true);
    console.error(err);
  }
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

async function loadAllFrameImages(db, ticks) {
  frameImgs = new Array(ticks.length).fill(null);
  let loaded = 0;

  setCanvasOverlay(`Rendu des frames — 0 / ${ticks.length}`);

  const loadOne = (tick, i) => new Promise(resolve => {
    const img = new Image();
    img.onload = () => {
      frameImgs[i] = img;
      loaded++;
      if (loaded % 3 === 0 || loaded === ticks.length)
        setCanvasOverlay(`Rendu des frames — ${loaded} / ${ticks.length}`);
      resolve();
    };
    img.onerror = () => { loaded++; resolve(); };
    img.src = `/api/replay/frame_img?db=${encodeURIComponent(db)}&tick=${tick}&w=${CANVAS_W}&h=${CANVAS_H}`;
  });

  // 6 requêtes en parallèle, puis batch suivant
  const BATCH = 6;
  for (let i = 0; i < ticks.length; i += BATCH) {
    await Promise.all(
      ticks.slice(i, i + BATCH).map((tick, j) => loadOne(tick, i + j))
    );
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// REPLAY — navigation (synchrone, aucun await ici)
// ══════════════════════════════════════════════════════════════════════════════

function gotoIdx(idx) {
  if (!replayDb || kfTicks.length === 0) return;
  idx   = Math.max(0, Math.min(kfTicks.length - 1, idx));
  kfIdx = idx;

  $('tl-slider').value = idx;
  updateTickLabel(idx);

  renderIdx(idx);

  // Charge JSON lazy pour panel populations + entité
  loadJsonLazy(kfTicks[idx]);
}

function updateTickLabel(idx) {
  const tick    = kfTicks[idx] ?? 0;
  const maxT    = replayMeta?.max_ticks ?? replayMeta?.total_ticks ?? 0;
  const pct     = maxT > 0 ? Math.min(100, Math.round(tick / maxT * 100)) : 0;
  const day     = Math.floor(tick / DAY_LENGTH) + 1;
  const tickRel = tick - (replayMeta?.min_tick ?? 0);   // ticks depuis début sim

  $('tl-label').textContent = `${tick.toLocaleString()} / ${maxT.toLocaleString()}`;
  $('hud-tick').textContent = `tick ${tick.toLocaleString()}`;

  // Bloc PROGRESSION
  $('si-frame').textContent  = `${idx + 1} / ${kfTicks.length}`;
  $('si-tick').textContent   = `${tick.toLocaleString()} / ${maxT.toLocaleString()}`;
  $('si-day').textContent    = `Jour ${day.toLocaleString()}`;
  $('si-speed').textContent  = `×${SPEED_LEVELS[speedIdx]}`;
  $('sim-track-fill').style.width = pct + '%';
}

/** Rendu principal — pur drawImage, 0 computation JS. */
function renderIdx(idx) {
  const cv  = $('sim-canvas');
  const ctx = cv.getContext('2d');
  const img = frameImgs[idx];

  if (img?.complete && img.naturalWidth > 0) {
    ctx.drawImage(img, 0, 0, cv.width, cv.height);
  } else {
    // Frame pas encore chargée : fond sombre
    ctx.fillStyle = '#050d18';
    ctx.fillRect(0, 0, cv.width, cv.height);
  }

  // Overlay sélection (ring autour de l'entité choisie)
  if (selectedId !== null && lastJsonSnap) {
    drawSelectionRing(ctx, lastJsonSnap, cv.width, cv.height);
  }
}

function drawSelectionRing(ctx, snap, cw, ch) {
  if (!replayMeta) return;
  const entity = [...snap.plants, ...snap.individuals].find(e => e.id === selectedId);
  if (!entity) return;
  const sx = cw / replayMeta.world_w;
  const sy = ch / replayMeta.world_h;
  const px = entity.x * sx;
  const py = entity.y * sy;
  const sp = speciesMap.get(entity.sp);
  ctx.strokeStyle = 'rgba(255,255,200,0.95)';
  ctx.lineWidth   = 2;
  ctx.beginPath();
  ctx.arc(px, py, 8, 0, Math.PI * 2);
  ctx.stroke();
  if (sp) {
    ctx.strokeStyle = sp.color;
    ctx.lineWidth   = 1;
    ctx.beginPath();
    ctx.arc(px, py, 11, 0, Math.PI * 2);
    ctx.stroke();
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// REPLAY — JSON lazy (populations + entity panel)
// ══════════════════════════════════════════════════════════════════════════════

function loadJsonLazy(tick) {
  if (jsonCache.has(tick)) {
    const snap = jsonCache.get(tick);
    lastJsonSnap = snap;
    updatePopPanel(snap.counts);
    updateGraph(snap.counts);
    if (selectedId !== null) updateEntityCard(snap);
    return;
  }

  fetch(`/api/replay/frame_json?db=${encodeURIComponent(replayDb)}&tick=${tick}`)
    .then(r => r.json())
    .then(snap => {
      jsonCache.set(tick, snap);
      if (tick === kfTicks[kfIdx]) {   // toujours sur ce tick ?
        lastJsonSnap = snap;
        updatePopPanel(snap.counts);
        updateGraph(snap.counts);
        if (selectedId !== null) updateEntityCard(snap);
      }
    })
    .catch(() => {});
}

// ══════════════════════════════════════════════════════════════════════════════
// REPLAY — Playback
// ══════════════════════════════════════════════════════════════════════════════

function togglePlay() { playing ? stopPlay() : startPlay(); }

function startPlay() {
  if (!replayDb || kfTicks.length === 0) return;
  playing    = true;
  nextTarget = performance.now();
  $('tl-play').classList.add('playing');
  $('tl-play').textContent = '⏸';
  rafId = requestAnimationFrame(playLoop);
}

function stopPlay() {
  playing = false;
  if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null; }
  if ($('tl-play')) {
    $('tl-play').classList.remove('playing');
    $('tl-play').textContent = '▶';
  }
}

function playLoop(now) {
  if (!playing) return;

  if (now >= nextTarget) {
    const nextIdx = kfIdx + 1;
    if (nextIdx >= kfTicks.length) { stopPlay(); return; }

    // Avance seulement si la frame est déjà chargée
    const img = frameImgs[nextIdx];
    if (img?.complete && img.naturalWidth > 0) {
      kfIdx = nextIdx;
      $('tl-slider').value = nextIdx;
      updateTickLabel(nextIdx);
      renderIdx(nextIdx);
      loadJsonLazy(kfTicks[nextIdx]);
    }
    // Recalcule le prochain instant même si on a sauté
    nextTarget += 1000 / Math.max(SPEED_LEVELS[speedIdx], 0.1);
  }

  rafId = requestAnimationFrame(playLoop);
}

function speedUp() {
  speedIdx = Math.min(SPEED_LEVELS.length - 1, speedIdx + 1);
  $('spd-label').textContent = `×${SPEED_LEVELS[speedIdx]}`;
  $('si-speed').textContent  = `×${SPEED_LEVELS[speedIdx]}`;
}
function speedDown() {
  speedIdx = Math.max(0, speedIdx - 1);
  $('spd-label').textContent = `×${SPEED_LEVELS[speedIdx]}`;
  $('si-speed').textContent  = `×${SPEED_LEVELS[speedIdx]}`;
}

// ══════════════════════════════════════════════════════════════════════════════
// REPLAY — Panel populations
// ══════════════════════════════════════════════════════════════════════════════

function updatePopPanel(counts) {
  const panel   = $('pop-panel');
  const sorted  = Object.entries(counts).sort((a, b) => b[1] - a[1]);

  sorted.forEach(([name, n]) => {
    popMaxes[name] = Math.max(popMaxes[name] || 1, n, 1);
    const sp    = speciesMap.get(name);
    const color = sp ? sp.color : '#888';
    const id    = 'pp-' + CSS.escape(name);

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
    const pct    = Math.round(n / popMaxes[name] * 100);
    row.querySelector('.pop-bar-fill').style.width = pct + '%';
    const cnt    = row.querySelector('.pop-count');
    cnt.textContent = n.toLocaleString();
    cnt.style.color = n > 0 ? 'var(--success)' : 'var(--danger)';
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// REPLAY — Graphe
// ══════════════════════════════════════════════════════════════════════════════

function clearGraphCanvas() {
  const gc = $('graph-canvas');
  if (!gc) return;
  gc.getContext('2d').clearRect(0, 0, gc.width, gc.height);
}

function updateGraph(counts) {
  Object.entries(counts).forEach(([name, n]) => {
    if (!graphHist[name]) graphHist[name] = [];
    graphHist[name].push(n);
    if (graphHist[name].length > 400) graphHist[name].splice(0, 100);
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

  ctx.globalAlpha = 0.85;
  Object.entries(graphHist).forEach(([name, hist]) => {
    if (hist.length < 2) return;
    const sp = speciesMap.get(name);
    ctx.strokeStyle = sp ? sp.color : '#888';
    ctx.lineWidth   = 1.2;
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

// ══════════════════════════════════════════════════════════════════════════════
// REPLAY — Sélection entité
// ══════════════════════════════════════════════════════════════════════════════

function onCanvasClick(ev) {
  if (!lastJsonSnap || !replayMeta) return;
  const cv     = $('sim-canvas');
  const rect   = cv.getBoundingClientRect();
  const scaleX = cv.width  / rect.width;
  const scaleY = cv.height / rect.height;
  const cx     = (ev.clientX - rect.left) * scaleX;
  const cy     = (ev.clientY - rect.top)  * scaleY;
  const wx     = cx / cv.width  * replayMeta.world_w;
  const wy     = cy / cv.height * replayMeta.world_h;

  let bestId = null, bestD = 14;
  [...lastJsonSnap.plants, ...lastJsonSnap.individuals].forEach(e => {
    const d = Math.hypot(e.x - wx, e.y - wy);
    if (d < bestD) { bestD = d; bestId = e.id; }
  });

  selectedId = bestId;
  renderIdx(kfIdx);
  if (lastJsonSnap) updateEntityCard(lastJsonSnap);
}

function onCanvasHover(ev) {
  if (!lastJsonSnap || !replayMeta) return;
  const cv   = $('sim-canvas');
  const rect = cv.getBoundingClientRect();
  const scaleX = cv.width  / rect.width;
  const scaleY = cv.height / rect.height;
  const cx   = (ev.clientX - rect.left) * scaleX;
  const cy   = (ev.clientY - rect.top)  * scaleY;
  const wx   = cx / cv.width  * replayMeta.world_w;
  const wy   = cy / cv.height * replayMeta.world_h;

  let bestName = '', bestD = 10;
  [...lastJsonSnap.plants, ...lastJsonSnap.individuals].forEach(e => {
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
  const barC  = ratio > 0.5 ? 'var(--success)' : ratio > 0.2 ? 'var(--warn)' : 'var(--danger)';

  card.innerHTML = `
    <div class="entity-name" style="color:${color}">
      <span class="sp-dot" style="background:${color};display:inline-block;margin-right:6px;vertical-align:middle"></span>${entity.sp}
    </div>
    <div class="energy-bar-wrap">
      <div class="energy-bar-fill" style="width:${Math.round(ratio*100)}%;background:${barC}"></div>
    </div>
    <div class="entity-info">
      x: ${entity.x?.toFixed(1)}&nbsp;&nbsp;y: ${entity.y?.toFixed(1)}<br>
      énergie: ${entity.energy?.toFixed(1)}<br>
      âge: ${entity.age?.toLocaleString()} ticks<br>
      état: ${entity.state || '—'}
    </div>
  `;
}

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
