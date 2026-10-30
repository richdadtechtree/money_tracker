/**
 * 계좌 간 이체 창 — 현금관리 / 투자 관리 공용
 *
 * openTransferModal({ from: 'bank:3' | 'invest:2', to: 'invest:2', currency: 'KRW' | 'USD' })
 *   - 출금/입금 대상: 현금관리 통장(bank) 또는 투자 계좌(invest). 통장끼리는 이체할 수 없다.
 *   - 이체가 끝나면 window.onTransferDone() 이 있으면 호출한다 (각 페이지가 표/잔액을 새로 그린다).
 * 창은 처음 열 때 한 번만 만들어 body 에 붙인다.
 */
(function () {
  const MODAL_ID = 'transferModal';
  let banks = [];    // 현금관리 통장 (예수금 잠금 행 제외)
  let accts = [];    // 사용 중인 투자 계좌

  const $ = id => document.getElementById(id);
  const usdText = v => (v < 0 ? '-$' : '$') + Math.abs(Number(v || 0)).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const krwText = v => Math.round(Number(v || 0)).toLocaleString('ko-KR') + '원';
  const money = (v, cur) => (cur === 'USD' ? usdText(v) : krwText(v));

  function ensureModal() {
    if ($(MODAL_ID)) return;
    document.body.insertAdjacentHTML('beforeend', `
<div class="modal fade" id="${MODAL_ID}" tabindex="-1">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title"><i class="bi bi-arrow-left-right me-2"></i>계좌 간 이체</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <div class="row g-2">
          <div class="col-12"><label class="form-label small mb-1">출금</label>
            <select class="form-select form-select-sm" id="trFrom"></select></div>
          <div class="col-12 text-center text-muted small"><i class="bi bi-arrow-down"></i>
            <button type="button" class="btn btn-link btn-sm py-0" id="trSwap">출금/입금 바꾸기</button></div>
          <div class="col-12"><label class="form-label small mb-1">입금</label>
            <select class="form-select form-select-sm" id="trTo"></select></div>
          <div class="col-4"><label class="form-label small mb-1">통화</label>
            <select class="form-select form-select-sm" id="trCurrency">
              <option value="KRW">원화</option><option value="USD">달러</option></select></div>
          <div class="col-8"><label class="form-label small mb-1">금액</label>
            <input type="text" inputmode="decimal" class="form-control form-control-sm" id="trAmount" placeholder="0"></div>
          <div class="col-6"><label class="form-label small mb-1">날짜</label>
            <input type="date" class="form-control form-control-sm" id="trDate"></div>
          <div class="col-6"><label class="form-label small mb-1">메모</label>
            <input type="text" class="form-control form-control-sm" id="trMemo"></div>
        </div>
        <div class="small fw-semibold mt-2" id="trPreview"></div>
        <div class="small text-muted mt-1">출금 통장의 잔액이 줄고 입금 계좌의 예수금이 같은 금액만큼 늘어납니다.
          잘못 입력했다면 이체 내역에서 삭제하면 양쪽이 원래대로 돌아갑니다.</div>
      </div>
      <div class="modal-footer"><button class="btn btn-primary btn-sm" id="trSave">이체</button></div>
    </div>
  </div>
</div>`);
    $('trCurrency').addEventListener('change', () => renderOptions());   // 이벤트 객체를 keep 인자로 넘기면 선택이 초기화되므로 인자 없이 호출
    ['trFrom', 'trTo'].forEach(id => $(id).addEventListener('change', updatePreview));
    $('trAmount').addEventListener('input', updatePreview);
    $('trSwap').addEventListener('click', () => {
      const f = $('trFrom').value; $('trFrom').value = $('trTo').value; $('trTo').value = f; updatePreview();
    });
    $('trSave').addEventListener('click', save);
  }

  /** 출금/입금 선택지를 현재 통화 기준 잔액과 함께 다시 그린다 (선택 값은 유지) */
  function renderOptions(keep) {
    const cur = $('trCurrency').value;
    const opts = () =>
      `<optgroup label="현금관리 통장">${banks.map(b =>
        `<option value="bank:${b.id}">${b.name} (${money(cur === 'USD' ? b.usd_amount : b.krw_amount, cur)})</option>`).join('')}</optgroup>` +
      `<optgroup label="투자 계좌 (예수금)">${accts.map(a =>
        `<option value="invest:${a.id}">${a.name} (${money(cur === 'USD' ? a.cash_usd : a.cash_krw, cur)})</option>`).join('')}</optgroup>`;
    ['trFrom', 'trTo'].forEach(id => {
      const sel = $(id), prev = keep ? keep[id] : sel.value;
      sel.innerHTML = opts();
      if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
    });
    updatePreview();
  }

  function labelOf(val) {
    const o = [...$('trFrom').options].find(x => x.value === val);
    return o ? o.textContent.replace(/\s*\(.*\)$/, '') : '';
  }

  function updatePreview() {
    const amt = parseFloat(($('trAmount').value || '').replace(/,/g, '')) || 0;
    $('trPreview').textContent = amt
      ? `${labelOf($('trFrom').value)} → ${labelOf($('trTo').value)} : ${money(amt, $('trCurrency').value)}` : '';
  }

  async function save() {
    const [ft, fid] = $('trFrom').value.split(':');
    const [tt, tid] = $('trTo').value.split(':');
    const body = {
      from_type: ft, from_id: fid, to_type: tt, to_id: tid, currency: $('trCurrency').value,
      amount: ($('trAmount').value || '').replace(/,/g, ''), tx_date: $('trDate').value, memo: $('trMemo').value,
    };
    $('trSave').disabled = true;
    try {
      const res = await fetchJSON('/api/account-transfers',
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (res === null) { alert(fetchJSON.lastError || '이체하지 못했습니다.'); return; }
      bootstrap.Modal.getOrCreateInstance($(MODAL_ID)).hide();
      if (res.warning) alert(res.warning);
      if (typeof window.onTransferDone === 'function') window.onTransferDone();
    } finally {
      $('trSave').disabled = false;
    }
  }

  window.openTransferModal = async function (opts) {
    opts = opts || {};
    ensureModal();
    const [b, a] = await Promise.all([fetchJSON('/api/cash-deposits'), fetchJSON('/api/invest-accounts')]);
    banks = (b || []).filter(r => !r.is_system);
    accts = (a || []).filter(x => x.is_active);
    if (!accts.length) { alert('이체할 투자 계좌가 없습니다. 투자 관리에서 [계좌 관리]로 계좌를 먼저 등록해 주세요.'); return; }
    $('trCurrency').value = opts.currency || 'KRW';
    // 기본값: 출금은 첫 통장, 입금은 지정한 계좌(없으면 첫 투자 계좌)
    const defFrom = opts.from || (banks.length ? `bank:${banks[0].id}` : `invest:${accts[0].id}`);
    let defTo = opts.to || `invest:${accts[0].id}`;
    if (defTo === defFrom) defTo = accts.map(x => `invest:${x.id}`).find(v => v !== defFrom) || defTo;
    renderOptions({ trFrom: defFrom, trTo: defTo });
    $('trFrom').value = [...$('trFrom').options].some(o => o.value === defFrom) ? defFrom : $('trFrom').value;
    $('trTo').value = [...$('trTo').options].some(o => o.value === defTo) ? defTo : $('trTo').value;
    $('trAmount').value = '';
    $('trMemo').value = '';
    $('trDate').value = todayLocalStr();
    updatePreview();
    bootstrap.Modal.getOrCreateInstance($(MODAL_ID)).show();
  };
})();
