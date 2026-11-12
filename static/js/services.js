// services.js — Various Services page JS
// Bootstrap data injected by the template: window.SERVICES_CONFIG

const _logsCache = {};       // { [name]: {logs, log_stats, errors, error_stats} }
const _logsLoaded = {};      // { [name]: true } — prevent duplicate fetches
const _activeTab = {};       // { [name]: 'schedule' | 'logs' | 'notifications' }
const _activeLogTab = {};    // { [name]: 'audit' | 'error' }
const _cardOpen = {};        // { [name]: bool }

// --------------------------------- Notifications ------------------------------------ //

function showNotification(message, type = 'info') {
    const colors = { success: 'bg-green-500', error: 'bg-red-500', info: 'bg-blue-500' };
    const el = document.createElement('div');
    el.className = `fixed top-4 right-4 ${colors[type] || colors.info} text-white px-6 py-3 rounded shadow-lg z-50 text-sm`;
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 6000);
}

// --------------------------------- Card expand/collapse ----------------------------- //

function toggleCard(name) {
    const body = document.getElementById(`card-body-${name}`);
    const chevron = document.getElementById(`chevron-${name}`);
    _cardOpen[name] = !_cardOpen[name];

    if (_cardOpen[name]) {
        body.classList.remove('hidden');
        chevron.classList.add('rotate-180');
        // Default to Schedule tab on first open
        if (!_activeTab[name]) switchTab(name, 'schedule');
    } else {
        body.classList.add('hidden');
        chevron.classList.remove('rotate-180');
    }
}

// --------------------------------- Tab switching ------------------------------------ //

function switchTab(name, tab) {
    _activeTab[name] = tab;
    // Tabs vary per card (e.g. OneDrive Shortcuts has an extra Syncs tab) — use the ones rendered.
    document.querySelectorAll(`[data-tab-btn][data-card="${name}"]`).forEach(btn => {
        const t = btn.dataset.tab;
        const panel = document.getElementById(`tab-panel-${name}-${t}`);
        const active = t === tab;
        btn.classList.toggle('border-blue-500', active);
        btn.classList.toggle('text-blue-600', active);
        btn.classList.toggle('font-semibold', active);
        btn.classList.toggle('border-transparent', !active);
        btn.classList.toggle('text-gray-500', !active);
        panel.classList.toggle('hidden', !tab || t !== tab);
    });

    if (tab === 'logs' && !_logsLoaded[name]) loadLogs(name);
    if (tab === 'syncs' && name === SC_NAME) scInit();
}

// --------------------------------- Run Now ----------------------------------------- //

