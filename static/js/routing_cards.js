// ============================================================================
// Digital Routing Card Manager — routing_cards.js
// Used by: templates/routing_cards/index.html + assign.html
// ============================================================================

const RC = window.ROUTING_CARDS_CONFIG || {};

// ============================================================================
// Index page — collapsible panels
// ============================================================================

function toggleRegister() {
    _togglePanel('register-content', 'register-arrow');
}

function toggleClose() {
    _togglePanel('close-content', 'close-arrow');
}

function _togglePanel(contentId, arrowId) {
    const content = document.getElementById(contentId);
    const arrow   = document.getElementById(arrowId);
    if (!content) return;
    const isHidden = content.classList.contains('hidden');
    content.classList.toggle('hidden', !isHidden);
    if (arrow) arrow.style.transform = isHidden ? 'rotate(180deg)' : '';
}

// ---- Register Cards --------------------------------------------------------

async function registerCards() {
    if (!RC.can_write) return;
    const input = document.getElementById('register-input');
    const result = document.getElementById('register-result');
    if (!input || !result) return;

    const raw = input.value.trim();
    if (!raw) {
        _showResult(result, 'error', 'Enter at least one card ID.');
        return;
    }

    try {
        const resp = await fetch('/routing-cards/api/cards/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ card_ids: raw }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            _showResult(result, 'error', data.error || 'Failed to register cards.');
            return;
        }
        let msg = '';
        if (data.added.length) msg += `Registered: ${data.added.join(', ')}. `;
        if (data.duplicates.length) msg += `Already registered (skipped): ${data.duplicates.join(', ')}.`;
        _showResult(result, 'success', msg.trim());
        input.value = '';
        // Reload the page after a short delay so the table updates
        setTimeout(() => location.reload(), 1200);
    } catch (e) {
        _showResult(result, 'error', 'Network error — please try again.');
    }
}

// ---- Close Work Order (index page) -----------------------------------------

async function closeWorkOrder() {
    if (!RC.can_write) return;
    const select = document.getElementById('close-order-select');
    const result = document.getElementById('close-result');
    if (!select || !result) return;

    const orderNumber = select.value.trim();
    if (!orderNumber) {
        _showResult(result, 'error', 'Select an order to close.');
        return;
    }

    if (!confirm(`Close work order "${orderNumber}"? This will release all assigned cards back to the pool.`)) return;

    try {
        const resp = await fetch('/routing-cards/api/close', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ order_number: orderNumber }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            _showResult(result, 'error', data.error || 'Failed to close order.');
            return;
        }
        const n = data.closed_count;
        _showResult(result, 'success', `Order ${orderNumber} closed — ${n} card${n !== 1 ? 's' : ''} returned to pool.`);
        select.value = '';
        setTimeout(() => location.reload(), 1400);
    } catch (e) {
        _showResult(result, 'error', 'Network error — please try again.');
    }
}

// ---- Refresh card table ----------------------------------------------------

function refreshCards() {
    location.reload();
}

// ============================================================================
// Assign page — two-stage scan workflow
// ============================================================================

let _confirmedOrder = null; // { order_number, part_number, revision }
let _scannedCards   = [];   // [{ card_id, batch_number, id, is_last_batch }]

// ---- Stage 1: Parse URL ----------------------------------------------------

function parseWorkOrderUrl() {
    const input  = document.getElementById('wo-url-input');
    const errEl  = document.getElementById('parse-error');
    const result = document.getElementById('parse-result');
    if (!input) return;

    const raw = input.value.trim();
    clearParseResult();

    let parsed;
    try {
        parsed = new URL(raw);
    } catch (e) {
        _showInline(errEl, 'Invalid URL — paste the full URL from the Intuiflow browser tab.');
        return;
    }

    const params      = new URLSearchParams(parsed.search);
    const orderNumber = params.get('OrderNumber');
    const partNumber  = params.get('PartNumber') || '';
    const revision    = params.get('Revision')   || '';

    if (!orderNumber) {
        _showInline(errEl, 'Could not find OrderNumber in that URL. Make sure you copied the full address bar URL.');
        return;
    }

    document.getElementById('parsed-order').textContent = orderNumber;
    document.getElementById('parsed-part').textContent  = partNumber || '—';
    document.getElementById('parsed-rev').textContent   = revision   || '—';
    result.classList.remove('hidden');

    window._pendingOrder = { order_number: orderNumber, part_number: partNumber, revision: revision, work_order_url: raw };
}

function clearParseResult() {
    const result = document.getElementById('parse-result');
    const err    = document.getElementById('parse-error');
    if (result) result.classList.add('hidden');
    if (err)    { err.textContent = ''; err.classList.add('hidden'); }
    window._pendingOrder = null;
}

function confirmWorkOrder() {
    if (!window._pendingOrder) return;
    _confirmedOrder = window._pendingOrder;
    _scannedCards   = [];

    document.getElementById('confirmed-order').textContent = _confirmedOrder.order_number;
    document.getElementById('confirmed-part').textContent  = _confirmedOrder.part_number || '—';
    document.getElementById('confirmed-rev').textContent   = _confirmedOrder.revision    || '—';

    document.getElementById('stage-1').classList.add('hidden');
    document.getElementById('stage-2').classList.remove('hidden');

    _renderScanList();
    document.getElementById('scan-input').focus();
}

