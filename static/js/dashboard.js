/**
 * 대시보드 차트 및 KPI 로직
 */

const COLORS = {
  stocks:     '#dc2626',  // red (crimson)
  etf:        '#f43f5e',  // rose red
  crypto:     '#f59e0b',  // amber
  realestate: '#10b981',  // emerald
  pension:    '#8b5cf6',  // violet
  cash:       '#14b8a6',  // teal
};

// 차트 인스턴스 저장 (재생성 시 destroy 필요)
const _charts = {};

// 투자 수익률 차트 상태
let _returnsMode    = 'cumul';
let _lastReturns    = null;   // 누계용 스냅샷 데이터
let _monthlyData    = null;   // 월별 데이터 (lazy load)

function destroyChart(id) {
  if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
}

// ── 필터 초기화 ──────────────────────────────────────────────
const today = new Date();
initYearMonthFilters('dashYear', 'dashMonth', today.getFullYear(), today.getMonth() + 1);

function getFilter() {
  return {
    year:  document.getElementById('dashYear').value,
    month: document.getElementById('dashMonth').value,
  };
}

function reloadDashboard() {
  const { year, month } = getFilter();
  loadDashboard(year, month);
}

// ── 만료 임박 배너 ───────────────────────────────────────────
async function loadExpiringBanner() {
  const list = await fetchJSON('/api/re-expiring') || [];
  const el   = document.getElementById('dashExpiringBanner');
  if (!el || !list.length) return;
  const today = new Date();
  const formatKoreanDate = (dateStr) => {
    if (!dateStr) return '';
    const parts = dateStr.split('-');
    if (parts.length === 3) {
      const y = parseInt(parts[0]);
      const m = parseInt(parts[1]);
      const d = parseInt(parts[2]);
      const dateObj = new Date(y, m - 1, d);
      const weekdays = ['일', '월', '화', '수', '목', '금', '토'];
      const w = weekdays[dateObj.getDay()];
      return `${y}년 ${m}월 ${d}일 (${w})`;
    }
    return dateStr;
  };
  el.innerHTML = `
    <div class="alert alert-warning border-0 mb-0">
      <div class="fw-semibold mb-2"><i class="bi bi-exclamation-triangle-fill me-2"></i>전세 만료 임박 (3개월 이내)</div>
      ${list.map(c => {
        const days = Math.ceil((new Date(c.end_date) - today) / 86400000);
        const cls  = days <= 30 ? 'text-danger fw-bold' : 'text-warning fw-semibold';
        return `<div class="small">${c.re_name} — <span class="${cls}">${formatKoreanDate(c.end_date)} (${days}일 후)</span>
          &nbsp;${c.contract_type} ${fmt(c.deposit)}원</div>`;
      }).join('')}
    </div>`;
}

// ── 메인 로드 ────────────────────────────────────────────────
async function loadDashboard(year, month) {
  const { year: y, month: m } = (year && month) ? { year, month } : getFilter();
  const isCurrentMonth = (parseInt(y) === today.getFullYear() && parseInt(m) === today.getMonth() + 1);
  const monthLabel = `${y}년 ${parseInt(m)}월`;

  const d = await fetchJSON(`/api/dashboard?year=${y}&month=${m}`);
  if (!d) {
    document.getElementById('dashPaymentBanner').style.display = '';
    document.getElementById('dashPaymentBanner').innerHTML =
      `<div class="alert alert-danger">대시보드 데이터 로딩 실패. 서버 로그를 확인해주세요.</div>`;
    return;
  }
  if (d.error) {
    document.getElementById('dashPaymentBanner').style.display = '';
    document.getElementById('dashPaymentBanner').innerHTML =
      `<div class="alert alert-danger"><strong>오류:</strong> ${d.error}<br><small class="text-muted" style="white-space:pre-wrap">${d.trace||''}</small></div>`;
    return;
  }
  _kpiData = d;
  _assetsDetailed = null; // 월 변경 시 캐시 초기화

  // KPI 레이블 업데이트
  const prefix = isCurrentMonth ? '이번달' : monthLabel;
  document.getElementById('label-income').textContent  = prefix + ' 수입';
  document.getElementById('label-expense').textContent = prefix + ' 지출';
  document.getElementById('label-chart-ie').textContent = prefix;

  // KPI 값
  document.getElementById('kpi-total-assets').textContent = fmt(d.total_assets) + '원';
  document.getElementById('kpi-networth').textContent = fmt(d.net_worth) + '원';
  document.getElementById('kpi-income').textContent   = fmt(d.income_total) + '원';
  document.getElementById('kpi-expense').textContent  = fmt(d.expense_total) + '원';
  document.getElementById('kpi-loans').textContent    = fmt(d.loan_total) + '원';

  // 부동산 거래 진행 중 배너
  renderPaymentAdjBanner(d.payment_adjustments);

  // 차트 재생성
  renderAssetPie(d.asset_breakdown);
  renderIncomeExpenseBar(d.income_by_cat, d.expense_by_cat);
  _lastReturns = d.investment_returns;
  if (_returnsMode === 'cumul') {
    renderReturnsChart(_lastReturns);
  } else {
    // 월별 모드일 때 대시보드 재조회 후에도 월별 차트 유지
    if (_monthlyData) renderReturnsMonthly(_monthlyData);
  }
  renderLoansChart(d.loans);
  renderGoalsProgress(d.goals);
}

