/**
 * 대시보드 차트 및 KPI 로직
 */

const COLORS = {
  stocks:     '#1565C0',
  etf:        '#1976D2',
  crypto:     '#F57F17',
  realestate: '#2E7D32',
  pension:    '#6A1B9A',
  cash:       '#00838F',
};

// 차트 인스턴스 저장 (재생성 시 destroy 필요)
const _charts = {};

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
  el.innerHTML = `
    <div class="alert alert-warning border-0 mb-0">
      <div class="fw-semibold mb-2"><i class="bi bi-exclamation-triangle-fill me-2"></i>전세 만료 임박 (3개월 이내)</div>
      ${list.map(c => {
        const days = Math.ceil((new Date(c.end_date) - today) / 86400000);
        const cls  = days <= 30 ? 'text-danger fw-bold' : 'text-warning fw-semibold';
        return `<div class="small">${c.re_name} — <span class="${cls}">${c.end_date} (${days}일 후)</span>
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

  // KPI 레이블 업데이트
  const prefix = isCurrentMonth ? '이번달' : monthLabel;
  document.getElementById('label-income').textContent  = prefix + ' 수입';
  document.getElementById('label-expense').textContent = prefix + ' 지출';
  document.getElementById('label-chart-ie').textContent = prefix;

  // KPI 값
  document.getElementById('kpi-networth').textContent = fmt(d.net_worth) + '원';
  document.getElementById('kpi-income').textContent   = fmt(d.income_total) + '원';
  document.getElementById('kpi-expense').textContent  = fmt(d.expense_total) + '원';
  document.getElementById('kpi-loans').textContent    = fmt(d.loan_total) + '원';

  // 차트 재생성
  renderAssetPie(d.asset_breakdown);
  renderIncomeExpenseBar(d.income_by_cat, d.expense_by_cat);
  renderReturnsChart(d.investment_returns);
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
        borderWidth: 2,
        borderColor: '#fff',
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
    el.innerHTML = '<p class="text-center text-muted">목표저축 데이터가 없습니다.</p>';
    return;
  }
  el.innerHTML = goals.map(g => {
    const pct = g.target_amount ? Math.min(100, Math.round(g.current_amount / g.target_amount * 100)) : 0;
    const barClass = pct >= 100 ? 'bg-success' : pct >= 70 ? 'bg-warning' : 'bg-primary';
    return `
    <div class="mb-3">
      <div class="d-flex justify-content-between mb-1">
        <span class="fw-semibold">${g.name}</span>
        <span class="text-muted small">${fmt(g.current_amount)}원 / ${fmt(g.target_amount)}원 (${pct}%)</span>
      </div>
      <div class="progress" style="height:12px">
        <div class="progress-bar ${barClass}" style="width:${pct}%" role="progressbar"></div>
      </div>
    </div>`;
  }).join('');
}

// 페이지 로드 시 실행
loadDashboard();
