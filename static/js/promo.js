'use strict';

const canWrite = window.PROMO_CONFIG?.canWrite ?? false;

// Local cache of promo objects keyed by name, for modal prefill
let _promoData = {};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
}

function formatPST(isoStr) {
    if (!isoStr) return '—';
    const [datePart, timePart] = isoStr.split('T');
    if (!datePart || !timePart) return isoStr;
    const [year, month, day] = datePart.split('-');
    const [hour, minute] = timePart.split(':');
    const h = parseInt(hour, 10);
    const ampm = h >= 12 ? 'PM' : 'AM';
    const h12 = h % 12 || 12;
    return `${month}/${day}/${year} ${h12}:${minute.padStart(2, '0')} ${ampm} PST`;
}

function toInputValue(isoStr) {
    // "2026-06-01T09:00:00" → "2026-06-01T09:00"
    return isoStr ? isoStr.slice(0, 16) : '';
}

function toIsoFull(inputVal) {
    // "2026-06-01T09:00" → "2026-06-01T09:00:00"
    return inputVal ? inputVal + ':00' : '';
}

function statusBadgeHtml(status) {
    const styles = {
        active:   'bg-green-100 text-green-800 border border-green-300',
        pending:  'bg-yellow-100 text-yellow-800 border border-yellow-300',
        inactive: 'bg-gray-100 text-gray-600 border border-gray-300',
    };
    const cls = styles[status] || styles.inactive;
    const label = status.charAt(0).toUpperCase() + status.slice(1);
    return `<span class="text-xs font-semibold px-2 py-0.5 rounded-full ${cls}">${label}</span>`;
}

function showNotification(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `fixed bottom-6 right-6 z-50 px-5 py-3 rounded-lg shadow-lg text-white font-semibold text-sm transition-all ${
        type === 'error' ? 'bg-red-600' : 'bg-green-600'
    }`;
    toast.classList.remove('hidden');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => toast.classList.add('hidden'), 4000);
}

function showModalError(modalPrefix, message) {
    const el = document.getElementById(`${modalPrefix}-error`);
    el.textContent = message;
    el.classList.remove('hidden');
}

function clearModalError(modalPrefix) {
    const el = document.getElementById(`${modalPrefix}-error`);
    el.textContent = '';
    el.classList.add('hidden');
}

// ─── Settings Panel ───────────────────────────────────────────────────────────

function toggleSettings() {
    const content = document.getElementById('settings-content');
    const arrow = document.getElementById('settings-arrow');
    const hidden = content.classList.toggle('hidden');
    arrow.style.transform = hidden ? '' : 'rotate(180deg)';
    if (!hidden) {
        refreshErrors();
        refreshLogs();
    }
}

// ─── Data Refresh ─────────────────────────────────────────────────────────────

async function refreshData() {
    try {
        const res = await fetch('/retail-promo/api/status');
        if (!res.ok) return;
        const data = await res.json();
        if (!data.success) return;

        _promoData = {};
        data.promos.forEach(p => { _promoData[p.name] = p; });

        renderInfoBoxes(data.stats);
        renderTable(data.promos);
    } catch (e) {
        // silent — will retry on next interval
    }
}

function renderInfoBoxes(stats) {
    document.getElementById('stat-total').textContent   = stats.total   ?? 0;
    document.getElementById('stat-pending').textContent = stats.pending ?? 0;
    document.getElementById('stat-active').textContent  = stats.active  ?? 0;
    document.getElementById('stat-inactive').textContent = stats.inactive ?? 0;
}