function renderPaymentAdjBanner(adj) {
  const el = document.getElementById('dashPaymentBanner');
  if (!el) return;
  if (!adj || (!adj.sell_received && !adj.buy_paid)) {
    el.style.display = 'none';
    return;
  }
  el.style.display = '';
  let parts = [];
  if (adj.sell_received > 0)
    parts.push(`매도 수령 <strong>${fmt(adj.sell_received)}원</strong> → 부동산 자산에서 차감 반영`);
  if (adj.buy_paid > 0)
    parts.push(`매수 지급 <strong>${fmt(adj.buy_paid)}원</strong> → 부동산 자산에 추가 반영`);
  el.innerHTML = `
    <div class="alert alert-warning border-0 py-2 mb-0 d-flex align-items-start gap-2" style="font-size:0.85rem">
      <i class="bi bi-arrow-left-right flex-shrink-0 mt-1"></i>
      <div>
        <span class="fw-semibold">부동산 거래 진행중 자산 조정</span><br>
        ${parts.join('<br>')}
        <a href="/real-estate" class="ms-2 small">거래 단계 보기 →</a>
      </div>
    </div>`;
}

// 페이지 로드 시 배너 바로 표시
loadExpiringBanner();

// ── 차트 렌더러 ──────────────────────────────────────────────
function renderAssetPie(breakdown) {
  destroyChart('chartAssets');
  // 주식+ETF를 하나의 슬라이스로 합산 → 테크트리·투자관리와 동일 기준
  const stocksAndEtf = (breakdown.stocks_and_etf != null)
    ? breakdown.stocks_and_etf
    : (breakdown.stocks || 0) + (breakdown.etf || 0);
  const labels = ['주식+ETF', '코인', '부동산', '연금', '현금/예금'];
  const values = [
    stocksAndEtf, breakdown.crypto,
    breakdown.realestate, breakdown.pension, breakdown.cash,
  ];
  const colors = [COLORS.stocks, COLORS.crypto, COLORS.realestate, COLORS.pension, COLORS.cash];

  _charts['chartAssets'] = new Chart(document.getElementById('chartAssets'), {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors,
        borderWidth: 3,
        borderColor: '#ffffff',
        hoverBorderWidth: 4,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { position: 'bottom', labels: { font: { size: 12 }, padding: 12 } },
        tooltip: {
          callbacks: {
            label: ctx => ' ' + fmt(ctx.raw) + '원 (' +
              (ctx.dataset.data.reduce((a,b)=>a+b,0) ?
                (ctx.raw / ctx.dataset.data.reduce((a,b)=>a+b,0) * 100).toFixed(1) : 0) + '%)'
          }
        }
      }
    }
  });
}

function renderIncomeExpenseBar(incomeCats, expenseCats) {
  destroyChart('chartIncomeExpense');
  const incMap = {};
  incomeCats.forEach(r => { incMap[r.category || '기타'] = r.total; });
  const expMap = {};
  expenseCats.forEach(r => { expMap[r.category || '기타'] = r.total; });

  const labels = [...new Set([...Object.keys(incMap), ...Object.keys(expMap)])];

  _charts['chartIncomeExpense'] = new Chart(document.getElementById('chartIncomeExpense'), {
    type: 'bar',
    data: {
      labels: labels.length ? labels : ['데이터 없음'],
      datasets: [
        {
          label: '수입',
          data: labels.map(l => incMap[l] || 0),
          backgroundColor: 'rgba(25,135,84,0.75)',
          borderRadius: 4,
        },
        {
          label: '지출',
          data: labels.map(l => expMap[l] || 0),
          backgroundColor: 'rgba(220,53,69,0.75)',
          borderRadius: 4,
        }
      ]
    },
    options: {
      responsive: true,
      plugins: { legend: { position: 'top' } },
      scales: {
        y: { ticks: { callback: v => (v / 10000).toFixed(0) + '만' } }
      }
    }
  });
}

