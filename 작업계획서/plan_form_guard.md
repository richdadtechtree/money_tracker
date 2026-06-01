# 기능 개선 계획서 — 폼 입력 데이터 유실 방지

> **문제**: 모달/폼 작성 중 입력 영역 바깥을 클릭하거나, 실수로 페이지를 이동하면  
> 작성한 내용이 모두 삭제된다.  
> **범위**: 수입, 가계부, 카드, 투자, 부동산, 대출, 연금, 목표저축 등 전 페이지 모달

---

## 1. 원인 분석

### 1-1. Bootstrap 모달 기본 동작

```
사용자가 모달 외부(backdrop) 클릭
         ↓
Bootstrap이 modal.hide() 자동 호출
         ↓
모달 DOM이 초기화(reset) 또는 숨겨짐
         ↓
form 입력값 전부 유실 ← 문제
```

Bootstrap 모달은 기본적으로 `data-bs-backdrop="true"` 설정.  
이 경우 **바깥 클릭 → 즉시 닫힘 → 데이터 소멸** 이 발생한다.

### 1-2. 페이지 이동 시 유실

```
작성 중 → 사이드바에서 다른 메뉴 클릭
         ↓
브라우저가 새 페이지 로드
         ↓
현재 폼 내용 전부 소멸 ← 문제
```

`beforeunload` 이벤트 핸들러가 없어 경고 없이 이탈됨.

---

## 2. 해결 전략 (3계층)

```
Layer 1: 모달 외부 클릭 차단 (즉각 적용, 가장 확실)
   └── 바깥 클릭해도 닫히지 않게

Layer 2: 닫기 전 확인 다이얼로그 (사용자 의도 재확인)
   └── 입력값이 있으면 "정말 닫으시겠어요?" 확인

Layer 3: 자동 임시저장 (마지막 안전망)
   └── 입력할 때마다 localStorage에 자동저장
   └── 다시 열면 "이전에 작성하던 내용이 있습니다" 복원 제안
```

---

## 3. 수정 파일 및 범위

| 파일 | 수정 내용 |
|------|-----------|
| `static/js/common.js` | 전역 모달 가드 + 임시저장 유틸리티 함수 |
| `templates/base.html` | `beforeunload` 경고 + 전역 초기화 스크립트 |
| 각 템플릿 HTML | 모달 속성 변경 (`data-bs-backdrop`, `data-bs-keyboard`) |

> **핵심 원칙**: 각 템플릿을 일일이 건드리는 대신,  
> `common.js`에서 **페이지 로드 후 모든 모달을 자동으로 처리**하여  
> 템플릿 수정량을 최소화한다.

---

## 4. Layer 1 — 모달 외부 클릭 차단

### 방법 A: `common.js`에서 전체 모달 일괄 처리 (권장)

페이지마다 HTML을 수정하지 않고, JS에서 **DOM 로드 후 모든 모달에 static backdrop 적용**.

```javascript
// common.js — 페이지 로드 시 전체 모달에 자동 적용
document.addEventListener('DOMContentLoaded', function () {
    _initAllModals();
});

function _initAllModals() {
    /**
     * 페이지 내 모든 .modal 요소에 대해:
     * 1. data-bs-backdrop="static"  → 바깥 클릭 시 닫히지 않음
     * 2. data-bs-keyboard="false"   → ESC 키로도 닫히지 않음
     * 3. 닫기 시 입력값 확인 후 확인 다이얼로그 표시
     * 4. 입력 이벤트마다 localStorage 임시저장
     */
    document.querySelectorAll('.modal').forEach(modalEl => {
        // ── static backdrop 강제 적용 ──
        modalEl.setAttribute('data-bs-backdrop', 'static');
        modalEl.setAttribute('data-bs-keyboard', 'false');

        // ── Bootstrap Modal 인스턴스 재생성 (설정 반영) ──
        // 이미 생성된 인스턴스가 있으면 dispose 후 재생성
        const existing = bootstrap.Modal.getInstance(modalEl);
        if (existing) existing.dispose();
        new bootstrap.Modal(modalEl, {
            backdrop: 'static',
            keyboard: false
        });

        // ── 닫기 이벤트 가로채기 ──
        // data-bs-dismiss="modal" 버튼 클릭 시 확인 다이얼로그
        modalEl.querySelectorAll('[data-bs-dismiss="modal"]').forEach(btn => {
            btn.addEventListener('click', function (e) {
                if (_hasModalDirtyInput(modalEl)) {
                    e.preventDefault();
                    e.stopImmediatePropagation();
                    _showCloseConfirm(modalEl);
                }
                // 입력값 없으면 그냥 닫힘 (기본 동작)
            }, true);  // capture phase에서 처리
        });

        // ── 임시저장 연결 ──
        _bindAutosave(modalEl);
    });
}
```

