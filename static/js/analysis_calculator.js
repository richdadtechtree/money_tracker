/**
 * 가용자산 계산기 전용 스크립트
 */

function toKoreanNumber(num) {
  const n = Math.floor(num);
  if (n === 0) return '영원';

  const digits  = ['', '일', '이', '삼', '사', '오', '육', '칠', '팔', '구'];
  const subUnit = ['', '십', '백', '천'];
  const bigUnit = ['', '만', '억', '조'];

  function group4(g) {
    let s = '';
    for (let i = 3; i >= 0; i--) {
      const d = Math.floor(g / Math.pow(10, i)) % 10;
      if (d) s += digits[d] + subUnit[i];
    }
    return s;
  }

  let result = '';
  let remaining = n;
  for (let i = 3; i >= 0; i--) {
    const unit = Math.pow(10, i * 4);
    const g = Math.floor(remaining / unit);
    remaining %= unit;
    if (g) result += group4(g) + bigUnit[i];
  }
  return result + '원';
}

function updateKoreanAmount(value) {
  const display = document.getElementById('korean-amount-display');
  if (!display) return;
  const num = parseFloat(value);
  display.textContent = (value && !isNaN(num) && num > 0) ? toKoreanNumber(num) : '';
}

let _calcItems = [];
let _allAssets = null;
let _extraItems = []; // 추가 투입 자산

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
    const escapedCat = cat.replace(/'/g, "\\'");

    html += `
    <div class="accordion-item border-0 mb-2 shadow-sm rounded overflow-hidden">
      <h2 class="accordion-header">
        <div class="d-flex align-items-center bg-white pe-2">
          <button class="accordion-button collapsed flex-grow-1 py-3" type="button" data-bs-toggle="collapse" data-bs-target="#${catId}">
            <span class="fw-bold">${cat}</span>
            <span class="ms-auto me-2 text-muted small">${fmt(total)}원</span>
          </button>
          <div class="d-flex align-items-center gap-1">
            <button class="btn btn-sm text-primary p-1 border-0 bg-transparent" title="계산기에 추가"
                    onclick="event.stopPropagation(); addCalcItem({label: '${escapedCat}', val: ${total}, type: 'category'})">
              <i class="bi bi-plus-circle fs-5"></i>
            </button>
            <div class="calc-item border-0 p-2 m-0 bg-transparent" draggable="true"
                 data-type="category" data-label="${cat}" data-val="${total}" title="전체 드래그">
              <i class="bi bi-grip-vertical fs-5 text-muted"></i>
            </div>
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
              const escapedName = item.name.replace(/'/g, "\\'");
              return `
              <div class="list-group-item bg-transparent d-flex justify-content-between align-items-center py-2 ps-4 pe-3 calc-item cursor-pointer"
                   draggable="true" data-type="item" data-label="${escapedName}" data-val="${dispVal}"
                   onclick="if(this.classList.contains('dragging')) return; addCalcItem({label: '${escapedName}', val: ${dispVal}, type: 'item'})">
                <div class="flex-grow-1 d-flex justify-content-between align-items-center me-3">
                  <span class="small">${item.name}${depositNote}</span>
                  <span class="small fw-semibold text-muted">${fmt(dispVal)}원</span>
                </div>
                <i class="bi bi-plus-circle text-primary fs-5"></i>
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
  // 커스텀 추가 자산 아이템도 포함
  const customItem = document.getElementById('custom-asset-drag-item');
  if (customItem) {
    customItem.addEventListener('dragstart', e => {
      e.dataTransfer.setData('text/plain', JSON.stringify({
        label: customItem.dataset.label,
        val:   customItem.dataset.val,
        type:  customItem.dataset.type
      }));
      customItem.classList.add('dragging');
    });
    customItem.addEventListener('dragend', () => customItem.classList.remove('dragging'));
  }

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
  if (data.type === 'custom') {
    // 모달로 이름과 금액 입력받기
    document.getElementById('custom-asset-name').value = '추가 자산';
    document.getElementById('custom-asset-amount').value = '';
    document.getElementById('korean-amount-display').textContent = '';
    const modal = new bootstrap.Modal(document.getElementById('customAssetModal'));
    modal.show();
    document.getElementById('customAssetModal').addEventListener('shown.bs.modal', () => {
      document.getElementById('custom-asset-amount').focus();
    }, { once: true });
    // Enter 키로 추가
    document.getElementById('custom-asset-amount').addEventListener('keydown', function onEnter(e) {
      if (e.key === 'Enter') { confirmCustomAsset(); this.removeEventListener('keydown', onEnter); }
    });
    return;
  }
  _calcItems.push(data);
  renderCalcList();
}