function renderTable(promos) {
    const tbody = document.getElementById('promo-tbody');
    if (!promos || promos.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center py-10 text-gray-500 text-sm">No promo codes yet. Click "Add Promo Code" to get started.</td></tr>`;
        return;
    }

    tbody.innerHTML = promos.map(p => {
        const discountStr = p.discount_type === 'percentage'
            ? `${p.discount_amount}%`
            : `$${Number(p.discount_amount).toFixed(2)}`;
        const dateRange = `${formatPST(p.start_dt)} – ${formatPST(p.end_dt)}`;
        const nextRun = p.next_run ? escapeHtml(p.next_run) : '—';
        const lastMod = formatPST(p.last_modified);
        const isInactive = p.status === 'inactive';

        const editBtn = canWrite
            ? `<button onclick="openEditModal('${escapeHtml(p.name)}')" class="text-blue-600 hover:text-blue-900 text-sm font-semibold mr-3">Edit</button>`
            : '';
        const inactivateBtn = canWrite && !isInactive
            ? `<button onclick="confirmInactivate('${escapeHtml(p.name)}')" class="text-red-600 hover:text-red-900 text-sm font-semibold">Inactivate</button>`
            : '';

        return `<tr data-name="${escapeHtml(p.name)}">
            <td class="px-4 py-4 whitespace-nowrap font-mono text-sm font-semibold text-gray-800">${escapeHtml(p.name)}</td>
            <td class="px-4 py-4 text-sm text-gray-600">${escapeHtml(p.description || '')}</td>
            <td class="px-4 py-4 whitespace-nowrap text-sm font-semibold text-gray-700">${escapeHtml(discountStr)}</td>
            <td class="px-4 py-4 text-xs text-gray-600">${escapeHtml(dateRange)}</td>
            <td class="px-4 py-4 whitespace-nowrap text-xs text-gray-500">${nextRun}</td>
            <td class="px-4 py-4 whitespace-nowrap">${statusBadgeHtml(p.status)}</td>
            <td class="px-4 py-4 whitespace-nowrap text-xs text-gray-500">${escapeHtml(lastMod)}</td>
            <td class="px-4 py-4 whitespace-nowrap text-sm">${editBtn}${inactivateBtn}</td>
        </tr>`;
    }).join('');
}

function filterTable() {
    const q = document.getElementById('search-input').value.toLowerCase();
    document.querySelectorAll('#promo-tbody tr').forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(q) ? '' : 'none';
    });
}

// ─── Add Modal ────────────────────────────────────────────────────────────────

function openAddModal() {
    document.getElementById('add-name').value = '';
    document.getElementById('add-description').value = '';
    document.getElementById('add-start-dt').value = '';
    document.getElementById('add-end-dt').value = '';
    document.getElementById('add-discount-amount').value = '';
    document.querySelector('input[name="add-use-type"][value="unlimited"]').checked = true;
    document.querySelector('input[name="add-discount-type"][value="percentage"]').checked = true;
    updateAddAmountLabel();
    clearModalError('add');
    document.getElementById('add-modal').classList.remove('hidden');
}

function closeAddModal() {
    document.getElementById('add-modal').classList.add('hidden');
}

function updateAddAmountLabel() {
    const type = document.querySelector('input[name="add-discount-type"]:checked')?.value;
    document.getElementById('add-amount-unit').textContent = type === 'flat' ? '($)' : '(%)';
}

async function submitAddForm() {
    clearModalError('add');
    const name          = document.getElementById('add-name').value.trim();
    const description   = document.getElementById('add-description').value.trim();
    const use_type      = document.querySelector('input[name="add-use-type"]:checked')?.value;
    const start_dt      = toIsoFull(document.getElementById('add-start-dt').value);
    const end_dt        = toIsoFull(document.getElementById('add-end-dt').value);
    const discount_type = document.querySelector('input[name="add-discount-type"]:checked')?.value;
    const discount_amount = parseFloat(document.getElementById('add-discount-amount').value);

    if (!name)         return showModalError('add', 'Promo code name is required.');
    if (!start_dt)     return showModalError('add', 'Start datetime is required.');
    if (!end_dt)       return showModalError('add', 'End datetime is required.');
    if (isNaN(discount_amount) || discount_amount <= 0)
                       return showModalError('add', 'Discount amount must be greater than 0.');
    if (discount_type === 'percentage' && discount_amount > 100)
                       return showModalError('add', 'Percentage discount cannot exceed 100.');

    const btn = document.getElementById('add-submit-btn');
    btn.disabled = true;
    btn.textContent = 'Saving...';

    try {
        const res = await fetch('/retail-promo/api/promo', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, description, use_type, start_dt, end_dt, discount_type, discount_amount}),
        });
        const data = await res.json();
        if (data.success) {
            closeAddModal();
            showNotification(`Promo "${name}" added successfully.`);
            refreshData();
        } else {
            showModalError('add', data.error || 'Failed to add promo.');
        }
    } catch (e) {
        showModalError('add', 'Network error. Please try again.');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Save';
    }
}