### 방법 B: 각 모달 HTML에 속성 직접 추가 (보조 방법)

방법 A와 함께 사용하면 더 확실함.  
각 템플릿의 모달 태그를 아래와 같이 수정:

```html
<!-- 변경 전 -->
<div class="modal fade" id="addIncomeModal" tabindex="-1">

<!-- 변경 후 -->
<div class="modal fade" id="addIncomeModal" tabindex="-1"
     data-bs-backdrop="static"
     data-bs-keyboard="false">
```

**일괄 변경 가이드** (templates 디렉토리에서 실행):
```bash
# 모든 템플릿의 modal 태그에 속성 일괄 추가
# (백업 후 실행 권장)
find templates/ -name "*.html" -exec sed -i \
  's/class="modal fade"/class="modal fade" data-bs-backdrop="static" data-bs-keyboard="false"/g' \
  {} \;
```

---

## 5. Layer 2 — 닫기 전 확인 다이얼로그

### 핵심 함수: `_hasModalDirtyInput()` — 입력값 존재 여부 판단

```javascript
/**
 * 모달 내 폼 요소에 사용자가 입력한 값이 있는지 확인.
 * 
 * 체크 대상:
 *   - <input type="text|number|date"> : value가 비어있지 않음
 *   - <textarea>                      : value가 비어있지 않음
 *   - <select>                        : 첫 번째 option이 아닌 값 선택됨
 *
 * 제외 대상:
 *   - type="hidden", type="submit", type="button"
 *   - data-no-dirty 속성이 있는 요소 (자동 채워지는 필드 등)
 */
function _hasModalDirtyInput(modalEl) {
    const inputs = modalEl.querySelectorAll(
        'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([data-no-dirty]),' +
        'textarea:not([data-no-dirty]),' +
        'select:not([data-no-dirty])'
    );

    for (const el of inputs) {
        if (el.tagName === 'SELECT') {
            // 선택지가 첫 번째(placeholder)가 아닌 경우
            if (el.selectedIndex > 0) return true;
        } else {
            // 공백 제거 후 값이 있으면 dirty
            if ((el.value || '').trim() !== '') return true;
        }
    }
    return false;
}
```

### 확인 다이얼로그: `_showCloseConfirm()` — 커스텀 확인창

브라우저 기본 `confirm()`은 스타일 변경이 불가하므로  
Bootstrap 기반 확인 모달을 별도로 삽입:

```javascript
/**
 * "작성 중인 내용이 있습니다. 정말 닫으시겠어요?" 확인 다이얼로그.
 * 확인 시 모달 강제 닫기 + 임시저장 삭제.
 * 취소 시 아무것도 하지 않음.
 */
function _showCloseConfirm(targetModalEl) {
    // 확인 모달이 이미 있으면 재사용, 없으면 생성
    let confirmModal = document.getElementById('_formGuardConfirmModal');
    if (!confirmModal) {
        document.body.insertAdjacentHTML('beforeend', `
            <div class="modal fade" id="_formGuardConfirmModal" tabindex="-1"
                 style="z-index: 1060;">
                <div class="modal-dialog modal-dialog-centered modal-sm">
                    <div class="modal-content">
                        <div class="modal-header bg-warning text-dark py-2">
                            <h6 class="modal-title mb-0">⚠️ 작성 중인 내용이 있습니다</h6>
                        </div>
                        <div class="modal-body py-3 text-center">
                            <p class="mb-1">입력한 내용이 모두 <strong>삭제</strong>됩니다.</p>
                            <p class="mb-0 text-muted small">정말 닫으시겠어요?</p>
                        </div>
                        <div class="modal-footer py-2 justify-content-center gap-2">
                            <button id="_formGuardCancelBtn"
                                    class="btn btn-outline-secondary btn-sm">
                                계속 작성하기
                            </button>
                            <button id="_formGuardConfirmBtn"
                                    class="btn btn-danger btn-sm">
                                닫기 (내용 삭제)
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `);
        confirmModal = document.getElementById('_formGuardConfirmModal');
    }

    const bsConfirmModal = new bootstrap.Modal(confirmModal, {
        backdrop: true,
        keyboard: true
    });

    // "닫기" 버튼: 원본 모달 강제 닫기
    document.getElementById('_formGuardConfirmBtn').onclick = function () {
        bsConfirmModal.hide();
        // 임시저장 데이터 삭제
        _clearAutosave(targetModalEl);
        // 원본 모달 강제 닫기 (dirty 체크 우회)
        targetModalEl._forceClose = true;
        bootstrap.Modal.getInstance(targetModalEl)?.hide();
        targetModalEl._forceClose = false;
    };

    // "계속 작성하기" 버튼
    document.getElementById('_formGuardCancelBtn').onclick = function () {
        bsConfirmModal.hide();
    };

    bsConfirmModal.show();
}
```

