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
  if (!d) return;
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

// 페이지 로드 시 배너 바로 표시
loadExpiringBanner();

// ── 차트 렌더러 ──────────────────────────────────────────────
function renderAssetPie(breakdown) {
  destroyChart('chartAssets');
  const labels = ['주식', 'ETF', '코인', '부동산', '연금', '현금/예금'];
  const values = [
    breakdown.stocks, breakdown.etf, breakdown.crypto,
    breakdown.realestate, breakdown.pension, breakdown.cash,
  ];
  const colors = Object.values(COLORS);

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
  const labels = ['주식', 'ETF', '코인'];
  const pcts = [
    calcReturn(returns.stocks),
    calcReturn(returns.etf),
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
  const res = await fetchJSON('/api/settings/privacyMode');
  applyPrivacyMode(res?.value === 'true');
}

async function togglePrivacy() {
  const on = !document.body.classList.contains('privacy-mode');
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
  '주식':    '#dc2626',
  'ETF':     '#f43f5e',
  '코인':    '#f59e0b',
  '부동산':  '#10b981',
  '연금':    '#8b5cf6',
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
    const catTotal = items.reduce((s, i) => s + i.val, 0);
    if (catTotal === 0) continue;
    totalAssets += catTotal;
    html += `<div class="kpi-row"><span>${cat}</span><span class="fw-semibold text-success">+${fmt(catTotal)}원</span></div>`;
  }

  const totalLoans = loans.reduce((s, l) => s + (l.remaining || 0), 0);
  if (totalLoans > 0) {
    html += `<div class="kpi-cat-header" style="border-color:#dc3545;color:#dc3545">대출 (차감)</div>`;
    loans.forEach(l => {
      if ((l.remaining || 0) > 0) {
        html += `<div class="kpi-row"><span>${l.name}</span><span class="fw-semibold text-danger">-${fmt(l.remaining)}원</span></div>`;
      }
    });
  }

  const netWorth = totalAssets - totalLoans;
  html += `
    <div class="kpi-total-row"><span>총자산</span><span class="text-success">${fmt(totalAssets)}원</span></div>
    <div class="kpi-row"><span class="text-muted">총대출</span><span class="text-danger">-${fmt(totalLoans)}원</span></div>
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

// 페이지 로드 시 실행
initPrivacyMode();
loadDashboard();
