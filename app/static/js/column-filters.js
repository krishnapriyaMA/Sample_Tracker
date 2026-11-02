/* Per-column filters for any <table class="data-table" data-col-filters>.
 * Adds a second header row: a dropdown for columns with few distinct values
 * (status, client...), a "contains" text box for the rest. Filters combine (AND).
 * Dashboard tables are injected after load, so call initColumnFilters(table) then. */
(function () {
  const SELECT_MAX = 15;
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();

  function initColumnFilters(table) {
    if (!table || table.dataset.cfReady) return;
    const headRow = table.querySelector('thead tr');
    const rows = Array.from(table.querySelectorAll('tbody tr')).filter(
      (r) => !(r.children.length === 1 && r.children[0].colSpan > 1)
    );
    if (!headRow || !rows.length) return;
    table.dataset.cfReady = '1';

    const ths = Array.from(headRow.children);
    const filterRow = document.createElement('tr');
    filterRow.className = 'filter-row';
    const controls = [];

    ths.forEach((th, i) => {
      const cell = document.createElement('th');
      controls.push(null);
      if (norm(th.textContent)) {
        const values = new Set();
        rows.forEach((r) => { if (r.children[i]) values.add(norm(r.children[i].textContent)); });
        let ctl;
        if (values.size <= SELECT_MAX) {
          ctl = document.createElement('select');
          ctl.innerHTML = '<option value="">All</option>';
          Array.from(values).sort((a, b) => a.localeCompare(b)).forEach((v) => {
            const o = document.createElement('option');
            o.value = v; o.textContent = v || '(blank)';
            ctl.appendChild(o);
          });
          ctl.dataset.mode = 'exact';
          ctl.addEventListener('change', apply);
        } else {
          ctl = document.createElement('input');
          ctl.type = 'text'; ctl.placeholder = 'Filter…';
          ctl.dataset.mode = 'contains';
          ctl.addEventListener('input', apply);
        }
        ctl.className = 'col-filter';
        ctl.addEventListener('click', (e) => e.stopPropagation());
        cell.appendChild(ctl);
        controls[i] = ctl;
      }
      filterRow.appendChild(cell);
    });
    headRow.parentNode.appendChild(filterRow);

    const bar = document.createElement('div');
    bar.className = 'filter-status';
    bar.innerHTML = '<span class="fs-count"></span> <button type="button" class="fs-clear" style="display:none">Clear column filters</button>';
    (table.closest('.table-wrap') || table).before(bar);
    const countEl = bar.querySelector('.fs-count');
    const clearBtn = bar.querySelector('.fs-clear');
    clearBtn.addEventListener('click', () => {
      controls.forEach((c) => { if (c) c.value = ''; });
      apply();
    });

    function apply() {
      const active = [];
      controls.forEach((c, i) => {
        if (c && c.value !== '') active.push([i, c.dataset.mode, c.value.toLowerCase()]);
      });
      let shown = 0;
      rows.forEach((r) => {
        const ok = active.every(([i, mode, val]) => {
          const text = norm(r.children[i] ? r.children[i].textContent : '').toLowerCase();
          return mode === 'exact' ? text === val : text.includes(val);
        });
        r.style.display = ok ? '' : 'none';
        if (ok) shown++;
      });
      countEl.textContent = 'Showing ' + shown + ' of ' + rows.length;
      clearBtn.style.display = active.length ? '' : 'none';
    }
    apply();
  }

  window.initColumnFilters = initColumnFilters;
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('table.data-table[data-col-filters]').forEach(initColumnFilters);
  });
})();