### `hide.bs.modal` 이벤트로 강제 닫기 흐름 처리

```javascript
// 모달이 hide되려 할 때 dirty 체크 (backdrop 클릭 등 다른 경로 대비)
modalEl.addEventListener('hide.bs.modal', function (e) {
    // 강제 닫기 플래그가 있으면 그냥 통과
    if (modalEl._forceClose) return;

    if (_hasModalDirtyInput(modalEl)) {
        e.preventDefault();          // 닫힘 취소
        _showCloseConfirm(modalEl);  // 확인 다이얼로그 표시
    }
});
```

---

## 6. Layer 3 — localStorage 자동 임시저장

### 설계 원칙

- 사용자가 입력할 때마다 **300ms debounce** 후 자동 저장
- 저장 키: `form_draft_{페이지경로}_{모달ID}` (예: `form_draft_/budget_addBudgetModal`)
- 모달이 성공적으로 **저장(submit)되면 임시저장 삭제**
- 모달을 다시 열면 임시저장 데이터가 있을 때 복원 제안 토스트 표시

### 자동저장 함수

```javascript
// ── debounce 유틸 ──
function _debounce(fn, delay) {
    let timer;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

// ── 모달 자동저장 연결 ──
function _bindAutosave(modalEl) {
    const key = _getDraftKey(modalEl);

    // 입력 이벤트마다 저장 (300ms debounce)
    const debouncedSave = _debounce(() => _saveAutosave(modalEl, key), 300);

    modalEl.querySelectorAll('input, textarea, select').forEach(el => {
        el.addEventListener('input',  debouncedSave);
        el.addEventListener('change', debouncedSave);
    });

    // 모달이 열릴 때 임시저장 데이터 있으면 복원 제안
    modalEl.addEventListener('shown.bs.modal', function () {
        _checkAndOfferRestore(modalEl, key);
    });

    // 폼 submit(저장 버튼 클릭) 성공 시 임시저장 삭제
    // 각 페이지의 저장 함수가 완료 후 _clearAutosave()를 호출하도록
    // 또는 모달 내 [data-save-btn] 속성 버튼 클릭 시 자동 삭제
    modalEl.querySelectorAll('[data-save-btn], .btn-save-modal').forEach(btn => {
        btn.addEventListener('click', function () {
            // 실제 저장 성공 여부와 무관하게 임시저장 삭제
            // (저장 실패 시에는 다시 임시저장이 필요하지만 복잡도 상승)
            // 간소화: 저장 버튼 클릭 시 임시저장 삭제
            setTimeout(() => _clearAutosave(modalEl), 1000);
        });
    });
}

// ── 임시저장 키 생성 ──
function _getDraftKey(modalEl) {
    const path    = window.location.pathname;  // 예: '/budget'
    const modalId = modalEl.id || 'modal_unknown';
    return `form_draft_${path}_${modalId}`;
}

// ── 폼 데이터 수집 및 저장 ──
function _saveAutosave(modalEl, key) {
    const data = {};
    modalEl.querySelectorAll(
        'input:not([type="hidden"]):not([type="submit"]):not([type="button"]),' +
        'textarea, select'
    ).forEach(el => {
        if (el.name || el.id) {
            const fieldKey = el.name || el.id;
            data[fieldKey] = el.value;
        }
    });

    if (Object.keys(data).length === 0) return;

    localStorage.setItem(key, JSON.stringify({
        data,
        savedAt: new Date().toISOString(),
        url: window.location.pathname
    }));
}

// ── 임시저장 복원 ──
function _restoreAutosave(modalEl, key) {
    const raw = localStorage.getItem(key);
    if (!raw) return false;

    try {
        const { data } = JSON.parse(raw);
        Object.entries(data).forEach(([fieldKey, value]) => {
            const el = modalEl.querySelector(`[name="${fieldKey}"], #${fieldKey}`);
            if (el) el.value = value;
        });
        return true;
    } catch (e) {
        return false;
    }
}