async function runService(name) {
    const btn = document.getElementById(`run-btn-${name}`);
    btn.disabled = true;
    btn.textContent = 'Starting...';
    updateStatusBadge(name, 'running');

    try {
        const resp = await fetch(`/services/run/${name}`, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
        const result = await resp.json();

        if (resp.ok && result.success) {
            btn.textContent = 'Running...';
            pollStatus(name);
        } else {
            showNotification(result.error || 'Failed to start service', 'error');
            btn.disabled = false;
            btn.textContent = '▶ Run Now';
            updateStatusBadge(name, window.SERVICES_CONFIG[name]?.last_status || null);
        }
    } catch (e) {
        showNotification('Error starting service', 'error');
        btn.disabled = false;
        btn.textContent = '▶ Run Now';
    }
}

function pollStatus(name, attempts = 0) {
    if (attempts > 60) {
        showNotification(`Timed out waiting for ${name} to complete`, 'error');
        return;
    }
    setTimeout(async () => {
        try {
            const resp = await fetch('/services/status');
            const result = await resp.json();
            const svc = result.services[name];

            if (!svc.running) {
                updateServiceUI(name, svc);
                // Invalidate log cache so next open re-fetches
                _logsLoaded[name] = false;
                const label = svc.label || name;
                showNotification(
                    svc.last_status === 'success'
                        ? `${label} completed successfully`
                        : `${label} finished with errors`,
                    svc.last_status === 'success' ? 'success' : 'error'
                );
            } else {
                pollStatus(name, attempts + 1);
            }
        } catch (e) {
            pollStatus(name, attempts + 1);
        }
    }, 5000);
}

function updateServiceUI(name, svc) {
    const btn = document.getElementById(`run-btn-${name}`);
    btn.disabled = false;
    btn.textContent = '▶ Run Now';

    updateStatusBadge(name, svc.last_status);

    const lastRunEl = document.getElementById(`last-run-${name}`);
    if (lastRunEl && svc.last_run) {
        lastRunEl.textContent = formatDatetime(svc.last_run);
    }

    const nextRunEl = document.getElementById(`next-run-${name}`);
    if (nextRunEl) {
        nextRunEl.textContent = svc.next_run ? formatDatetime(svc.next_run) : '—';
    }

    // Update bootstrap config
    if (window.SERVICES_CONFIG[name]) {
        Object.assign(window.SERVICES_CONFIG[name], svc);
    }
}

function updateStatusBadge(name, status) {
    const el = document.getElementById(`status-badge-${name}`);
    if (!el) return;
    const badges = {
        running: 'bg-yellow-100 text-yellow-800',
        success: 'bg-green-100 text-green-800',
        error:   'bg-red-100 text-red-800',
    };
    const labels = { running: 'Running...', success: 'Last run: Success', error: 'Last run: Error' };
    const cls = badges[status] || 'bg-gray-100 text-gray-600';
    const text = labels[status] || 'Never run';
    el.innerHTML = `<span class="${cls} text-xs font-bold px-3 py-1 rounded-full">${text}</span>`;
}

// --------------------------------- Schedule tab ------------------------------------- //

function onScheduleTypeChange(name) {
    const type = document.getElementById(`schedule-type-${name}`).value;
    ['interval', 'daily', 'weekly', 'custom'].forEach(t => {
        document.getElementById(`sched-${t}-${name}`).classList.toggle('hidden', t !== type);
    });
}

function selectScheduleType(name, type) {
    document.getElementById(`schedule-type-${name}`).value = type;
    ['interval', 'daily', 'weekly', 'custom'].forEach(t => {
        const btn = document.getElementById(`sched-type-btn-${t}-${name}`);
        if (!btn) return;
        const active = t === type;
        btn.classList.toggle('bg-blue-500', active);
        btn.classList.toggle('text-white', active);
        btn.classList.toggle('bg-white', !active);
        btn.classList.toggle('text-gray-600', !active);
    });
    onScheduleTypeChange(name);
}

function saveSchedule(name) {
    const type = document.getElementById(`schedule-type-${name}`).value;
    const enabled = document.getElementById(`enabled-toggle-input-${name}`).checked;

    let payload = { schedule_type: type, enabled };

    if (type === 'interval') {
        const mins = parseInt(document.getElementById(`interval-mins-${name}`).value);
        if (!mins || mins < 1) { showNotification('Interval must be at least 1 minute', 'error'); return; }
        payload.schedule_interval_minutes = mins;
        payload.schedule_cron = null;

    } else if (type === 'daily') {
        const time = document.getElementById(`daily-time-${name}`).value;
        if (!time) { showNotification('Please select a time', 'error'); return; }
        const [hour, minute] = time.split(':').map(Number);
        payload.schedule_type = 'cron';
        payload.schedule_cron = { hour, minute };

    } else if (type === 'weekly') {
        const day = document.getElementById(`weekly-day-${name}`).value;
        const time = document.getElementById(`weekly-time-${name}`).value;
        if (!time) { showNotification('Please select a time', 'error'); return; }
        const [hour, minute] = time.split(':').map(Number);
        payload.schedule_type = 'cron';
        payload.schedule_cron = { day_of_week: day, hour, minute };

    } else if (type === 'custom') {
        const expr = document.getElementById(`custom-cron-${name}`).value.trim();
        if (!expr) { showNotification('Please enter a cron expression', 'error'); return; }
        // Parse 5-field cron: minute hour day_of_month month day_of_week
        const parts = expr.split(/\s+/);
        if (parts.length !== 5) { showNotification('Cron expression must have 5 fields (e.g. 0 9 * * 1-5)', 'error'); return; }
        payload.schedule_type = 'cron';
        payload.schedule_cron = {
            minute:      parts[0],
            hour:        parts[1],
            day:         parts[2],
            month:       parts[3],
            day_of_week: parts[4],
        };
    }

    _putConfig(name, payload, (result) => {
        const svc = result.config;
        showNotification(
            svc.enabled
                ? `${svc.label}: schedule saved`
                : `${svc.label}: schedule disabled`,
            'success'
        );
        const nextRunEl = document.getElementById(`next-run-${name}`);
        if (nextRunEl) nextRunEl.textContent = svc.next_run ? formatDatetime(svc.next_run) : '—';
        if (window.SERVICES_CONFIG[name]) Object.assign(window.SERVICES_CONFIG[name], svc);
    });
}

// --------------------------------- Log tab ----------------------------------------- //

async function loadLogs(name) {
    if (_logsLoaded[name]) {
        renderLogTab(name, 'audit');
        renderLogTab(name, 'error');
        return;
    }
    const panel = document.getElementById(`log-loading-${name}`);
    if (panel) panel.classList.remove('hidden');

    try {
        const resp = await fetch(`/services/logs/${name}`);
        const result = await resp.json();
        if (resp.ok && result.success) {
            _logsCache[name] = result.data;
            _logsLoaded[name] = true;
        } else {
            showNotification('Failed to load logs', 'error');
        }
    } catch (e) {
        showNotification('Error loading logs', 'error');
    }

    if (panel) panel.classList.add('hidden');
    renderLogTab(name, 'audit');
    renderLogTab(name, 'error');
}

function renderLogTab(name, tab) {
    const isAudit = tab === 'audit';
    const contentEl = document.getElementById(`log-entries-${name}-${isAudit ? 'audit' : 'error'}`);
    if (!contentEl) return;

    const cached = _logsCache[name];
    if (!cached) { contentEl.innerHTML = '<p class="text-gray-400 text-sm">Loading...</p>'; return; }

    const entries = isAudit ? cached.logs.filter(e => e.status !== 'error') : cached.errors;
    const stats   = isAudit ? cached.log_stats : cached.error_stats;

    // Count badge
    const badgeId = isAudit ? `log-count-badge-${name}` : `error-count-badge-${name}`;
    const badgeEl = document.getElementById(badgeId);
    if (badgeEl) badgeEl.textContent = entries ? entries.length : 0;

    if (!entries || entries.length === 0) {
        contentEl.innerHTML = '<p class="text-gray-400 text-sm italic">No records yet.</p>';
        return;
    }

    contentEl.innerHTML = entries.map(e => {
        const statusCls = e.status === 'success'
            ? 'bg-green-100 text-green-800'
            : 'bg-red-100 text-red-800';
        const triggerCls = e.triggered_by === 'manual'
            ? 'bg-purple-100 text-purple-700'
            : e.triggered_by === 'sync-change'
                ? 'bg-amber-100 text-amber-700'
                : 'bg-blue-100 text-blue-700';

        let logRows = '';
        if (e.log_data) {
            for (const [func, messages] of Object.entries(e.log_data)) {
                logRows += `<div class="mb-1"><span class="font-bold text-gray-700">${escHtml(func)}:</span>`;
                for (const msg of messages) {
                    logRows += `<div class="ml-4 text-gray-600">${escHtml(String(msg))}</div>`;
                }
                logRows += '</div>';
            }
        }

        return `
        <div class="border rounded-lg mb-3 overflow-hidden">
            <div class="flex items-center gap-3 px-4 py-2 bg-gray-50 border-b cursor-pointer"
                 onclick="toggleLogEntry(this)">
                <span class="text-xs text-gray-500">${formatDatetime(e.timestamp)}</span>
                <span class="${statusCls} text-xs font-bold px-2 py-0.5 rounded-full">${e.status}</span>
                <span class="${triggerCls} text-xs font-semibold px-2 py-0.5 rounded-full capitalize">${e.triggered_by}</span>
                <svg class="w-4 h-4 text-gray-400 ml-auto transition-transform" fill="none"
                     stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                </svg>
            </div>
            <div class="hidden px-4 py-3 bg-gray-50 font-mono text-xs text-gray-700">
                ${logRows || '<span class="text-gray-400">No output recorded.</span>'}
            </div>
        </div>`;
    }).join('');
}

function toggleLogEntry(headerEl) {
    const body = headerEl.nextElementSibling;
    const arrow = headerEl.querySelector('svg');
    body.classList.toggle('hidden');
    arrow.classList.toggle('rotate-180');
}

function refreshLogs(name) {
    _logsLoaded[name] = false;
    _logsCache[name]  = null;
    loadLogs(name);
}

async function clearLogs(name, type) {
    const url = type === 'errors'
        ? `/services/logs/${name}/errors`
        : `/services/logs/${name}`;
    try {
        const resp   = await fetch(url, { method: 'DELETE' });
        const result = await resp.json();
        if (!resp.ok || !result.success) { showNotification(result.error || 'Failed to clear', 'error'); return; }
        if (type === 'errors') {
            if (_logsCache[name]) {
                _logsCache[name].errors      = [];
                _logsCache[name].error_stats = { total_errors: 0, last_error: null };
            }
        } else {
            if (_logsCache[name]) {
                _logsCache[name].logs      = [];
                _logsCache[name].log_stats = { total_runs: 0, last_run: null };
            }
        }
        renderLogTab(name, 'audit');
        renderLogTab(name, 'error');
        showNotification('Logs cleared', 'success');
    } catch (e) {
        showNotification('Failed to clear logs', 'error');
    }
}

// --------------------------------- Notifications tab -------------------------------- //

function saveNotifications(name) {
    const mode = document.querySelector(`input[name="notify-mode-${name}"]:checked`)?.value || 'none';
    const chips = document.querySelectorAll(`#recipient-chips-${name} [data-email]`);
    const recipients = Array.from(chips).map(c => c.dataset.email);

    if (mode !== 'none' && recipients.length === 0) {
        showNotification('Add at least one recipient before enabling notifications', 'error');
        return;
    }

    _putConfig(name, { notify_mode: mode, notify_recipients: recipients }, (result) => {
        showNotification(`${result.config.label}: notification settings saved`, 'success');
        if (window.SERVICES_CONFIG[name]) Object.assign(window.SERVICES_CONFIG[name], result.config);
    });
}

function addRecipient(name) {
    const input = document.getElementById(`recipient-input-${name}`);
    const email = input.value.trim();
    if (!email || !email.includes('@')) { showNotification('Enter a valid email address', 'error'); return; }

    // Prevent duplicates
    const existing = Array.from(
        document.querySelectorAll(`#recipient-chips-${name} [data-email]`)
    ).map(c => c.dataset.email);
    if (existing.includes(email)) { showNotification('That email is already in the list', 'error'); return; }

    const chip = document.createElement('span');
    chip.dataset.email = email;
    chip.className = 'inline-flex items-center gap-1 bg-blue-100 text-blue-800 text-xs font-semibold px-3 py-1 rounded-full';
    chip.innerHTML = `${escHtml(email)} <button type="button" onclick="removeRecipient(this)" class="ml-1 text-blue-500 hover:text-red-500 font-bold leading-none">×</button>`;
    document.getElementById(`recipient-chips-${name}`).appendChild(chip);
    input.value = '';
}

function removeRecipient(btn) {
    btn.closest('[data-email]').remove();
}

// --------------------------------- Shared helpers ----------------------------------- //

function _putConfig(name, payload, onSuccess) {
    fetch(`/services/config/${name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    })
    .then(r => r.json().then(d => ({ ok: r.ok, data: d })))
    .then(({ ok, data }) => {
        if (ok && data.success) {
            onSuccess(data);
        } else {
            showNotification(data.error || 'Failed to save', 'error');
        }
    })
    .catch(() => showNotification('Network error', 'error'));
}

function formatDatetime(iso) {
    if (!iso) return '—';
    // Naive datetime strings from the server have no timezone indicator — parse components directly
    if (!/Z$/.test(iso) && !/[+-]\d{2}:?\d{2}$/.test(iso)) {
        const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/);
        if (!m) return iso;
        let h = +m[4];
        const ampm = h >= 12 ? 'p.m.' : 'a.m.';
        if (h > 12) h -= 12;
        if (h === 0) h = 12;
        return `${m[1]}-${m[2]}-${m[3]} ${h}:${m[5]}:${m[6]} ${ampm}`;
    }
    const normalized = iso.replace(/(\.\d{3})\d+/, '$1');
    const d = new Date(normalized);
    if (isNaN(d)) return iso.substring(0, 19).replace('T', ' ');
    return new Intl.DateTimeFormat('en-CA', {
        timeZone: 'America/Los_Angeles',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: 'numeric', minute: '2-digit', second: '2-digit',
        hour12: true,
    }).format(d).replace(',', '');
}

document.addEventListener('DOMContentLoaded', () => {
    for (const [name, cfg] of Object.entries(window.SERVICES_CONFIG || {})) {
        const el = document.getElementById(`last-run-${name}`);
        if (el && cfg.last_run) el.textContent = formatDatetime(cfg.last_run);
    }
});

function escHtml(str) {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// ===================================================================================== //
// OneDrive Shortcuts — Syncs tab, Validate, Preview
// See .claude/12. sharepoint_onedrive_shortcut.md
// ===================================================================================== //

const SC_NAME = 'onedrive-shortcuts';
const SC_TARGET_TYPES = [['all_users', 'All users'], ['groups', 'Groups'], ['users', 'Specific users']];

let _scSyncs = null;          // working copy (array) — null until the tab is first opened
let _scSaved = [];            // last saved copy (from the server)
let _scState = { syncs: {}, pending_removals: [] };  // tracked counts + pending removals
let _scValidation = {};       // { [syncId]: validate result }
let _scOpen = {};             // { [syncId]: bool } — row expanded
let _scPreviewTimer = null;

function scCanWrite() { return !!window.SERVICES_CAN_WRITE; }
function scClone(x) { return JSON.parse(JSON.stringify(x)); }
function scFind(id) { return (_scSyncs || []).find(s => s.id === id); }
function scSavedFind(id) { return _scSaved.find(s => s.id === id); }
function scTracked(id) { return (_scState.syncs[id] || {}).tracked || 0; }
function scIsDirty() { return JSON.stringify(_scSyncs) !== JSON.stringify(_scSaved); }
function scNewId() {
    const a = new Uint8Array(4);
    crypto.getRandomValues(a);
    return Array.from(a, b => b.toString(16).padStart(2, '0')).join('');
}
// Mirrors sync_fingerprint() in VariousInternalServices/data.py
function scFingerprint(s) {
    const site = (s.site_url || '').trim().replace(/\/+$/, '').toLowerCase();
    return `${site}|${(s.library_name || '').trim().toLowerCase()}|${(s.shortcut_name || '').trim().toLowerCase()}`;
}

function scInit() {
    if (_scSyncs !== null) return;
    const cfg = (window.SERVICES_CONFIG || {})[SC_NAME] || {};
    _scSaved = scClone(cfg.syncs || []);
    _scSyncs = scClone(_scSaved);
    scRender();
    scLoadState();
}

async function scLoadState() {
    try {
        const resp = await fetch('/services/onedrive-shortcuts/state');
        const result = await resp.json();
        if (resp.ok && result.success) {
            _scState = result.state;
            scRender();
        }
    } catch (e) { /* counts are informational only */ }
}

// --------------------------------- Rendering ---------------------------------------- //

function scRender() {
    const list = document.getElementById('sc-syncs-list');
    if (!list || _scSyncs === null) return;
    list.innerHTML = _scSyncs.length
        ? _scSyncs.map(scRowHtml).join('')
        : '<p class="text-sm text-gray-400 italic">No syncs yet. Click <strong>+ Add Sync</strong> to create one.</p>';
    scRenderPending();
    scUpdateDirty();
    if (!scCanWrite()) {
        document.getElementById('sc-add-btn')?.setAttribute('disabled', '');
        document.getElementById('sc-save-btn')?.setAttribute('disabled', '');
    }
}

function scRenderPending() {
    const el = document.getElementById('sc-pending');
    if (!el) return;
    const pending = _scState.pending_removals || [];
    if (!pending.length) { el.classList.add('hidden'); return; }
    el.classList.remove('hidden');
    el.innerHTML = '<span class="font-semibold">Pending removals</span> (processed at the start of the next run): ' +
        pending.map(p => `${escHtml(p.name || 'Sync')}: ${p.count} user${p.count === 1 ? '' : 's'} (sync ${escHtml(p.reason || '')})`).join('; ');
}

function scUpdateDirty() {
    const dirty = _scSyncs !== null && scIsDirty();
    document.getElementById('sc-dirty-hint')?.classList.toggle('hidden', !dirty);
    const prev = document.getElementById('sc-preview-btn');
    if (prev) prev.disabled = dirty;
}

function scRowHtml(s) {
    const ro = scCanWrite() ? '' : 'disabled';
    const saved = scSavedFind(s.id);
    const tracked = scTracked(s.id);
    const open = _scOpen[s.id] ?? !saved;
    const v = _scValidation[s.id];
    const inputCls = 'border rounded py-1.5 px-3 text-sm w-full focus:outline-none focus:ring-2 focus:ring-blue-500';

    const typeBtns = SC_TARGET_TYPES.map(([val, label], i) => {
        const active = s.target_type === val;
        return `<button type="button" ${ro} onclick="scSetTargetType('${s.id}', '${val}')"
                    class="flex-1 py-1.5 text-sm font-semibold transition ${i ? 'border-l border-gray-300' : ''}
                           ${active ? 'bg-blue-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}">${label}</button>`;
    }).join('');

    const targetsBlock = s.target_type === 'all_users'
        ? `<p class="text-xs text-gray-500">Every enabled, licensed member account in the tenant (guests excluded).</p>`
        : scChipsBlock(s, 'targets', s.target_type === 'groups' ? 'Group name or object ID' : 'user@company.com',
                       s.target_type === 'groups' ? 'Groups (nested group members are included)' : 'Users');

    return `
    <div class="border rounded-lg bg-white" id="sc-row-${s.id}">
        <div class="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50 select-none" onclick="scToggleRow('${s.id}')">
            <svg class="w-4 h-4 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
            <span id="sc-${s.id}-title" class="font-semibold text-gray-800">${escHtml(s.name || 'New sync')}</span>
            ${s.enabled
                ? '<span class="bg-green-100 text-green-800 text-xs font-bold px-2 py-0.5 rounded-full">Enabled</span>'
                : '<span class="bg-gray-100 text-gray-600 text-xs font-bold px-2 py-0.5 rounded-full">Paused</span>'}
            ${saved ? `<span class="text-xs text-gray-500">${tracked} user${tracked === 1 ? '' : 's'} have this shortcut</span>`
                    : '<span class="bg-amber-100 text-amber-800 text-xs font-bold px-2 py-0.5 rounded-full">Not saved</span>'}
        </div>
        <div class="${open ? '' : 'hidden'} border-t px-4 py-4 space-y-4">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                    <label class="block text-sm font-semibold text-gray-700 mb-1">Sync name</label>
                    <input type="text" ${ro} class="${inputCls}" value="${escHtml(s.name || '')}" placeholder="Company Hub"
                           oninput="scSet('${s.id}', 'name', this.value)">
                </div>
                <div class="flex items-end">
                    <label class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                        <input type="checkbox" ${ro} ${s.enabled ? 'checked' : ''} class="accent-blue-500 w-4 h-4"
                               onchange="scSet('${s.id}', 'enabled', this.checked, true)">
                        Enabled <span class="text-xs text-gray-400">(unchecked = paused; existing shortcuts stay)</span>
                    </label>
                </div>
                <div class="md:col-span-2">
                    <label class="block text-sm font-semibold text-gray-700 mb-1">SharePoint site URL</label>
                    <input type="url" ${ro} class="${inputCls}" value="${escHtml(s.site_url || '')}"
                           placeholder="https://contoso.sharepoint.com/sites/CompanyHub"
                           oninput="scSet('${s.id}', 'site_url', this.value)">
                </div>
                <div>
                    <label class="block text-sm font-semibold text-gray-700 mb-1">Library name</label>
                    <input type="text" ${ro} id="sc-${s.id}-library" class="${inputCls}" value="${escHtml(s.library_name || '')}"
                           placeholder="Documents" oninput="scSet('${s.id}', 'library_name', this.value)">
                </div>
                <div>
                    <label class="block text-sm font-semibold text-gray-700 mb-1">Shortcut name <span class="font-normal text-gray-400">(optional)</span></label>
                    <input type="text" ${ro} class="${inputCls}" value="${escHtml(s.shortcut_name || '')}"
                           placeholder="${escHtml(s.library_name || 'Library name')}"
                           oninput="scSet('${s.id}', 'shortcut_name', this.value)">
                    <p class="text-xs text-gray-400 mt-1">OneDrive always adds the site name in front:
                        "<em>${escHtml(v && v.site_display_name ? v.site_display_name : 'Site name')}</em> - ${escHtml(s.shortcut_name || s.library_name || 'Library name')}".
                        Leave blank to use the library name, which matches a manual click.</p>
                </div>
            </div>
            <div id="sc-${s.id}-editwarn">${scEditWarningHtml(s)}</div>
            <div>
                <label class="block text-sm font-semibold text-gray-700 mb-2">Sync to</label>
                <div class="flex rounded-lg border border-gray-300 overflow-hidden w-full md:w-2/3 mb-3">${typeBtns}</div>
                ${targetsBlock}
            </div>
            <details ${s.exclude_upns && s.exclude_upns.length ? 'open' : ''}>
                <summary class="text-sm font-semibold text-gray-700 cursor-pointer">Exclude users (${(s.exclude_upns || []).length})</summary>
                <div class="mt-2">${scChipsBlock(s, 'exclude_upns', 'user@company.com', '')}</div>
            </details>
            <div id="sc-${s.id}-validate">${v ? scValidationHtml(s.id, v) : ''}</div>
            <div class="flex items-center gap-2">
                <button type="button" ${ro} onclick="scValidate('${s.id}')" id="sc-${s.id}-validate-btn"
                        class="bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-semibold py-1.5 px-3 rounded transition">Validate</button>
                <div class="flex-1"></div>
                <button type="button" ${ro} onclick="scRemoveSync('${s.id}')"
                        class="bg-white border border-red-300 text-red-600 hover:bg-red-50 text-sm font-semibold py-1.5 px-3 rounded transition">Delete Sync</button>
            </div>
        </div>
    </div>`;
}

function scChipsBlock(s, field, placeholder, label) {
    const ro = scCanWrite() ? '' : 'disabled';
    return `
        ${label ? `<label class="block text-sm font-semibold text-gray-700 mb-2">${label}</label>` : ''}
        <div id="sc-${s.id}-${field}-chips" class="flex flex-wrap gap-2 mb-2">${scChipsHtml(s, field)}</div>
        <div class="flex items-center gap-2">
            <input type="text" ${ro} id="sc-${s.id}-${field}-input" placeholder="${escHtml(placeholder)}"
                   onkeydown="if(event.key==='Enter'){event.preventDefault();scAddChip('${s.id}','${field}');}"
                   class="border rounded py-1.5 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-72">
            <button type="button" ${ro} onclick="scAddChip('${s.id}','${field}')"
                    class="bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-semibold py-1.5 px-3 rounded transition">+ Add</button>
        </div>`;
}

function scChipsHtml(s, field) {
    const ro = scCanWrite() ? '' : 'disabled';
    const values = s[field] || [];
    if (!values.length) return '<span class="text-xs text-gray-400 italic">None</span>';
    return values.map((val, i) => `
        <span class="inline-flex items-center gap-1 bg-blue-100 text-blue-800 text-xs font-semibold px-3 py-1 rounded-full">
            ${escHtml(val)}
            <button type="button" ${ro} onclick="scRemoveChip('${s.id}','${field}',${i})"
                    class="ml-1 text-blue-500 hover:text-red-500 font-bold leading-none">×</button>
        </span>`).join('');
}

function scEditWarningHtml(s) {
    const saved = scSavedFind(s.id);
    const tracked = scTracked(s.id);
    if (!saved || !tracked || scFingerprint(saved) === scFingerprint(s)) return '';
    return `<div class="bg-amber-50 border border-amber-300 text-amber-800 rounded p-3 text-sm">
        You changed the site, library, or shortcut name. Saving will <strong>remove the existing shortcut from
        ${tracked} user${tracked === 1 ? '' : 's'}</strong> and add the new one on the next run.</div>`;
}

function scValidationHtml(id, v) {
    if (v.loading) return '<p class="text-sm text-gray-400 italic">Validating...</p>';
    let html = '';
    if (v.ok) {
        html += `<div class="bg-green-50 border border-green-200 text-green-800 rounded p-3 text-sm">
            ✓ Site <strong>${escHtml(v.site_display_name || '')}</strong> found. Library found.
            Shortcut will be named <strong>${escHtml(v.shortcut_name || '')}</strong>.
            ${v.target_count !== null ? `<strong>${v.target_count}</strong> eligible user${v.target_count === 1 ? '' : 's'}.` : ''}</div>`;
    } else {
        html += `<div class="bg-red-50 border border-red-200 text-red-800 rounded p-3 text-sm space-y-1">
            ${(v.errors || []).map(e => `<div>✗ ${escHtml(e)}</div>`).join('')}`;
        if (v.library_names && v.library_names.length && scCanWrite()) {
            html += `<div class="pt-1">Use library:
                <select class="border rounded py-1 px-2 text-sm text-gray-800" onchange="scPickLibrary('${id}', this.value)">
                    <option value="">Choose...</option>
                    ${v.library_names.map(n => `<option value="${escHtml(n)}">${escHtml(n)}</option>`).join('')}
                </select></div>`;
        }
        html += '</div>';
    }
    if (v.warnings && v.warnings.length) {
        html += `<div class="bg-amber-50 border border-amber-200 text-amber-800 rounded p-3 text-sm mt-2">
            ${v.warnings.map(w => `<div>⚠ ${escHtml(w)}</div>`).join('')}</div>`;
    }
    return html;
}

// --------------------------------- Editing ------------------------------------------ //

function scToggleRow(id) {
    const saved = scSavedFind(id);
    _scOpen[id] = !(_scOpen[id] ?? !saved);
    scRender();
}

function scSet(id, field, value, rerender = false) {
    const s = scFind(id);
    if (!s) return;
    s[field] = value;
    if (['site_url', 'library_name', 'shortcut_name'].includes(field)) {
        delete _scValidation[id];
        const v = document.getElementById(`sc-${id}-validate`);
        if (v) v.innerHTML = '';
        const w = document.getElementById(`sc-${id}-editwarn`);
        if (w) w.innerHTML = scEditWarningHtml(s);
    }
    if (field === 'name') {
        const t = document.getElementById(`sc-${id}-title`);
        if (t) t.textContent = value || 'New sync';
    }
    if (rerender) scRender(); else scUpdateDirty();
}

function scPickLibrary(id, value) {
    if (!value) return;
    scSet(id, 'library_name', value, true);
}

function scSetTargetType(id, type) {
    const s = scFind(id);
    if (!s || s.target_type === type) return;
    s.target_type = type;
    s.targets = [];
    delete _scValidation[id];
    scRender();
}

function scAddChip(id, field) {
    const s = scFind(id);
    const input = document.getElementById(`sc-${id}-${field}-input`);
    const value = (input.value || '').trim();
    if (!s || !value) return;
    if ((field === 'exclude_upns' || s.target_type === 'users') && !value.includes('@')) {
        showNotification('Enter a user principal name, e.g. user@company.com', 'error');
        return;
    }
    s[field] = s[field] || [];
    if (s[field].some(v => v.toLowerCase() === value.toLowerCase())) {
        showNotification('That entry is already in the list', 'error');
        return;
    }
    s[field].push(value);
    input.value = '';
    delete _scValidation[id];
    document.getElementById(`sc-${id}-${field}-chips`).innerHTML = scChipsHtml(s, field);
    document.getElementById(`sc-${id}-validate`).innerHTML = '';
    scUpdateDirty();
}

function scRemoveChip(id, field, index) {
    const s = scFind(id);
    if (!s) return;
    s[field].splice(index, 1);
    delete _scValidation[id];
    document.getElementById(`sc-${id}-${field}-chips`).innerHTML = scChipsHtml(s, field);
    document.getElementById(`sc-${id}-validate`).innerHTML = '';
    scUpdateDirty();
}

function scAddSync() {
    const id = scNewId();
    _scSyncs.push({ id, name: '', enabled: true, site_url: '', library_name: 'Documents', shortcut_name: '',
                    target_type: 'groups', targets: [], exclude_upns: [] });
    _scOpen[id] = true;
    scRender();
}

async function scRemoveSync(id) {
    const s = scFind(id);
    if (!s) return;
    const saved = scSavedFind(id);
    const tracked = scTracked(id);
    const label = (saved && saved.name) || s.name || 'this sync';

    // Never saved: just drop the row from the editor.
    if (!saved) {
        if (!confirm(`Discard new sync "${label}"?`)) return;
        _scSyncs = _scSyncs.filter(x => x.id !== id);
        delete _scValidation[id];
        scRender();
        return;
    }

    // Saved sync: deleting takes effect immediately (no separate Save step), so the removal
    // can't be silently lost by leaving the page. Other unsaved edits on the page are kept.
    const msg = `Delete sync "${label}" now?\n\n` +
        (tracked
            ? `Its shortcut will be REMOVED from ${tracked} user${tracked === 1 ? '' : 's'}' OneDrive right away.\n\n` +
              'Only the shortcut is removed. The SharePoint library and its files are not affected.'
            : 'No users currently have this sync\'s shortcut.');
    if (!confirm(msg)) return;

    try {
        const resp = await fetch('/services/onedrive-shortcuts/syncs', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ syncs: _scSaved.filter(x => x.id !== id) }),
        });
        const result = await resp.json();
        if (!resp.ok || !result.success) {
            showNotification(result.error || 'Failed to delete sync', 'error');
            return;
        }
        _scSaved = scClone(result.syncs);
        _scSyncs = _scSyncs.filter(x => x.id !== id);   // keep any other unsaved edits
        _scState = result.state || _scState;
        delete _scValidation[id];
        if (window.SERVICES_CONFIG[SC_NAME]) window.SERVICES_CONFIG[SC_NAME].syncs = scClone(result.syncs);
        scRender();

        const queued = (result.queued_removals || []).reduce((n, q) => n + q.count, 0);
        showNotification(queued
            ? (result.run_started
                ? `Sync "${label}" deleted. Removing its shortcut from ${queued} user${queued === 1 ? '' : 's'} now.`
                : `Sync "${label}" deleted. Its shortcut will be removed from ${queued} user${queued === 1 ? '' : 's'} on the next run.`)
            : `Sync "${label}" deleted`, 'success');
        if (result.run_started) {
            updateStatusBadge(SC_NAME, 'running');
            const runBtn = document.getElementById(`run-btn-${SC_NAME}`);
            if (runBtn) { runBtn.disabled = true; runBtn.textContent = 'Running...'; }
            pollStatus(SC_NAME);
        }
    } catch (e) {
        showNotification('Network error while deleting sync', 'error');
    }
}