function renderReturnsChart(returns) {
  destroyChart('chartReturns');
  // 주식+ETF 합산 수익률 (테크트리와 동일 기준)
  const stocksEtfCombined = {
    cost:  (returns.stocks?.cost  || 0) + (returns.etf?.cost  || 0),
    value: (returns.stocks?.value || 0) + (returns.etf?.value || 0),
  };
  const labels = ['주식+ETF', '코인'];
  const pcts = [
    calcReturn(stocksEtfCombined),
    calcReturn(returns.crypto),
  ];

  _charts['chartReturns'] = new Chart(document.getElementById('chartReturns'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '수익률 (%)',
        data: pcts,
        backgroundColor: pcts.map(v => v >= 0 ? 'rgba(220,53,69,0.75)' : 'rgba(13,110,253,0.75)'),
        borderRadius: 4,
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        y: {
          ticks: { callback: v => v + '%' },
          grid: { color: '#f0f0f0' }
        }
      }
    }
  });
}

function calcReturn(inv) {
  if (!inv || !inv.cost) return 0;
  return parseFloat(((inv.value - inv.cost) / inv.cost * 100).toFixed(2));
}

async function setReturnsMode(mode) {
  _returnsMode = mode;
  document.getElementById('btnReturnsCumul').classList.toggle('active', mode === 'cumul');
  document.getElementById('btnReturnsMonthly').classList.toggle('active', mode === 'monthly');

  if (mode === 'monthly') {
    if (!_monthlyData) _monthlyData = await fetchJSON('/api/investment-monthly');
    renderReturnsMonthly(_monthlyData);
  } else {
    if (_lastReturns) renderReturnsChart(_lastReturns);
  }
}

function renderReturnsMonthly(data) {
  destroyChart('chartReturns');
  const labels = data.map(d => {
    const [y, m] = d.ym.split('-');
    return `${y.slice(2)}년 ${parseInt(m)}월`;
  });
  const pnls = data.map(d => d.realized_pnl);

  _charts['chartReturns'] = new Chart(document.getElementById('chartReturns'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '실현손익 (원)',
        data: pnls,
        backgroundColor: pnls.map(v => v > 0 ? 'rgba(220,53,69,0.75)' : v < 0 ? 'rgba(13,110,253,0.75)' : 'rgba(160,160,160,0.3)'),
        borderRadius: 4,
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => ` 실현손익: ${fmt(ctx.raw)}원`
          }
        }
      },
      scales: {
        x: { grid: { display: false } },
        y: {
          ticks: { callback: v => (v / 10000).toFixed(0) + '만' },
          grid:  { color: '#f0f0f0' },
        },
      },
    }
  });
}

function renderLoansChart(loans) {
  destroyChart('chartLoans');
  const el = document.getElementById('chartLoans');
  if (!loans || !loans.length) {
    el.closest('.card-body').innerHTML =
      '<p class="text-center text-muted py-4">대출 데이터가 없습니다.</p>';
    return;
  }

  _charts['chartLoans'] = new Chart(el, {
    type: 'bar',
    data: {
      labels: loans.map(l => l.name),
      datasets: [{
        label: '잔액',
        data: loans.map(l => l.remaining),
        backgroundColor: 'rgba(255,165,0,0.75)',
        borderRadius: 4,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { callback: v => (v / 10000000).toFixed(0) + '천만' } }
      }
    }
  });
}