function confirmCustomAsset() {
  const name = document.getElementById('custom-asset-name').value.trim() || '추가 자산';
  const raw  = document.getElementById('custom-asset-amount').value;
  const amount = parseFloat(raw);
  if (raw === '' || isNaN(amount) || amount < 0) {
    document.getElementById('custom-asset-amount').classList.add('is-invalid');
    document.getElementById('custom-asset-amount').focus();
    return;
  }
  document.getElementById('custom-asset-amount').classList.remove('is-invalid');
  _calcItems.push({ label: name, val: amount, type: 'custom' });
  renderCalcList();
  bootstrap.Modal.getInstance(document.getElementById('customAssetModal')).hide();
}

function updateCustomItemVal(idx, value) {
  const num = parseFloat(value);
  if (!isNaN(num) && num >= 0) {
    _calcItems[idx].val = num;
    let total = 0;
    _calcItems.forEach(item => total += parseFloat(item.val));
    document.getElementById('calc-total').textContent = fmt(total) + '원';
  }
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

    if (item.type === 'custom') {
      div.innerHTML = `
        <div class="d-flex align-items-center gap-2">
          <span class="badge bg-success">직접입력</span>
          <span class="fw-semibold">${item.label}</span>
        </div>
        <div class="d-flex align-items-center gap-2">
          <div class="input-group input-group-sm" style="width:160px">
            <input type="number" class="form-control form-control-sm text-end fw-bold"
                   value="${item.val}" min="0" step="1"
                   oninput="updateCustomItemVal(${idx}, this.value)">
            <span class="input-group-text">원</span>
          </div>
          <i class="bi bi-x-lg text-danger cursor-pointer" onclick="removeCalcItem(${idx})"></i>
        </div>
      `;
    } else {
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
    }
    dropZone.appendChild(div);
  });

  document.getElementById('calc-total').textContent = fmt(total) + '원';
  updateGrandTotal();
}

function resetCalculator() {
  if (!confirm('계산기를 초기화하시겠습니까?')) return;
  _calcItems = [];
  _extraItems = [];
  renderCalcList();
  renderExtraList();
}

// ── 추가 투입 자산 ─────────────────────────────────────────────
function addExtraItem() {
  _extraItems.push({ label: '', val: 0 });
  renderExtraList();
  // 새로 생긴 입력칸으로 포커스
  const inputs = document.querySelectorAll('.extra-label-input');
  if (inputs.length) inputs[inputs.length - 1].focus();
}

function removeExtraItem(idx) {
  _extraItems.splice(idx, 1);
  renderExtraList();
}

function updateExtraItem(idx, field, value) {
  if (field === 'val') {
    const raw = value.replace(/,/g, '').replace(/[^0-9]/g, '');
    _extraItems[idx].val = parseInt(raw || '0', 10);
  } else {
    _extraItems[idx][field] = value;
  }
  updateGrandTotal();
}

function renderExtraList() {
  const el = document.getElementById('extra-items-list');
  if (!el) return;

  el.innerHTML = _extraItems.map((item, idx) => `
    <div class="d-flex align-items-center gap-2 mb-2">
      <input type="text" class="form-control form-control-sm extra-label-input"
             placeholder="항목명 (예: 부모님 지원)" value="${item.label}"
             oninput="updateExtraItem(${idx}, 'label', this.value)"
             style="flex:1.2; font-size:13px">
      <input type="text" class="form-control form-control-sm text-end"
             placeholder="금액" value="${item.val ? item.val.toLocaleString('ko-KR') : ''}"
             oninput="this.value=this.value.replace(/[^0-9,]/g,'').replace(/,/g,'').replace(/\\B(?=(\\d{3})+(?!\\d))/g,','); updateExtraItem(${idx}, 'val', this.value)"
             style="flex:1; font-size:13px">
      <button class="btn btn-sm btn-outline-danger py-0 px-1 border-0" onclick="removeExtraItem(${idx})">
        <i class="bi bi-x-lg" style="font-size:11px"></i>
      </button>
    </div>
  `).join('');

  updateGrandTotal();
}

function updateGrandTotal() {
  const extraTotal = _extraItems.reduce((s, i) => s + (i.val || 0), 0);
  const calcTotal  = _calcItems.reduce((s, i) => s + parseFloat(i.val || 0), 0);
  const grand      = calcTotal + extraTotal;

  const etEl = document.getElementById('extra-total');
  const gtEl = document.getElementById('calc-grand-total');
  if (etEl) etEl.textContent = fmt(extraTotal) + '원';
  if (gtEl) gtEl.textContent = fmt(grand) + '원';
}

// 초기화
loadAssets();