// Warn before leaving the page with unsaved sync edits.
window.addEventListener('beforeunload', (e) => {
    if (_scSyncs !== null && scIsDirty()) { e.preventDefault(); e.returnValue = ''; }
});

// --------------------------------- Save / Validate ---------------------------------- //

async function scSaveSyncs() {
    const btn = document.getElementById('sc-save-btn');
    btn.disabled = true;
    try {
        const resp = await fetch('/services/onedrive-shortcuts/syncs', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ syncs: _scSyncs }),
        });
        const result = await resp.json();
        if (!resp.ok || !result.success) {
            showNotification(result.error || 'Failed to save syncs', 'error');
            return;
        }
        _scSaved = scClone(result.syncs);
        _scSyncs = scClone(result.syncs);
        _scState = result.state || _scState;
        if (window.SERVICES_CONFIG[SC_NAME]) window.SERVICES_CONFIG[SC_NAME].syncs = scClone(result.syncs);
        scRender();

        const queued = result.queued_removals || [];
        if (queued.length) {
            const what = queued.map(q => `${q.name} (${q.count} user${q.count === 1 ? '' : 's'})`).join(', ');
            showNotification(result.run_started
                ? `Syncs saved. Removing shortcuts now: ${what}`
                : `Syncs saved. Shortcuts will be removed on the next run: ${what}`, 'info');
        } else {
            showNotification('Syncs saved', 'success');
        }
        if (result.run_started) {
            updateStatusBadge(SC_NAME, 'running');
            const runBtn = document.getElementById(`run-btn-${SC_NAME}`);
            if (runBtn) { runBtn.disabled = true; runBtn.textContent = 'Running...'; }
            pollStatus(SC_NAME);
        }
    } catch (e) {
        showNotification('Network error while saving syncs', 'error');
    } finally {
        btn.disabled = !scCanWrite();
    }
}

