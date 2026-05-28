/**
 * 공통 유틸리티
 */

/** 숫자를 천단위 콤마 포맷으로 변환 */
function fmt(n) {
  if (n == null || n === '') return '0';
  return Math.round(n).toLocaleString('ko-KR');
}

/** JSON fetch 래퍼 */
async function fetchJSON(url, opts = {}) {
  const res = await fetch(url, opts);
  if (!res.ok) {
    const err = await res.text();
    console.error('API error:', res.status, err);
    return null;
  }
  return res.json();
}

/**
 * GridTable — 인라인 편집 그리드
 *
 * columns 정의:
 *   { key, type:'text|date|number|select|computed',
 *     options:[]/fn, compute:fn, render:fn, align:'end', step }
 */
class GridTable {
  constructor({ tableId, columns, apiUrl, getQueryParams, onLoad, getExtraData, onSave, onDelete, onStartEdit, selectable, onSelectChange, onBeforeDelete }) {
    this.tableEl  = document.getElementById(tableId);
    this.tbody    = this.tableEl.querySelector('tbody');
    this.columns  = columns;
    this.apiUrl   = apiUrl;
    this.getQueryParams = getQueryParams || (() => '');
    this.onLoad         = onLoad         || null;
    this.getExtraData   = getExtraData   || (() => ({}));
    this.onSave         = onSave         || null;
    this.onDelete       = onDelete       || null;
    this.onStartEdit    = onStartEdit    || null;
    this.onBeforeDelete = onBeforeDelete || null;
    this.selectable       = selectable       || false;
    this.selected         = new Set();
    this.onSelectChange   = onSelectChange   || null;
    this._tr    = null;   // editing <tr>
    this._keyFn = null;
    this.rows   = [];
    this._ncols = columns.length + 1 + (this.selectable ? 1 : 0);

    // event delegation
    this.tbody.addEventListener('click', e => {
      // 체크박스 클릭은 편집 모드 진입하지 않음
      if (e.target.type === 'checkbox') {
        const tr = e.target.closest('tr[data-id]');
        if (tr) this._toggleSelect(tr.dataset.id, e.target.checked);
        return;
      }
      const btn = e.target.closest('[data-ga]');
      if (btn) {
        e.stopPropagation();
        const a = btn.dataset.ga;
        if      (a === 's') this.saveEdit();
        else if (a === 'c') this.cancelEdit();
        else if (a === 'd') this._delete(btn.dataset.id);
        return;
      }
      const tr = e.target.closest('tr[data-id]');
      if (tr && tr !== this._tr) this.startEdit(tr);
    });

    // click outside → cancel (이벤트 버블링으로 인한 즉시 취소 방지)
    this._ignoreDocClick = false;
    document.addEventListener('click', e => {
      if (this._ignoreDocClick) return;
      if (this._tr && !this.tableEl.contains(e.target)) this.cancelEdit();
    });

    // 정렬 상태 초기화 및 헤더 클릭 이벤트 바인딩
    this.sortKey = null;
    this.sortAsc = true;
    const thead = this.tableEl.querySelector('thead');
    if (thead) {
      thead.style.cursor = 'pointer';
      thead.style.userSelect = 'none';
      thead.addEventListener('click', e => {
        const th = e.target.closest('th');
        if (!th) return;
        const tr = th.closest('tr');
        const ths = Array.from(tr.querySelectorAll('th'));
        const idx = ths.indexOf(th);
        const colIdx = this.selectable ? idx - 1 : idx;
        if (colIdx < 0 || colIdx >= this.columns.length) return;
        const col = this.columns[colIdx];
        if (!col) return;
        this._sortByColumn(col, th);
      });
    }
  }