// ── 임시저장 삭제 ──
function _clearAutosave(modalEl) {
    localStorage.removeItem(_getDraftKey(modalEl));
}

// ── 복원 제안 토스트 표시 ──
function _checkAndOfferRestore(modalEl, key) {
    const raw = localStorage.getItem(key);
    if (!raw) return;

    let savedAt = '';
    try {
        savedAt = new Date(JSON.parse(raw).savedAt).toLocaleTimeString('ko-KR');
    } catch (e) {}

    // 기존 복원 토스트가 있으면 제거
    document.getElementById('_restoreToast')?.remove();

    // 토스트 생성
    document.body.insertAdjacentHTML('beforeend', `
        <div id="_restoreToast"
             class="toast align-items-center text-bg-info border-0"
             role="alert"
             style="position:fixed; bottom:80px; right:20px; z-index:1070; min-width:300px;">
            <div class="d-flex align-items-center p-2">
                <div class="toast-body py-1">
                    📝 <strong>${savedAt}</strong>에 작성하던 내용이 있습니다.
                </div>
                <div class="ms-auto d-flex gap-1 pe-2">
                    <button class="btn btn-light btn-sm py-0"
                            onclick="_restoreAndDismiss('${key}', document.getElementById('${modalEl.id}'))">
                        복원
                    </button>
                    <button class="btn btn-outline-light btn-sm py-0"
                            onclick="_discardAndDismiss('${key}')">
                        무시
                    </button>
                </div>
            </div>
        </div>
    `);

    const toastEl = document.getElementById('_restoreToast');
    new bootstrap.Toast(toastEl, { autohide: false }).show();
}

function _restoreAndDismiss(key, modalEl) {
    _restoreAutosave(modalEl, key);
    document.getElementById('_restoreToast')?.remove();
}

function _discardAndDismiss(key) {
    localStorage.removeItem(key);
    document.getElementById('_restoreToast')?.remove();
}
```

---

## 7. Layer 보완 — 페이지 이탈 경고 (`base.html`)

```javascript
// base.html의 <script> 태그 또는 common.js 끝에 추가