// ─── Edit Modal ───────────────────────────────────────────────────────────────

function openEditModal(name) {
    const p = _promoData[name];
    if (!p) return showNotification('Promo data not found. Please refresh.', 'error');

    document.getElementById('edit-name').value = p.name;
    document.getElementById('edit-name-display').textContent = p.name;
    document.getElementById('edit-description').value = p.description || '';
    document.getElementById('edit-start-dt').value = toInputValue(p.start_dt);
    document.getElementById('edit-end-dt').value = toInputValue(p.end_dt);
    document.getElementById('edit-discount-amount').value = p.discount_amount;

    const useTypeRadio = document.querySelector(`input[name="edit-use-type"][value="${p.use_type}"]`);
    if (useTypeRadio) useTypeRadio.checked = true;

    const discountRadio = document.querySelector(`input[name="edit-discount-type"][value="${p.discount_type}"]`);
    if (discountRadio) discountRadio.checked = true;

    updateEditAmountLabel();

    const badge = document.getElementById('edit-status-badge');
    const styles = {
        active:   'bg-green-100 text-green-800 border border-green-300',
        pending:  'bg-yellow-100 text-yellow-800 border border-yellow-300',
        inactive: 'bg-gray-100 text-gray-600 border border-gray-300',
    };
    badge.textContent = p.status.charAt(0).toUpperCase() + p.status.slice(1);
    badge.className = `text-sm font-semibold px-2 py-0.5 rounded-full ${styles[p.status] || styles.inactive}`;

    clearModalError('edit');
    document.getElementById('edit-modal').classList.remove('hidden');
}

function closeEditModal() {
    document.getElementById('edit-modal').classList.add('hidden');
}

function updateEditAmountLabel() {
    const type = document.querySelector('input[name="edit-discount-type"]:checked')?.value;
    document.getElementById('edit-amount-unit').textContent = type === 'flat' ? '($)' : '(%)';
}