  _getSortValue(r, col) {
    let rate = 1380;
    try { if (typeof usdKrw !== 'undefined') rate = usdKrw; } catch {}
    if (typeof window.usdKrw === 'number') rate = window.usdKrw;

    const noRateFields = new Set(['quantity', 'return_rate', 'installment', '_qty', '_rate', '_return', 'sort_order']);

    let valStr = '';
    if (col.compute) {
      valStr = String(col.compute(r) ?? '');
    } else if (col.render) {
      valStr = String(col.render(r[col.key] ?? '', r));
    } else {
      valStr = String(r[col.key] ?? '');
    }

    let text = valStr.replace(/<[^>]+>/g, '').trim();
    if (text === '-' || text === '') return null;

    if (/^\d{4}-\d{2}-\d{2}/.test(text)) {
      return text;
    }

    const hasDollar = text.includes('$');
    const cleanNum = text.replace(/[+,원$%KRW\s]/g, '');

    if (!isNaN(cleanNum) && cleanNum !== '') {
      let num = Number(cleanNum);
      if (hasDollar && !noRateFields.has(col.key)) {
        num = num * rate;
      }
      return num;
    }

    if (col.key && r[col.key] !== undefined && r[col.key] !== null && r[col.key] !== '') {
      return r[col.key];
    }

    return text;
  }

  _performSort(col) {
    this.rows.sort((a, b) => {
      const va = this._getSortValue(a, col);
      const vb = this._getSortValue(b, col);

      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;

      if (typeof va === 'number' && typeof vb === 'number') {
        return this.sortAsc ? va - vb : vb - va;
      }

      const sa = String(va).toLowerCase();
      const sb = String(vb).toLowerCase();
      return this.sortAsc ? sa.localeCompare(sb) : sb.localeCompare(sa);
    });
  }

  _sortByColumn(col, th) {
    if (this.sortKey === col.key) {
      this.sortAsc = !this.sortAsc;
    } else {
      this.sortKey = col.key;
      this.sortAsc = true;
    }

    this._performSort(col);

    const thead = this.tableEl.querySelector('thead');
    if (thead) {
      thead.querySelectorAll('th').forEach(el => {
        const icon = el.querySelector('.sort-icon');
        if (icon) icon.remove();
      });
      const icon = document.createElement('i');
      icon.className = 'sort-icon bi ' + (this.sortAsc ? 'bi-caret-up-fill' : 'bi-caret-down-fill');
      icon.style.marginLeft = '4px';
      icon.style.fontSize = '0.8rem';
      th.appendChild(icon);
    }

    this._renderAll();
  }

  async load() {
    const qs   = this.getQueryParams();
    const data = await fetchJSON(this.apiUrl + (qs ? '?' + qs : ''));
    // {rows, total, ...} 형태와 기존 배열 형태 모두 지원
    if (Array.isArray(data)) {
      this.rows = data;
      this.meta = {};
    } else {
      this.rows = data?.rows || [];
      this.meta = data || {};
    }
    if (this.sortKey) {
      const col = this.columns.find(c => c.key === this.sortKey);
      if (col) this._performSort(col);
    }
    this._renderAll();
    this.onLoad?.(this.rows, this.meta);
  }

  _renderAll() {
    this._tr = null;
    if (this.selectable) this.selected.clear();
    this.tbody.innerHTML = this.rows.length
      ? this.rows.map(r => this._viewHtml(r)).join('')
      : `<tr><td colspan="${this._ncols}" class="text-center text-muted py-4">데이터가 없습니다.</td></tr>`;
    if (this.selectable) this._updateSelectAll();
  }

  _toggleSelect(id, checked) {
    if (checked) this.selected.add(String(id));
    else         this.selected.delete(String(id));
    this._updateSelectAll();
    this.onSelectChange?.(this.selected);
  }

  _updateSelectAll() {
    const cbAll = this.tableEl.querySelector('.cb-all');
    if (!cbAll) return;
    const allIds = this.rows.map(r => String(r.id));
    cbAll.checked = allIds.length > 0 && allIds.every(id => this.selected.has(id));
    cbAll.indeterminate = !cbAll.checked && this.selected.size > 0;
  }

  selectAll(checked) {
    this.rows.forEach(r => {
      const cb = this.tbody.querySelector(`tr[data-id="${r.id}"] .row-cb`);
      if (cb) cb.checked = checked;
      if (checked) this.selected.add(String(r.id));
      else         this.selected.delete(String(r.id));
    });
    this._updateSelectAll();
    this.onSelectChange?.(this.selected);
  }