function renderGoalsProgress(goals) {
  const el = document.getElementById('goals-progress');
  if (!goals || !goals.length) {
    el.innerHTML = '<p class="text-center text-muted">목표 자산 데이터가 없습니다.</p>';
    return;
  }
  el.innerHTML = goals.map(g => {
    const pct = g.target_amount ? Math.min(100, Math.round(g.current_amount / g.target_amount * 100)) : 0;
    const barClass = pct >= 100 ? 'bg-success' : pct >= 70 ? 'bg-warning' : 'bg-primary';
    return `
    <div class="mb-3">
      <div class="d-flex justify-content-between mb-1">
        <span class="fw-semibold">${g.name}</span>
        <span class="text-muted small amt">${fmt(g.current_amount)}원 / ${fmt(g.target_amount)}원 (${pct}%)</span>
      </div>
      <div class="progress" style="height:12px">
        <div class="progress-bar ${barClass}" style="width:${pct}%" role="progressbar"></div>
      </div>
    </div>`;
  }).join('');
}

// ── 프라이빗 모드 ─────────────────────────────────────────────
async function initPrivacyMode() {
  // 깜빡임 방지: 로컬에서 즉시 동기식으로 적용
  const cached = localStorage.getItem('privacyMode');
  if (cached === 'true') applyPrivacyMode(true);

  const res = await fetchJSON('/api/settings/privacyMode');
  const on = res?.value === 'true';
  if (String(on) !== cached) {
    localStorage.setItem('privacyMode', on);
    applyPrivacyMode(on);
  }
}

async function togglePrivacy() {
  const on = !document.body.classList.contains('privacy-mode');
  localStorage.setItem('privacyMode', on);
  applyPrivacyMode(on);
  await fetch('/api/settings/privacyMode', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value: String(on) }),
  });
}

function applyPrivacyMode(on) {
  document.body.classList.toggle('privacy-mode', on);
  document.querySelectorAll('.amt.reveal').forEach(el => el.classList.remove('reveal'));
  const btn   = document.getElementById('btnPrivacy');
  const icon  = document.getElementById('privacyIcon');
  const label = document.getElementById('privacyLabel');
  if (on) {
    btn.classList.add('active');
    icon.className  = 'bi bi-eye-slash-fill';
    label.textContent = '프라이빗 ON';
  } else {
    btn.classList.remove('active');
    icon.className  = 'bi bi-eye-slash';
    label.textContent = '프라이빗';
  }
}

// 프라이빗 모드에서 마우스 클릭 시 금액 보이기/숨기기 토글
document.addEventListener('click', e => {
  if (document.body.classList.contains('privacy-mode')) {
    const amtEl = e.target.closest('.amt');
    if (amtEl) {
      amtEl.classList.toggle('reveal');
      e.stopPropagation();
    }
  }
});

// ── KPI 상세 팝업 ─────────────────────────────────────────────
let _kpiData = null;       // 마지막 dashboard API 응답
let _assetsDetailed = null; // assets-detailed 캐시

const _catColors = {
  '주식':      '#dc2626',
  'ETF':       '#f43f5e',
  '주식+ETF':  '#dc2626',
  '코인':      '#f59e0b',
  '부동산':    '#10b981',
  '연금':      '#8b5cf6',
  '현금/예금': '#14b8a6',
};

async function openKpiDetail(type) {
  const modal = new bootstrap.Modal(document.getElementById('kpiDetailModal'));
  const title = document.getElementById('kpiDetailTitle');
  const body  = document.getElementById('kpiDetailBody');

  body.innerHTML = '<div class="text-center py-4"><div class="spinner-border spinner-border-sm text-primary"></div></div>';
  modal.show();

  if (type === 'loans') {
    title.textContent = '대출 상세 내역';
    body.innerHTML = renderLoansDetail(_kpiData?.loans || []);
    return;
  }

  // 총자산 / 순자산은 assets-detailed 필요
  if (!_assetsDetailed) {
    _assetsDetailed = await fetchJSON('/api/assets-detailed');
  }
  if (!_assetsDetailed || _assetsDetailed.error) {
    body.innerHTML = '<p class="text-danger text-center py-3">데이터를 불러올 수 없습니다.</p>';
    return;
  }

  if (type === 'assets') {
    title.textContent = '총자산 상세 내역';
    body.innerHTML = renderAssetsDetail(_assetsDetailed);
  } else if (type === 'networth') {
    title.textContent = '순자산 상세 내역';
    body.innerHTML = renderNetworthDetail(_assetsDetailed, _kpiData?.loans || []);
  }
}