function handleBack() {
    const stage2 = document.getElementById('stage-2');
    if (stage2 && !stage2.classList.contains('hidden')) {
        resetToStage1();
    } else {
        window.location.href = '/routing-cards/';
    }
}

function resetToStage1() {
    _confirmedOrder = null;
    _scannedCards   = [];
    document.getElementById('stage-2').classList.add('hidden');
    document.getElementById('stage-1').classList.remove('hidden');
    clearParseResult();
    document.getElementById('wo-url-input').value = '';
}

// ---- Stage 2: Scan loop ----------------------------------------------------

function _initScanInput() {
    const input = document.getElementById('scan-input');
    if (!input) return;

    input.addEventListener('keydown', async (e) => {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        const cardId = input.value.trim();
        input.value  = '';
        if (!cardId) return;
        await _assignCard(cardId);
        input.focus();
    });

    // Re-focus if user accidentally clicks elsewhere on the page
    document.addEventListener('click', (e) => {
        if (!document.getElementById('stage-2').classList.contains('hidden')) {
            const tag = e.target.tagName.toLowerCase();
            if (!['button', 'a', 'input', 'textarea', 'select'].includes(tag)) {
                input.focus();
            }
        }
    });
}

async function _assignCard(cardId, force = false) {
    const errEl = document.getElementById('scan-error');
    _showInline(errEl, '');

    if (!_confirmedOrder) return;

    let resp, data;
    try {
        resp = await fetch('/routing-cards/api/assign', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                card_id:        cardId,
                order_number:   _confirmedOrder.order_number,
                part_number:    _confirmedOrder.part_number,
                revision:       _confirmedOrder.revision,
                work_order_url: _confirmedOrder.work_order_url,
                force:          force,
            }),
        });
        data = await resp.json();
    } catch (e) {
        _showInline(errEl, 'Network error — please try again.');
        return;
    }

    if (!resp.ok) {
        if (data.conflict) {
            const msg = `Card "${cardId}" is currently assigned to order "${data.current_order}".\n\nReassign it to order "${_confirmedOrder.order_number}"?`;
            if (confirm(msg)) {
                await _assignCard(cardId, true);
            }
        } else {
            _showInline(errEl, `${cardId}: ${data.error || 'Unknown error'}`);
        }
        return;
    }

    // Update in place if card already in list (handles idempotent re-scans and force reassigns),
    // otherwise push a new entry.
    const idx = _scannedCards.findIndex(c => c.card_id === cardId);
    if (idx >= 0) {
        _scannedCards[idx] = {
            card_id:       cardId,
            batch_number:  data.batch_number,
            id:            data.id,
            is_last_batch: false,
        };
    } else {
        _scannedCards.push({
            card_id:       cardId,
            batch_number:  data.batch_number,
            id:            data.id,
            is_last_batch: false,
        });
    }
    _renderScanList();
}

async function toggleLastBatch(assignmentId) {
    const card = _scannedCards.find(c => c.id === assignmentId);
    if (!card) return;

    try {
        const resp = await fetch(`/routing-cards/api/assign/${assignmentId}/last-batch`, {
            method: 'PATCH',
        });
        if (resp.ok) {
            card.is_last_batch = true;
            _renderScanList();
        }
    } catch (e) {
        // fail silently — operator can retry
    }
}

function _renderScanList() {
    const empty  = document.getElementById('scan-list-empty');
    const table  = document.getElementById('scan-list-table');
    const tbody  = document.getElementById('scan-list-body');
    const badge  = document.getElementById('scan-count-badge');

    if (!empty || !table || !tbody) return;

    badge.textContent = _scannedCards.length;

    if (_scannedCards.length === 0) {
        empty.classList.remove('hidden');
        table.classList.add('hidden');
        return;
    }

    empty.classList.add('hidden');
    table.classList.remove('hidden');

    tbody.innerHTML = _scannedCards.map(c => `
        <tr class="hover:bg-gray-50">
            <td class="px-4 py-2 font-mono text-sm font-semibold text-gray-800">${_esc(c.card_id)}</td>
            <td class="px-4 py-2 text-sm text-gray-700">${c.batch_number}</td>
            <td class="px-4 py-2">
                ${c.is_last_batch
                    ? '<span class="bg-amber-100 text-amber-800 text-xs font-bold px-3 py-1 rounded-full">Last Batch</span>'
                    : `<button onclick="toggleLastBatch(${c.id})"
                               class="text-xs text-gray-400 hover:text-amber-600 hover:underline transition">
                           Mark as last
                       </button>`
                }
            </td>
        </tr>
    `).join('');
}

// ============================================================================
// Shared utilities
// ============================================================================

function _showResult(el, type, message) {
    if (!el) return;
    el.classList.remove('hidden');
    if (type === 'success') {
        el.className = 'mt-3 text-sm font-medium text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2';
    } else {
        el.className = 'mt-3 text-sm font-medium text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2';
    }
    el.textContent = message;
}

function _showInline(el, message) {
    if (!el) return;
    el.textContent = message;
    if (message) el.classList.remove('hidden');
    else         el.classList.add('hidden');
}

function _esc(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// ============================================================================
// Init
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    _initScanInput();
});