  _viewHtml(r) {
    const cells = this.columns.map(col => {
      const cls = col.align === 'end' ? ' class="text-end"' : '';
      let content;
      if (col.type === 'computed') {
        content = col.compute(r) ?? '';
      } else {
        const v = r[col.key] ?? '';
        let renderedVal = col.render ? col.render(v, r) : v;
        if (col.type === 'date' && !col.render && v) {
          const parts = String(v).split('-');
          if (parts.length === 3) {
            const y = parseInt(parts[0]);
            const m = parseInt(parts[1]);
            const d = parseInt(parts[2]);
            const dateObj = new Date(y, m - 1, d);
            const weekdays = ['일', '월', '화', '수', '목', '금', '토'];
            const w = weekdays[dateObj.getDay()];
            renderedVal = `${y}년 ${m}월 ${d}일 (${w})`;
          }
        }
        content = renderedVal;
      }
      return `<td${cls}>${content}</td>`;
    });
    cells.push(`<td class="text-center"><button class="btn btn-sm btn-outline-danger py-0" data-ga="d" data-id="${r.id}"><i class="bi bi-trash"></i></button></td>`);
    const cbCell = this.selectable
      ? `<td class="text-center"><input type="checkbox" class="form-check-input row-cb" value="${r.id}"${this.selected.has(String(r.id)) ? ' checked' : ''}></td>`
      : '';
    return `<tr data-id="${r.id}" class="grid-row">${cbCell}${cells.join('')}</tr>`;
  }

  _editInner(r) {
    const cells = this.columns.map(col => {
      if (col.type === 'computed') {
        const cls = col.align === 'end' ? ' class="text-end"' : '';
        return `<td${cls}>${col.compute(r) ?? ''}</td>`;
      }
      const raw = r[col.key] ?? '';
      const v = (col.type === 'date' && raw === '')
        ? new Date().toISOString().split('T')[0]
        : raw;
      let inp;
      if (col.type === 'select') {
        const opts = (typeof col.options === 'function' ? col.options() : col.options || [])
          .map(o => {
            const ov = typeof o === 'object' ? o.value : o;
            const ol = typeof o === 'object' ? o.label : o;
            return `<option value="${ov}"${String(ov) === String(v) ? ' selected' : ''}>${ol}</option>`;
          }).join('');
        inp = `<select class="form-select form-select-sm" data-key="${col.key}"><option value=""></option>${opts}</select>`;
      } else if (col.type === 'number') {
        const fmtd = (v !== '' && v != null && !isNaN(v))
          ? Number(v).toLocaleString('ko-KR') : '';
        inp = `<input type="text" inputmode="decimal" class="form-control form-control-sm" data-key="${col.key}" data-numeric="true" value="${fmtd}">`;
      } else {
        const t = {text:'text', date:'date'}[col.type] || 'text';
        inp = `<input type="${t}" class="form-control form-control-sm" data-key="${col.key}" value="${v}">`;
      }
      return `<td>${inp}</td>`;
    });
    cells.push(`<td class="text-center" style="white-space:nowrap">
      <button class="btn btn-sm btn-success py-0 me-1" data-ga="s"><i class="bi bi-check-lg"></i></button>
      <button class="btn btn-sm btn-outline-secondary py-0" data-ga="c"><i class="bi bi-x-lg"></i></button>
    </td>`);
    const cbCell = this.selectable ? '<td></td>' : '';
    return cbCell + cells.join('');
  }

  startEdit(tr) {
    if (this._tr) this.cancelEdit();
    this._tr = tr;
    const id = tr.dataset.id;
    const r  = id === 'new' ? { id: 'new' } : (this.rows.find(x => String(x.id) === id) || {});
    tr.innerHTML = this._editInner(r);
    tr.classList.add('grid-editing');
    tr.querySelectorAll('input[data-numeric]').forEach(el => {
      el.addEventListener('input', () => {
        const sel  = el.selectionStart;
        const prev = el.value;
        const clean = prev.replace(/[^\d.]/g, '');
        const parts = clean.split('.');
        const intFmt = (parts[0] || '').replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        const next = parts.length > 1 ? intFmt + '.' + parts[1] : intFmt;
        el.value = next;
        try { el.setSelectionRange(sel + next.length - prev.length, sel + next.length - prev.length); } catch {}
      });
    });
    this.onStartEdit?.(tr, r);
    tr.querySelector('input,select')?.focus();
    tr.addEventListener('keydown', this._keyFn = e => {
      if (e.key === 'Enter' && e.target.tagName !== 'SELECT') { e.preventDefault(); this.saveEdit(); }
      if (e.key === 'Escape') this.cancelEdit();
    });
    // 이 클릭 이벤트가 document까지 버블링되어 즉시 cancelEdit 되는 것을 방지
    this._ignoreDocClick = true;
    setTimeout(() => { this._ignoreDocClick = false; }, 0);
  }