function renderAssetsDetail(data) {
  let html = '';
  let grandTotal = 0;

  for (const [cat, items] of Object.entries(data)) {
    if (cat.startsWith('_')) continue; // 내부 메타 키 제외
    const catTotal = items.reduce((s, i) => s + i.val, 0);
    if (catTotal === 0 && items.length === 0) continue;
    grandTotal += catTotal;
    const color = _catColors[cat] || '#888';

    html += `<div class="kpi-cat-header" style="border-color:${color}; color:${color}">${cat} <span style="color:#888;font-weight:400">${fmt(catTotal)}원</span></div>`;
    if (items.length === 0) {
      html += `<div class="kpi-row"><span class="text-muted">항목 없음</span><span>-</span></div>`;
    } else {
      items.forEach(item => {
        html += `<div class="kpi-row"><span>${item.name}</span><span class="fw-semibold">${fmt(item.val)}원</span></div>`;
      });
    }
  }

  html += `<div class="kpi-total-row"><span>총자산 합계</span><span>${fmt(grandTotal)}원</span></div>`;
  return html;
}

function renderNetworthDetail(data, loans) {
  let totalAssets = 0;
  let html = '<div class="kpi-cat-header" style="border-color:#0d6efd;color:#0d6efd">자산</div>';

  for (const [cat, items] of Object.entries(data)) {
    if (cat.startsWith('_')) continue;
    const catTotal = items.reduce((s, i) => s + i.val, 0);
    if (catTotal === 0) continue;
    totalAssets += catTotal;
    html += `<div class="kpi-row"><span>${cat}</span><span class="fw-semibold text-success">+${fmt(catTotal)}원</span></div>`;
  }

  const totalLoans = loans.reduce((s, l) => s + (l.remaining || 0), 0);
  const tenantDeposits = data['_tenant_deposits'] || [];
  const totalTenantDeposit = tenantDeposits.reduce((s, d) => s + d.val, 0);
  const totalDeductions = totalLoans + totalTenantDeposit;

  if (totalLoans > 0 || totalTenantDeposit > 0) {
    html += `<div class="kpi-cat-header" style="border-color:#dc3545;color:#dc3545">차감 항목</div>`;
    loans.forEach(l => {
      if ((l.remaining || 0) > 0)
        html += `<div class="kpi-row"><span><span class="badge bg-danger-subtle text-danger me-1" style="font-size:10px">대출</span>${l.name}</span><span class="fw-semibold text-danger">-${fmt(l.remaining)}원</span></div>`;
    });
    tenantDeposits.forEach(d => {
      html += `<div class="kpi-row"><span><span class="badge bg-warning-subtle text-warning me-1" style="font-size:10px">보증금</span>${d.name}</span><span class="fw-semibold text-warning">-${fmt(d.val)}원</span></div>`;
    });
  }

  const netWorth = totalAssets - totalDeductions;
  html += `
    <div class="kpi-total-row"><span>총자산</span><span class="text-success">${fmt(totalAssets)}원</span></div>
    <div class="kpi-row text-muted" style="font-size:13px"><span>대출</span><span>-${fmt(totalLoans)}원</span></div>
    <div class="kpi-row text-muted" style="font-size:13px"><span>세입자 보증금 (사적 레버리지)</span><span>-${fmt(totalTenantDeposit)}원</span></div>
    <div class="kpi-total-row" style="font-size:18px"><span>순자산</span><span class="${netWorth >= 0 ? 'text-primary' : 'text-danger'}">${fmt(netWorth)}원</span></div>`;
  return html;
}

function renderLoansDetail(loans) {
  if (!loans || loans.length === 0) {
    return '<p class="text-center text-muted py-4">대출 항목이 없습니다.</p>';
  }
  let html = '';
  let total = 0;
  loans.forEach(l => {
    total += l.remaining || 0;
    html += `
    <div class="card border-0 bg-light mb-2 px-3 py-2">
      <div class="d-flex justify-content-between align-items-center">
        <span class="fw-semibold">${l.name}</span>
        <span class="fw-bold text-warning">${fmt(l.remaining)}원</span>
      </div>
      <div class="d-flex gap-3 mt-1" style="font-size:12px;color:#888">
        ${l.institution ? `<span><i class="bi bi-building me-1"></i>${l.institution}</span>` : ''}
        ${l.interest_rate ? `<span><i class="bi bi-percent me-1"></i>${l.interest_rate}%</span>` : ''}
        ${l.monthly_payment ? `<span><i class="bi bi-calendar-month me-1"></i>월 ${fmt(l.monthly_payment)}원</span>` : ''}
      </div>
    </div>`;
  });
  html += `<div class="kpi-total-row"><span>총 대출잔액</span><span class="text-warning">${fmt(total)}원</span></div>`;
  return html;
}

