/**
 * 가용자산 계산기 전용 스크립트
 */

let _calcItems = [];
let _allAssets = null;

async function loadAssets() {
  const data = await fetchJSON('/api/assets-detailed');
  if (!data) {
    alert('데이터를 불러오는 데 실패했습니다. 서버 상태를 확인해주세요.');
    return;
  }
  if (data.error) {
    console.error('API Error:', data.error, data.trace);
    alert('데이터 오류: ' + data.error);
    return;
  }
  _allAssets = data;
  renderAssetTree();
}

function renderAssetTree() {
  const treeEl = document.getElementById('asset-tree');
  if (!treeEl) return;

  let html = '';
  let index = 0;

  for (const [cat, items] of Object.entries(_allAssets)) {
    if (cat.startsWith('_')) continue;

    // 부동산은 보증금 차감한 net_val 사용
    const isRE = (cat === '부동산');
    const getVal = item => isRE ? (item.net_val ?? item.val) : item.val;

    const total = items.reduce((s, i) => s + getVal(i), 0);
    const catId = `cat-${index++}`;

    html += `
    <div class="accordion-item border-0 mb-2 shadow-sm rounded overflow-hidden">
      <h2 class="accordion-header">
        <div class="d-flex align-items-center bg-white pe-3">
          <button class="accordion-button collapsed flex-grow-1 py-3" type="button" data-bs-toggle="collapse" data-bs-target="#${catId}">
            <span class="fw-bold">${cat}</span>
            <span class="ms-auto me-2 text-muted small">${fmt(total)}원</span>
          </button>
          <div class="calc-item border-0 p-2 m-0 bg-transparent" draggable="true"
               data-type="category" data-label="${cat}" data-val="${total}" title="전체 드래그">
            <i class="bi bi-grip-vertical fs-5 text-muted"></i>
          </div>
        </div>
      </h2>
      <div id="${catId}" class="accordion-collapse collapse" data-bs-parent="#asset-tree">
        <div class="accordion-body p-0 bg-light">
          <div class="list-group list-group-flush">
            ${items.map(item => {
              const dispVal = getVal(item);
              const depositNote = isRE && item.deposit > 0
                ? ` <span class="text-warning" style="font-size:10px">(보증금 ${fmt(item.deposit)}원 제외)</span>` : '';
              return `
              <div class="list-group-item bg-transparent d-flex justify-content-between align-items-center py-2 ps-4 calc-item"
                   draggable="true" data-type="item" data-label="${item.name}" data-val="${dispVal}">
                <span class="small">${item.name}${depositNote}</span>
                <span class="small fw-semibold text-muted">${fmt(dispVal)}원</span>
              </div>`;
            }).join('')}
          </div>
        </div>
      </div>
    </div>`;
  }

  treeEl.innerHTML = html;
  initDragEvents();
}

function initDragEvents() {
  document.querySelectorAll('.calc-item').forEach(item => {
    item.addEventListener('dragstart', e => {
      e.dataTransfer.setData('text/plain', JSON.stringify({
        label: item.dataset.label,
        val:   item.dataset.val,
        type:  item.dataset.type
      }));
      item.classList.add('dragging');
    });
    item.addEventListener('dragend', () => item.classList.remove('dragging'));
  });

  const dropZone = document.getElementById('calc-drop-zone');
  if (!dropZone) return;

  dropZone.addEventListener('dragover', e => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
  });

  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));

  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    try {
      const data = JSON.parse(e.dataTransfer.getData('text/plain'));
      addCalcItem(data);
    } catch (err) {
      console.error('Drop error:', err);
    }
  });
}

function addCalcItem(data) {
  _calcItems.push(data);
  renderCalcList();
}

function removeCalcItem(idx) {
  _calcItems.splice(idx, 1);
  renderCalcList();
}

function renderCalcList() {
  const dropZone = document.getElementById('calc-drop-zone');
  const placeholder = dropZone.querySelector('.drop-placeholder');
  
  // 기존 아이템들 제거
  Array.from(dropZone.children).forEach(el => {
    if (!el.classList.contains('drop-placeholder')) el.remove();
  });

  if (_calcItems.length === 0) {
    placeholder.style.display = 'block';
    document.getElementById('calc-total').textContent = '0원';
    return;
  }

  placeholder.style.display = 'none';

  let total = 0;
  _calcItems.forEach((item, idx) => {
    total += parseFloat(item.val);
    const div = document.createElement('div');
    div.className = 'calc-item border-primary bg-primary-subtle d-flex justify-content-between align-items-center p-3 mb-2 shadow-sm';
    div.innerHTML = `
      <div class="d-flex align-items-center gap-2">
        <span class="badge ${item.type === 'category' ? 'bg-primary' : 'bg-info'}">${item.type === 'category' ? '그룹' : '항목'}</span>
        <span class="fw-semibold">${item.label}</span>
      </div>
      <div class="d-flex align-items-center gap-3">
        <span class="fw-bold">${fmt(item.val)}원</span>
        <i class="bi bi-x-lg text-danger cursor-pointer" onclick="removeCalcItem(${idx})"></i>
      </div>
    `;
    dropZone.appendChild(div);
  });

  document.getElementById('calc-total').textContent = fmt(total) + '원';
}

function resetCalculator() {
  if (!confirm('계산기를 초기화하시겠습니까?')) return;
  _calcItems = [];
  renderCalcList();
}

// 초기화
loadAssets();