async function submitEditForm() {
    clearModalError('edit');
    const name          = document.getElementById('edit-name').value;
    const description   = document.getElementById('edit-description').value.trim();
    const use_type      = document.querySelector('input[name="edit-use-type"]:checked')?.value;
    const start_dt      = toIsoFull(document.getElementById('edit-start-dt').value);
    const end_dt        = toIsoFull(document.getElementById('edit-end-dt').value);
    const discount_type = document.querySelector('input[name="edit-discount-type"]:checked')?.value;
    const discount_amount = parseFloat(document.getElementById('edit-discount-amount').value);

    if (!start_dt) return showModalError('edit', 'Start datetime is required.');
    if (!end_dt)   return showModalError('edit', 'End datetime is required.');
    if (isNaN(discount_amount) || discount_amount <= 0)
                   return showModalError('edit', 'Discount amount must be greater than 0.');
    if (discount_type === 'percentage' && discount_amount > 100)
                   return showModalError('edit', 'Percentage discount cannot exceed 100.');

    const btn = document.getElementById('edit-submit-btn');
    btn.disabled = true;
    btn.textContent = 'Saving...';

    try {
        const res = await fetch(`/retail-promo/api/promo/${encodeURIComponent(name)}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({description, use_type, start_dt, end_dt, discount_type, discount_amount}),
        });
        const data = await res.json();
        if (data.success) {
            closeEditModal();
            showNotification(`Promo "${name}" updated.`);
            refreshData();
        } else {
            showModalError('edit', data.error || 'Failed to update promo.');
        }
    } catch (e) {
        showModalError('edit', 'Network error. Please try again.');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Save Changes';
    }
}

// ─── Inactivate ───────────────────────────────────────────────────────────────

async function confirmInactivate(name) {
    if (!confirm(`Inactivate "${name}"? This will deactivate it in Fishbowl immediately.`)) return;

    try {
        const res = await fetch(`/retail-promo/api/promo/${encodeURIComponent(name)}/inactivate`, {
            method: 'POST',
        });
        const data = await res.json();
        if (data.success) {
            showNotification(`Promo "${name}" inactivated.`);
            refreshData();
        } else {
            showNotification(data.error || 'Failed to inactivate promo.', 'error');
        }
    } catch (e) {
        showNotification('Network error. Please try again.', 'error');
    }
}

// ─── Logs ─────────────────────────────────────────────────────────────────────

async function loadLogs() {
    try {
        const res = await fetch('/retail-promo/api/logs?limit=50');
        if (!res.ok) return;
        const data = await res.json();
        if (!data.success) return;
        displayErrors(data.errors || []);
        displayLogs(data.logs || []);
    } catch (e) {
        // silent
    }
}

function refreshErrors() { loadLogs(); }
function refreshLogs()   { loadLogs(); }

function displayErrors(errors) {
    const badge = document.getElementById('error-count-badge');
    const container = document.getElementById('error-log-container');
    badge.textContent = errors.length;

    if (errors.length === 0) {
        container.innerHTML = '<div class="text-center text-gray-500 py-4 text-sm">No errors recorded.</div>';
        return;
    }
    container.innerHTML = errors.map(e => `
        <div class="border-b last:border-b-0 py-2">
            <div class="flex items-start justify-between gap-2">
                <span class="text-xs text-gray-400 whitespace-nowrap">${escapeHtml(e.timestamp || '')}</span>
                <span class="text-xs font-mono font-semibold text-red-700">${escapeHtml(e.promo_name || '')}</span>
                <span class="text-xs text-gray-500 capitalize">${escapeHtml(e.triggered_by || '')}</span>
            </div>
            <div class="text-sm text-gray-700 mt-0.5">${escapeHtml(e.details || e.action || '')}</div>
        </div>
    `).join('');
}

function displayLogs(logs) {
    const badge = document.getElementById('log-count-badge');
    const container = document.getElementById('audit-log-container');
    badge.textContent = logs.length;

    if (logs.length === 0) {
        container.innerHTML = '<div class="text-center text-gray-500 py-4 text-sm">No logs recorded.</div>';
        return;
    }
    container.innerHTML = logs.map(e => `
        <div class="border-b last:border-b-0 py-2">
            <div class="flex items-start justify-between gap-2">
                <span class="text-xs text-gray-400 whitespace-nowrap">${escapeHtml(e.timestamp || '')}</span>
                <span class="text-xs font-mono font-semibold text-gray-700">${escapeHtml(e.promo_name || '')}</span>
                <span class="text-xs capitalize ${e.result === 'error' ? 'text-red-600 font-semibold' : 'text-green-700'}">${escapeHtml(e.result || '')}</span>
                <span class="text-xs text-gray-500 capitalize">${escapeHtml(e.triggered_by || '')}</span>
            </div>
            <div class="text-sm text-gray-700 mt-0.5">${escapeHtml(e.details || e.action || '')}</div>
        </div>
    `).join('');
}

async function clearAllErrors() {
    if (!confirm('Clear all error logs?')) return;
    try {
        await fetch('/retail-promo/api/errors/clear', {method: 'POST'});
        loadLogs();
        showNotification('Error logs cleared.');
    } catch (e) {
        showNotification('Failed to clear errors.', 'error');
    }
}

async function clearAllLogs() {
    if (!confirm('Clear all audit logs?')) return;
    try {
        await fetch('/retail-promo/api/logs/clear', {method: 'POST'});
        loadLogs();
        showNotification('Audit logs cleared.');
    } catch (e) {
        showNotification('Failed to clear logs.', 'error');
    }
}

// ─── Init ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    refreshData();
    loadLogs();
    setInterval(refreshData, 60000);
    setInterval(loadLogs, 60000);
});