// ── 순자산 변화 차트 ──────────────────────────────────────
let networthChart = null;

function initNetworthChart() {
  document.querySelectorAll('#period-tabs button').forEach(btn => {
    btn.addEventListener('click', function () {
      document.querySelectorAll('#period-tabs button')
        .forEach(b => b.classList.remove('active'));
      this.classList.add('active');
      loadNetworthChart(this.dataset.period);
    });
  });
}

function formatKRW(val) {
  if (val === null || val === undefined) return '-';
  return fmt(val) + '원';
}

function formatKRWMobile(val) {
  if (val === null || val === undefined) return '-';
  const sign = val < 0 ? '-' : '';
  const abs = Math.abs(val);
  if (abs >= 100000000) {
    const v = abs / 100000000;
    return sign + (v % 1 === 0 ? v : v.toFixed(1)) + '억';
  }
  if (abs >= 10000) return sign + Math.round(abs / 10000) + '만';
  return sign + fmt(abs);
}

async function loadNetworthChart(period) {
  // 요약 수치 업데이트
  const res  = await fetch('/api/networth-history?period=' + period);
  const data = await res.json();
  const rows = data.rows || [];
  const s    = data.summary || {};

  const curEl    = document.getElementById('nw-current');
  const changeEl = document.getElementById('nw-change-amt');
  const pctEl    = document.getElementById('nw-change-pct');
  if (curEl)    curEl.textContent  = formatKRW(s.current);
  if (changeEl) {
    changeEl.textContent = (s.change_amt >= 0 ? '+' : '') + formatKRW(s.change_amt);
    changeEl.style.color = s.change_amt >= 0 ? '#2ecc71' : '#e74c3c';
  }
  if (pctEl) {
    pctEl.textContent = (s.change_pct >= 0 ? '+' : '') + (s.change_pct || 0) + '%';
    pctEl.style.color = s.change_pct >= 0 ? '#2ecc71' : '#e74c3c';
  }

  // 데이터 없으면 wrap에 메시지 표시
  const wrap = document.getElementById('networth-chart-wrap');
  if (!rows.length) {
    wrap.innerHTML = '<p class="text-center text-muted py-5">저장된 데이터가 없습니다.</p>';
    networthChart = null;
    return;
  }

  // wrap에 canvas가 없으면 새로 추가
  if (!document.getElementById('networth-chart')) {
    wrap.innerHTML = '<canvas id="networth-chart"></canvas>';
  }

  const isMobile  = window.innerWidth < 768;
  wrap.style.height = isMobile ? '250px' : '300px';

  const labels    = rows.map(r => r.label);
  const netWorth  = rows.map(r => r.net_worth  || 0);
  const changePct = rows.map(r => r.change_pct || 0);
  const barLabels = { daily: '일간 변동률(%)', weekly: '주간 변동률(%)', monthly: '월간 변동률(%)', yearly: '연간 변동률(%)' };

  if (networthChart) { networthChart.destroy(); networthChart = null; }
  document.getElementById('nw-detail-panel').style.display = 'none';
  var _rows = rows; // closure for click handler

  networthChart = new Chart(document.getElementById('networth-chart'), {
    data: {
      labels,
      datasets: [
        {
          type: 'line',
          label: '순자산',
          data: netWorth,
          borderColor: '#3498db',
          backgroundColor: 'rgba(52,152,219,0.07)',
          fill: true,
          tension: 0.3,
          yAxisID: 'y',
          pointRadius: period === 'daily' ? 2 : (isMobile ? 3 : 4),
          pointHoverRadius: 6,
          order: 1,
        },
        {
          type: 'bar',
          label: barLabels[period] || '변동률(%)',
          data: changePct,
          backgroundColor: changePct.map(v => v >= 0 ? 'rgba(46,204,113,0.55)' : 'rgba(231,76,60,0.55)'),
          borderColor:     changePct.map(v => v >= 0 ? '#2ecc71' : '#e74c3c'),
          borderWidth: 1,
          yAxisID: 'y1',
          order: 2,
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          position: 'top',
          labels: {
            font: { size: isMobile ? 11 : 12 },
            boxWidth: isMobile ? 10 : 12,
            padding: isMobile ? 8 : 10,
          }
        },
        tooltip: {
          callbacks: {
            label: function(ctx) {
              if (ctx.dataset.yAxisID === 'y') return '순자산: ' + formatKRW(ctx.raw);
              var sign = ctx.raw >= 0 ? '+' : '';
              return '변동률: ' + sign + Number(ctx.raw).toFixed(2) + '%';
            }
          }
        }
      },
      scales: {
        x: {
          ticks: {
            maxRotation: isMobile ? 30 : 45,
            maxTicksLimit: isMobile ? 6 : undefined,
            font: { size: isMobile ? 9 : 11 },
            callback: function(val, idx) { return labels[idx]; }
          }
        },
        y: {
          type: 'linear', position: 'left',
          ticks: {
            callback: function(v) { return isMobile ? formatKRWMobile(v) : formatKRW(v); },
            font: { size: isMobile ? 9 : 11 },
            maxTicksLimit: isMobile ? 5 : 8,
          },
          title: { display: !isMobile, text: '순자산 (원)' },
          afterFit: function(scale) {
            scale.width = isMobile ? 52 : 90;
          }
        },
        y1: {
          type: 'linear', position: 'right',
          grid: { drawOnChartArea: false },
          ticks: {
            callback: function(v) { return v.toFixed(1) + '%'; },
            font: { size: isMobile ? 9 : 11 },
            maxTicksLimit: isMobile ? 5 : 8,
          },
          title: { display: !isMobile, text: '변동률 (%)' }
        }
      }
    }
  });

  // canvas 클릭으로 가장 가까운 x 인덱스 찾아 상세 표시
  document.getElementById('networth-chart').onclick = function(evt) {
    var points = networthChart.getElementsAtEventForMode(evt, 'index', { intersect: false }, false);
    if (!points.length) return;
    showAssetDetail(_rows[points[0].index]);
  };
}

