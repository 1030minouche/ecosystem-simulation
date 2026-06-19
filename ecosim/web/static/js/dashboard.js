/**
 * dashboard.js — Gestion de la liste des runs (tri, filtre, comparaison).
 * Exposé via window.Dashboard pour être appelé depuis app.js.
 */

const Dashboard = (() => {
  let _runs = [];
  let _sortKey = 'created_at';
  let _sortDir = -1; // -1 = desc
  let _filterText = '';
  let _onOpen = null;
  let _onExtend = null;

  function init({ onOpen, onExtend }) {
    _onOpen   = onOpen;
    _onExtend = onExtend;
  }

  function setRuns(runs) {
    _runs = runs;
  }

  function _sorted(runs) {
    return [...runs].sort((a, b) => {
      let va = a[_sortKey] ?? '';
      let vb = b[_sortKey] ?? '';
      if (typeof va === 'string') va = va.toLowerCase();
      if (typeof vb === 'string') vb = vb.toLowerCase();
      return va < vb ? _sortDir : va > vb ? -_sortDir : 0;
    });
  }

  function _filtered(runs) {
    if (!_filterText) return runs;
    const q = _filterText.toLowerCase();
    return runs.filter(r =>
      (r.name || '').toLowerCase().includes(q) ||
      (r.run_id || '').toLowerCase().includes(q) ||
      (r.terrain_preset || '').toLowerCase().includes(q) ||
      (r.species || []).some(s => s.toLowerCase().includes(q))
    );
  }

  function render(container) {
    const runs = _sorted(_filtered(_runs));
    container.innerHTML = '';

    if (!runs.length) {
      container.innerHTML = '<p class="no-runs">Aucun enregistrement</p>';
      return;
    }

    // Barre de contrôle
    const ctrl = document.createElement('div');
    ctrl.className = 'dash-ctrl';
    ctrl.innerHTML = `
      <input class="dash-filter" type="text" placeholder="Filtrer…" value="${_filterText}">
      <select class="dash-sort">
        <option value="created_at" ${_sortKey==='created_at'?'selected':''}>Date</option>
        <option value="ticks"      ${_sortKey==='ticks'     ?'selected':''}>Ticks</option>
        <option value="file_size_mb" ${_sortKey==='file_size_mb'?'selected':''}>Taille</option>
        <option value="name"       ${_sortKey==='name'      ?'selected':''}>Nom</option>
      </select>
      <button class="dash-sort-dir">${_sortDir === -1 ? '↓' : '↑'}</button>`;
    ctrl.querySelector('.dash-filter').addEventListener('input', e => {
      _filterText = e.target.value;
      render(container);
    });
    ctrl.querySelector('.dash-sort').addEventListener('change', e => {
      _sortKey = e.target.value;
      render(container);
    });
    ctrl.querySelector('.dash-sort-dir').addEventListener('click', () => {
      _sortDir *= -1;
      render(container);
    });
    container.appendChild(ctrl);

    // Liste
    runs.slice(0, 12).forEach(run => {
      const el = document.createElement('div');
      el.className = 'run-item';
      const idChip  = run.run_id ? `<span class="run-id-chip">#${run.run_id}</span>` : '';
      const species = (run.species || []).slice(0, 4).join(', ');
      const ticks   = run.ticks ? run.ticks.toLocaleString() + ' ticks' : '';
      el.innerHTML = `
        <div class="run-info">
          <span class="run-name">${run.name}</span>${idChip}
          <span class="run-species-hint">${species}</span>
        </div>
        <div class="run-meta">
          <span class="run-size">${run.file_size_mb ?? run.size_mb ?? '?'} MB · ${ticks}</span>
          <span class="run-open">▶ Replay</span>
          <span class="run-extend">⊕ Étendre</span>
        </div>`;
      el.querySelector('.run-open').addEventListener('click', e => {
        e.stopPropagation();
        _onOpen && _onOpen(run.path);
      });
      el.querySelector('.run-extend').addEventListener('click', e => {
        e.stopPropagation();
        _onExtend && _onExtend(run.path);
      });
      container.appendChild(el);
    });
  }

  return { init, setRuns, render };
})();

window.Dashboard = Dashboard;