  cancelEdit() {
    if (!this._tr) return;
    const tr = this._tr;
    tr.removeEventListener('keydown', this._keyFn);
    this._tr = null;
    if (tr.dataset.id === 'new') {
      tr.remove();
    } else {
      const r = this.rows.find(x => String(x.id) === tr.dataset.id);
      if (r) tr.outerHTML = this._viewHtml(r);
    }
  }

  async saveEdit() {
    if (!this._tr) return;
    const tr = this._tr;
    const id = tr.dataset.id;
    const data = { ...this.getExtraData() };
    tr.querySelectorAll('[data-key]').forEach(el => {
      const col = this.columns.find(c => c.key === el.dataset.key);
      data[el.dataset.key] = col?.type === 'number' ? (parseFloat(el.value.replace(/,/g, '')) || 0) : el.value;
    });
    tr.removeEventListener('keydown', this._keyFn);
    this._tr = null;
    const method = id === 'new' ? 'POST' : 'PUT';
    const url    = id === 'new' ? this.apiUrl : `${this.apiUrl}/${id}`;
    const result = await fetchJSON(url, { method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
    await this.load();
    this.onSave?.(result, method, data);
  }

  async _delete(id) {
    if (this._tr) this.cancelEdit();
    if (this.onBeforeDelete) {
      await this.onBeforeDelete(id, async (mode = 'single') => {
        const url = mode === 'forward'
          ? `${this.apiUrl}/${id}?mode=forward`
          : `${this.apiUrl}/${id}`;
        await fetchJSON(url, { method: 'DELETE' });
        await this.load();
        this.onDelete?.();
      });
      return;
    }
    if (!confirm('삭제하시겠습니까?')) return;
    await fetchJSON(`${this.apiUrl}/${id}`, { method: 'DELETE' });
    await this.load();
    this.onDelete?.();
  }

  addRow() {
    if (this._tr) this.cancelEdit();
    const tr = document.createElement('tr');
    tr.dataset.id = 'new';
    this.tbody.insertBefore(tr, this.tbody.firstChild);
    this.startEdit(tr);
  }
}

// ── Dark Mode ─────────────────────────────────────────────────
async function initDarkMode() {
  // 깜빡임 방지: 로컬에서 즉시 적용 후 DB 확인
  const cached = localStorage.getItem('darkMode');
  if (cached === 'true') applyDarkMode(true, false);

  const res = await fetchJSON('/api/settings/darkMode');
  const on = res?.value === 'true';
  if (String(on) !== cached) localStorage.setItem('darkMode', on);
  applyDarkMode(on, false);
}

async function toggleDarkMode() {
  const on = !document.body.classList.contains('dark-mode');
  localStorage.setItem('darkMode', on);
  applyDarkMode(on, true);
  await fetch('/api/settings/darkMode', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value: String(on) }),
  });
}

function applyDarkMode(on, animate = true) {
  if (!animate) document.body.style.transition = 'none';
  document.body.classList.toggle('dark-mode', on);
  if (!animate) requestAnimationFrame(() => { document.body.style.transition = ''; });

  const icon  = document.getElementById('darkModeIcon');
  const label = document.getElementById('darkModeLabel');
  const btn   = document.getElementById('btnDarkMode');
  if (icon)  icon.className  = on ? 'bi bi-sun' : 'bi bi-moon-stars';
  if (label) label.textContent = on ? '라이트 모드' : '다크 모드';
  if (btn)   btn.title = on ? '라이트 모드로 전환' : '다크 모드로 전환';

  if (typeof Chart !== 'undefined') {
    const textColor = on ? '#FFFFFF' : '#333333';
    const gridColor = on ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';
    Chart.defaults.color = textColor;
    Chart.defaults.borderColor = gridColor;

    Object.values(Chart.instances).forEach(chart => {
      if (chart.options.plugins?.legend?.labels) {
        chart.options.plugins.legend.labels.color = textColor;
      }
      if (chart.options.plugins?.title) {
        chart.options.plugins.title.color = textColor;
      }
      if (chart.options.scales) {
        Object.values(chart.options.scales).forEach(scale => {
          if (scale.ticks) scale.ticks.color = textColor;
          if (scale.grid)  scale.grid.color  = gridColor;
        });
      }
      chart.update();
    });
  }
}