function showAssetDetail(row) {
  var panel = document.getElementById('nw-detail-panel');
  var labelEl = document.getElementById('nw-detail-label');
  var rowsEl  = document.getElementById('nw-detail-rows');

  labelEl.textContent = row.label + ' 자산 변동 내역';

  var assets = [
    { name: '주식·ETF', key: 'stocks',       icon: '📈' },
    { name: '현금',     key: 'cash',          icon: '💵' },
    { name: '부동산',   key: 'real_estate',   icon: '🏠' },
    { name: '코인',     key: 'crypto',        icon: '🪙' },
    { name: '연금',     key: 'pension',       icon: '🏦' },
  ];

  rowsEl.innerHTML = assets.map(function(a) {
    var cur  = row[a.key] || 0;
    var prev = row['prev_' + a.key] || 0;
    var diff = cur - prev;
    var color = diff > 0 ? '#2ecc71' : diff < 0 ? '#e74c3c' : '#aaa';
    var sign  = diff > 0 ? '+' : '';
    return '<div class="col-6 col-md-4 col-lg-2">' +
      '<div class="border rounded p-2 text-center" style="font-size:0.82rem">' +
        '<div class="mb-1">' + a.icon + ' ' + a.name + '</div>' +
        '<div class="fw-semibold">' + formatKRW(cur) + '</div>' +
        '<div style="color:' + color + ';font-size:0.78rem">' + sign + formatKRW(diff) + '</div>' +
      '</div>' +
    '</div>';
  }).join('');

  panel.style.display = '';
}

// ── 자정 직전 자동 스냅샷 저장 ────────────────────────────
function scheduleMidnightSnapshot() {
  const now = new Date();
  const target = new Date(now);
  target.setHours(23, 59, 30, 0);
  if (now >= target) {
    // 이미 23:59:30 지남 → 내일 자정 직전으로
    target.setDate(target.getDate() + 1);
  }
  const msUntil = target - now;
  setTimeout(async () => {
    try {
      await fetch('/api/dashboard');
      console.log('자정 스냅샷 저장 완료');
    } catch (e) {
      console.warn('자정 스냅샷 저장 실패:', e);
    }
    scheduleMidnightSnapshot(); // 다음 날 재예약
  }, msUntil);
}

// 페이지 로드 시 실행
initPrivacyMode();
loadDashboard();
initNetworthChart();
loadNetworthChart('monthly');
scheduleMidnightSnapshot();