(function () {
    /**
     * 페이지를 벗어날 때 (링크 클릭, 새로고침, 브라우저 뒤로가기 등)
     * 어느 모달이든 입력값이 있으면 이탈 경고를 표시한다.
     *
     * 주의: 모던 브라우저는 커스텀 메시지를 무시하고 고정 메시지를 표시함.
     * 그러나 확인/취소 다이얼로그 자체는 표시됨.
     */
    window.addEventListener('beforeunload', function (e) {
        // 열려 있는 모달 중 dirty 입력이 있는 것이 있는지 확인
        const openModals = document.querySelectorAll('.modal.show');
        let hasDirty = false;

        for (const modalEl of openModals) {
            if (_hasModalDirtyInput(modalEl)) {
                hasDirty = true;
                break;
            }
        }

        // 모달이 열려있지 않아도 페이지의 폼 입력값 확인
        if (!hasDirty) {
            const allInputs = document.querySelectorAll(
                'form input:not([type="hidden"]):not([type="submit"]), ' +
                'form textarea, form select'
            );
            for (const el of allInputs) {
                if ((el.value || '').trim() !== '') {
                    hasDirty = true;
                    break;
                }
            }
        }

        if (hasDirty) {
            e.preventDefault();
            // 크롬/사파리: returnValue 설정 필요
            e.returnValue = '작성 중인 내용이 있습니다. 페이지를 벗어나면 내용이 삭제됩니다.';
            return e.returnValue;
        }
    });

    // 사이드바 메뉴 링크 클릭 시 — 커스텀 확인창으로 더 나은 UX 제공
    // (beforeunload는 메시지 커스터마이징이 안 되므로)
    document.querySelectorAll('#sidebar a[href]').forEach(link => {
        link.addEventListener('click', function (e) {
            const openModals = document.querySelectorAll('.modal.show');
            let dirtyModal = null;

            for (const modalEl of openModals) {
                if (_hasModalDirtyInput(modalEl)) {
                    dirtyModal = modalEl;
                    break;
                }
            }

            if (!dirtyModal) return;  // dirty 없으면 그냥 이동

            e.preventDefault();
            const href = this.href;

            // Bootstrap 확인 다이얼로그 재활용
            _showNavigationConfirm(href);
        });
    });

    function _showNavigationConfirm(href) {
        let confirmModal = document.getElementById('_navGuardModal');
        if (!confirmModal) {
            document.body.insertAdjacentHTML('beforeend', `
                <div class="modal fade" id="_navGuardModal" tabindex="-1"
                     style="z-index:1060;">
                    <div class="modal-dialog modal-dialog-centered modal-sm">
                        <div class="modal-content">
                            <div class="modal-header bg-warning text-dark py-2">
                                <h6 class="modal-title mb-0">⚠️ 페이지를 이동할까요?</h6>
                            </div>
                            <div class="modal-body py-3 text-center">
                                <p class="mb-1">작성 중인 내용이 <strong>삭제</strong>됩니다.</p>
                                <p class="mb-0 text-muted small">지금 이동하시겠어요?</p>
                            </div>
                            <div class="modal-footer py-2 justify-content-center gap-2">
                                <button id="_navGuardCancelBtn"
                                        class="btn btn-outline-secondary btn-sm">
                                    계속 작성하기
                                </button>
                                <button id="_navGuardConfirmBtn"
                                        class="btn btn-danger btn-sm">
                                    이동하기
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            `);
            confirmModal = document.getElementById('_navGuardModal');
        }

        const bsNavModal = new bootstrap.Modal(confirmModal, {
            backdrop: true,
            keyboard: true
        });

        document.getElementById('_navGuardConfirmBtn').onclick = function () {
            // localStorage 임시저장 전체 정리 후 이동
            bsNavModal.hide();
            window.location.href = href;
        };

        document.getElementById('_navGuardCancelBtn').onclick = function () {
            bsNavModal.hide();
        };

        bsNavModal.show();
    }
})();
```

---

## 8. 각 페이지별 저장 함수 연동

각 페이지의 저장 버튼 클릭 → API 호출 성공 후 `_clearAutosave()` 호출 패턴:

```javascript
// 예: budget.html의 saveExpense() 함수
async function saveExpense() {
    const data = collectFormData();  // 기존 로직

    try {
        const res = await fetch('/api/budget', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (res.ok) {
            // ── [추가] 저장 성공 시 임시저장 삭제 ──
            const modalEl = document.getElementById('addBudgetModal');
            _clearAutosave(modalEl);

            // 모달 강제 닫기 (dirty 체크 우회)
            modalEl._forceClose = true;
            bootstrap.Modal.getInstance(modalEl)?.hide();
            modalEl._forceClose = false;

            loadBudget();  // 목록 새로고침
        }
    } catch (e) {
        alert('저장에 실패했습니다. 다시 시도해주세요.');
    }
}
```

**모든 저장 함수에 공통으로 적용할 래퍼 함수** (`common.js`에 추가):

```javascript
/**
 * API 저장 성공 후 모달 닫기 + 임시저장 삭제를 처리하는 공통 함수.
 *
 * @param {string} modalId  - 닫을 모달의 id (예: 'addBudgetModal')
 * @param {Function} onSuccess - 저장 성공 후 실행할 콜백 (목록 새로고침 등)
 */
function _afterSaveSuccess(modalId, onSuccess) {
    const modalEl = document.getElementById(modalId);
    if (!modalEl) return;

    // 임시저장 삭제
    _clearAutosave(modalEl);

    // 강제 닫기 플래그 설정 후 닫기
    modalEl._forceClose = true;
    const bsModal = bootstrap.Modal.getInstance(modalEl);
    if (bsModal) bsModal.hide();
    setTimeout(() => { modalEl._forceClose = false; }, 500);

    // 성공 콜백 실행
    if (typeof onSuccess === 'function') {
        onSuccess();
    }
}

// 사용 예시
// 기존: bootstrap.Modal.getInstance(modal).hide(); loadBudget();
// 변경: _afterSaveSuccess('addBudgetModal', loadBudget);
```

---

## 9. 수정 후 동작 흐름 (Before / After)

### Before

```
사용자가 "수입 추가" 모달에서 이름, 금액, 날짜 입력 중
         ↓
실수로 모달 바깥(어두운 배경) 클릭
         ↓
모달 즉시 닫힘
         ↓
입력한 내용 전부 소멸 😞
```

### After

```
사용자가 "수입 추가" 모달에서 이름, 금액, 날짜 입력 중
         ↓
[300ms마다] localStorage에 입력값 자동저장
         ↓
실수로 모달 바깥 클릭 시도
         ↓
data-bs-backdrop="static" → 닫히지 않음 ✅
         ↓
X 버튼 또는 취소 버튼 클릭 시
         ↓
"입력한 내용이 삭제됩니다. 정말 닫으시겠어요?" 확인 다이얼로그
         ↓
[계속 작성하기] → 모달 유지, 내용 그대로 ✅
[닫기]         → 모달 닫힘, 임시저장 삭제
         ↓
나중에 같은 모달을 다시 열면
         ↓
"14:32에 작성하던 내용이 있습니다. [복원] [무시]" 토스트 표시 ✅
```

---

## 10. 구현 순서 및 체크리스트

```
STEP 1: common.js — 핵심 함수 추가                    ⭐⭐   1시간
  ├─ _initAllModals()
  ├─ _hasModalDirtyInput()
  ├─ _showCloseConfirm()
  ├─ _bindAutosave() + _saveAutosave() + _restoreAutosave()
  ├─ _checkAndOfferRestore() (토스트)
  ├─ _clearAutosave()
  └─ _afterSaveSuccess() (공통 저장 래퍼)

STEP 2: base.html — 이탈 경고 추가                     ⭐     30분
  ├─ beforeunload 이벤트 핸들러
  └─ 사이드바 링크 클릭 가드

STEP 3: 각 템플릿 HTML — static backdrop 속성 추가     ⭐     20분
  └─ sed 명령어로 일괄 변환 또는 수동 추가

STEP 4: 각 페이지 저장 함수 — _afterSaveSuccess 연동   ⭐⭐   1시간
  ├─ income.html   → saveIncome()
  ├─ budget.html   → saveExpense()
  ├─ cards.html    → saveCard(), saveCardTx()
  ├─ investments.html → saveStock(), saveEtf()
  ├─ realestate.html  → saveRealEstate()
  ├─ loans.html    → saveLoan()
  ├─ pension.html  → savePension()
  └─ goals.html    → saveGoal()

STEP 5: 검증                                           ⭐     30분
  □ 모달 바깥 클릭 시 닫히지 않는지 확인
  □ X버튼 클릭 시 확인 다이얼로그 뜨는지 확인
  □ 입력 없는 모달은 확인 없이 바로 닫히는지 확인
  □ localStorage 임시저장 → 복원 토스트 표시 확인
  □ 저장 성공 후 localStorage 삭제 확인
  □ 사이드바 메뉴 클릭 시 이탈 경고 확인
  □ 다크모드에서 확인 다이얼로그 텍스트 가시성 확인
```

---

## 11. 예외 처리 및 엣지 케이스

| 상황 | 처리 방법 |
|------|-----------|
| 수정(편집) 모달 — 기존 데이터로 채워짐 | `data-original-value` 속성으로 원본값 저장, 변경됐을 때만 dirty 판정 |
| 날짜 자동 채우기 (`value=today`) | `data-no-dirty` 속성 추가로 dirty 판정에서 제외 |
| localStorage 용량 초과 | try-catch로 감싸고 실패 시 임시저장 건너뜀 |
| 두 탭에서 같은 페이지 동시 사용 | 키에 `_탭ID` 접미사 추가로 분리 가능 (선택 구현) |
| 모달 없이 인라인 폼 사용하는 페이지 | `_hasModalDirtyInput`을 폼 엘리먼트에도 직접 적용 |
| 저장 API 실패 시 | 임시저장을 삭제하지 않고 유지 → 다음 열 때 복원 가능 |

---

## 12. 수정 파일 요약

| 파일 | 변경 규모 | 주요 내용 |
|------|----------|-----------|
| `static/js/common.js` | +180줄 추가 | 전체 가드 유틸리티 함수군 |
| `templates/base.html` | +30줄 추가 | beforeunload + 사이드바 가드 |
| `templates/*.html` (8개) | 각 1~5줄 수정 | 저장 함수에 `_afterSaveSuccess` 연동 |
| (선택) `templates/*.html` | 모달 태그 속성 추가 | `data-bs-backdrop="static"` |