async function scValidate(id) {
    const s = scFind(id);
    if (!s) return;
    _scValidation[id] = { loading: true };
    document.getElementById(`sc-${id}-validate`).innerHTML = scValidationHtml(id, _scValidation[id]);
    try {
        const resp = await fetch('/services/onedrive-shortcuts/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sync: s }),
        });
        const result = await resp.json();
        if (!resp.ok || !result.success) {
            _scValidation[id] = { ok: false, errors: [result.error || 'Validation failed'], warnings: [] };
        } else {
            _scValidation[id] = result.result;
        }
    } catch (e) {
        _scValidation[id] = { ok: false, errors: ['Network error during validation'], warnings: [] };
    }
    scRender();
}

// --------------------------------- Preview ------------------------------------------ //

function scOpenModal(html) {
    const modal = document.getElementById('sc-preview-modal');
    document.getElementById('sc-preview-body').innerHTML = html;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

function scClosePreview() {
    const modal = document.getElementById('sc-preview-modal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    if (_scPreviewTimer) { clearTimeout(_scPreviewTimer); _scPreviewTimer = null; }
}

async function scStartPreview() {
    if (_scSyncs !== null && scIsDirty()) {
        showNotification('Save your changes before previewing', 'error');
        return;
    }
    scOpenModal('<p class="text-gray-500 italic">Running preview: looking up users and checking their OneDrive. This can take a minute...</p>');
    try {
        const resp = await fetch('/services/onedrive-shortcuts/preview', { method: 'POST' });
        const result = await resp.json();
        if (!resp.ok || !result.success) {
            scOpenModal(`<div class="text-red-700">${escHtml(result.error || 'Failed to start preview')}</div>`);
            return;
        }
        scPollPreview(0);
    } catch (e) {
        scOpenModal('<div class="text-red-700">Network error starting preview</div>');
    }
}

function scPollPreview(attempts) {
    if (attempts > 150) {
        scOpenModal('<div class="text-red-700">Timed out waiting for the preview to finish.</div>');
        return;
    }
    _scPreviewTimer = setTimeout(async () => {
        try {
            const resp = await fetch('/services/onedrive-shortcuts/preview');
            const result = await resp.json();
            if (result.running) { scPollPreview(attempts + 1); return; }
            _scPreviewTimer = null;
            if (document.getElementById('sc-preview-modal').classList.contains('hidden')) return;
            scOpenModal(result.error
                ? `<div class="text-red-700">Preview failed: ${escHtml(result.error)}</div>`
                : scPreviewHtml(result.result));
        } catch (e) {
            scPollPreview(attempts + 1);
        }
    }, 2000);
}

function scPreviewList(label, items, cls, open = false) {
    if (!items || !items.length) return '';
    return `<details class="border rounded mb-2" ${open ? 'open' : ''}>
        <summary class="px-3 py-2 cursor-pointer font-semibold ${cls}">${escHtml(label)} (${items.length})</summary>
        <div class="px-3 pb-2 text-gray-700 text-xs font-mono space-y-0.5">${items.map(i => `<div>${escHtml(String(i))}</div>`).join('')}</div>
    </details>`;
}

function scPreviewHtml(r) {
    if (!r) return '<p class="text-gray-500">No result.</p>';
    let html = `<p class="text-xs text-gray-400 mb-3">Generated ${formatDatetime(r.generated_at)}</p>`;
    if (r.error) html += `<div class="bg-red-50 border border-red-200 text-red-800 rounded p-3 mb-3">${escHtml(r.error)}</div>`;

    for (const p of r.pending_removals || []) {
        html += `<div class="border border-red-200 rounded-lg p-3 mb-3">
            <div class="font-semibold text-red-700 mb-2">Pending removal: ${escHtml(p.name || 'Sync')} (sync ${escHtml(p.reason || '')})</div>
            ${scPreviewList('Shortcut will be removed from', p.users, 'text-red-700')}
        </div>`;
    }

    const syncs = r.syncs || [];
    if (!syncs.length && !(r.pending_removals || []).length) html += '<p class="text-gray-500">No syncs configured.</p>';

    for (const s of syncs) {
        if (s.disabled) {
            html += `<div class="border rounded-lg p-3 mb-3 bg-gray-50">
                <span class="font-semibold text-gray-700">${escHtml(s.name || '')}</span>
                <span class="text-gray-500"> is paused (disabled). No changes.</span></div>`;
            continue;
        }
        html += `<div class="border rounded-lg p-3 mb-3">
            <div class="font-semibold text-gray-800">${escHtml(s.name || '')}
                ${s.shortcut_name ? `<span class="font-normal text-gray-500">→ "${escHtml(s.shortcut_name)}"</span>` : ''}</div>`;
        if (s.fatal) {
            html += `<div class="bg-red-50 border border-red-200 text-red-800 rounded p-2 mt-2">${escHtml(s.fatal)}
                     <div class="text-xs mt-1">Nothing will be created or removed for this sync.</div></div></div>`;
            continue;
        }
        html += `<div class="text-xs text-gray-500 mb-2">${s.target_count} eligible target user${s.target_count === 1 ? '' : 's'}</div>`;
        if (s.guard_tripped) {
            html += `<div class="bg-red-50 border border-red-300 text-red-800 rounded p-3 mb-2">
                <div class="font-semibold">Removal guard: ${escHtml(s.guard_detail)}.</div>
                <div class="text-xs mt-1">These users will <strong>not</strong> be removed until you allow it.
                    Check the sync's targets first, because an emptied or mistyped group causes exactly this.</div>
                ${scCanWrite() ? `<button type="button" id="sc-force-${s.id}" onclick="scAllowRemovals('${s.id}', ${s.removed.length})"
                    class="mt-2 bg-red-600 hover:bg-red-700 text-white text-xs font-bold py-1.5 px-3 rounded transition">
                    Allow these ${s.removed.length} removals on the next run</button>` : ''}
            </div>`;
            html += scPreviewList('Blocked removals', s.removed, 'text-red-700');
        } else {
            html += scPreviewList('Would remove (no longer targeted)', s.removed, 'text-red-700', true);
        }
        html += scPreviewList('Would create', s.created, 'text-green-700', true);
        html += scPreviewList('Already has the shortcut', s.existing, 'text-gray-600');
        html += scPreviewList('Skipped: OneDrive not provisioned yet', s.skipped, 'text-amber-700');
        html += scPreviewList('Name conflict: unrelated item, left untouched', s.conflict, 'text-amber-700');
        html += scPreviewList('Errors', s.errors, 'text-red-700', true);
        html += scPreviewList('Warnings', s.warnings, 'text-amber-700');
        const changes = (s.created || []).length + (s.guard_tripped ? 0 : (s.removed || []).length);
        if (!changes && !(s.errors || []).length) html += '<div class="text-green-700 text-xs">✓ Up to date. No changes needed.</div>';
        html += '</div>';
    }
    return html;
}

async function scAllowRemovals(id, count) {
    if (!confirm(`Allow ${count} shortcut removal${count === 1 ? '' : 's'} on the next run?\n\n` +
                 'This applies once. Only the shortcut is removed; the SharePoint library and its files are not affected.')) return;
    try {
        const resp = await fetch(`/services/onedrive-shortcuts/force-removals/${id}`, { method: 'POST' });
        const result = await resp.json();
        if (!resp.ok || !result.success) { showNotification(result.error || 'Failed', 'error'); return; }
        _scState = result.state || _scState;
        const btn = document.getElementById(`sc-force-${id}`);
        if (btn) { btn.disabled = true; btn.textContent = 'Allowed: click ▶ Run Now (or wait for the schedule) to apply'; }
        showNotification('Removals allowed for the next run', 'success');
    } catch (e) {
        showNotification('Network error', 'error');
    }
}
