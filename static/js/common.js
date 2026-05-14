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
    const r  = id === 'new' ? {} : (this.rows.find(x => String(x.id) === id) || {});
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