document.addEventListener('DOMContentLoaded', initDarkMode);

/** 년도/월 셀렉트 초기화 */
function initYearMonthFilters(yearId, monthId, defaultYear, defaultMonth) {
  const yearSel  = document.getElementById(yearId);
  const monthSel = document.getElementById(monthId);
  const curYear  = new Date().getFullYear();

  for (let y = curYear; y >= curYear - 5; y--) {
    const opt = document.createElement('option');
    opt.value = y;
    opt.textContent = y + '년';
    if (y === defaultYear) opt.selected = true;
    yearSel.appendChild(opt);
  }

  for (let m = 1; m <= 12; m++) {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m + '월';
    if (m === defaultMonth) opt.selected = true;
    monthSel.appendChild(opt);
  }
}

// 모든 date 타입 인풋에 대해 6자리 연도 입력 방지 및 4자리 자동 탭 브라우저 기능 활성화
document.addEventListener('focusin', function(e) {
  if (e.target && e.target.type === 'date' && !e.target.hasAttribute('max')) {
    e.target.setAttribute('max', '9999-12-31');
  }
});

// ── 사이드바 자동 숨김 / 재표시 ──────────────────────────
(function () {
  const HIDE_DELAY_MS = 3000;   // 3초 후 숨김
  
  let hideTimer   = null;
  let isSidebarHidden = false;
  const sidebar   = document.getElementById('sidebar');
  const body      = document.body;

  if (!sidebar) return;

  // ── 타이머 시작 (5초 후 숨김) ──
  function startHideTimer() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hideSidebar, HIDE_DELAY_MS);
  }

  // ── 타이머 취소 ──
  function cancelHideTimer() {
    clearTimeout(hideTimer);
  }

  // ── 사이드바 숨기기 ──
  function hideSidebar() {
    if (isSidebarHidden) return;
    isSidebarHidden = true;
    sidebar.classList.add('sidebar-hidden');
    body.classList.add('sidebar-hidden');
  }

  // ── 사이드바 표시 ──
  window.showSidebar = function () {
    if (!isSidebarHidden) return;
    isSidebarHidden = false;
    sidebar.classList.remove('sidebar-hidden');
    body.classList.remove('sidebar-hidden');
    startHideTimer();  // 표시 후 다시 타이머 시작
  };

  // ── 타이틀 호버 ──
  window.onTitleHover = function () {
    if (isSidebarHidden) showSidebar();
    else cancelHideTimer();   // 아직 표시 중이면 타이머 취소
  };

  // ── 사이드바에 마우스 진입 시 타이머 리셋 ──
  sidebar.addEventListener('mouseenter', () => {
    cancelHideTimer();
  });

  // ── 사이드바에서 마우스 이탈 시 타이머 재시작 ──
  sidebar.addEventListener('mouseleave', () => {
    startHideTimer();
  });

  // ── 전체 문서 마우스 이동 감지 (사이드바 밖) ──
  document.addEventListener('mousemove', (e) => {
    // 좌하단 타이틀 영역 (x < 80, y > window.innerHeight - 120) → 표시
    if (e.clientX < 80 && e.clientY > window.innerHeight - 120) {
      if (isSidebarHidden) showSidebar();
      return;
    }
    // 사이드바 위에 있는 경우 타이머 리셋 (mouseenter 이벤트 보완)
    const rect = sidebar.getBoundingClientRect();
    if (
      e.clientX >= rect.left && e.clientX <= rect.right &&
      e.clientY >= rect.top  && e.clientY <= rect.bottom
    ) {
      cancelHideTimer();
      return;
    }
    // 그 외 영역에서 마우스가 움직이면 타이머 재시작
    startHideTimer();
  });

  // ── 모바일에서는 비활성화 ──
  if (window.innerWidth < 768) {
    cancelHideTimer();
    return;
  }

  // ── 페이지 로드 시 타이머 시작 ──
  startHideTimer();
})();
