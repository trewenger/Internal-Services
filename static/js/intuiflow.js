// intuiflow.js — Intuiflow page JS
// Bootstrap data injected by the template: window.INTUIFLOW_CONFIG

const PIPELINE_NAMES = new Set(['full-sync', 'partial-sync']);
const SHORT_INV_NAMES = new Set(['full-sync', 'partial-sync', 'close-work-orders']);

const _logsCache   = {};  // { [name]: {logs, log_stats, errors, error_stats} }
const _logsLoaded  = {};  // { [name]: true }
const _activeTab   = {};  // { [name]: 'schedule'|'notifications'|'logs' }
const _cardOpen    = {};  // { [name]: bool }

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
    const body    = document.getElementById(`card-body-${name}`);
    const chevron = document.getElementById(`chevron-${name}`);
    _cardOpen[name] = !_cardOpen[name];

    if (_cardOpen[name]) {
        body.classList.remove('hidden');
        chevron.classList.add('rotate-180');
        if (!_activeTab[name]) {
            // Pipelines default to schedule tab; modules default to notifications
            switchTab(name, PIPELINE_NAMES.has(name) ? 'schedule' : 'notifications');
        }
    } else {
        body.classList.add('hidden');
        chevron.classList.remove('rotate-180');
    }
}

// --------------------------------- Tab switching ------------------------------------ //

function switchTab(name, tab) {
    _activeTab[name] = tab;
    const allTabs = PIPELINE_NAMES.has(name)
        ? ['schedule', 'notifications', 'logs']
        : ['notifications', 'logs'];

    allTabs.forEach(t => {
        const btn   = document.getElementById(`tab-btn-${name}-${t}`);
        const panel = document.getElementById(`tab-panel-${name}-${t}`);
        if (!btn || !panel) return;
        const active = t === tab;
        btn.classList.toggle('border-blue-500', active);
        btn.classList.toggle('text-blue-600', active);
        btn.classList.toggle('font-semibold', active);
        btn.classList.toggle('border-transparent', !active);
        btn.classList.toggle('text-gray-500', !active);
        panel.classList.toggle('hidden', !active);
    });

    if (tab === 'logs' && !_logsLoaded[name]) loadLogs(name);
}

// --------------------------------- Run Now ----------------------------------------- //

async function runNow(name) {
    const btn = document.getElementById(`run-btn-${name}`);
    btn.disabled = true;
    btn.textContent = 'Starting...';
    updateStatusBadge(name, 'running');

    try {
        const resp   = await fetch(`/intuiflow/run/${name}`, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
        const result = await resp.json();

        if (resp.ok && result.success) {
            btn.textContent = 'Running...';
            pollStatus(name);
        } else {
            showNotification(result.error || 'Failed to start', 'error');
            btn.disabled = false;
            btn.textContent = '▶ Run Now';
            updateStatusBadge(name, window.INTUIFLOW_CONFIG[name]?.last_status || null);
        }
    } catch (e) {
        showNotification('Error starting run', 'error');
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
            const resp   = await fetch('/intuiflow/status');
            const result = await resp.json();
            const cfg    = result.config[name];

            if (!cfg.running) {
                updateEntryUI(name, cfg);
                _logsLoaded[name] = false;
                const label     = cfg.label || name;
                const isWarning = cfg.last_status === 'short-inventory' || cfg.last_status === 'default-location';
                showNotification(
                    cfg.last_status === 'success' ? `${label} completed successfully`
                    : isWarning                   ? `${label} completed with warnings`
                                                  : `${label} finished with errors`,
                    cfg.last_status === 'success' ? 'success' : isWarning ? 'info' : 'error'
                );
            } else {
                pollStatus(name, attempts + 1);
            }
        } catch (e) {
            pollStatus(name, attempts + 1);
        }
    }, 5000);
}

function updateEntryUI(name, cfg) {
    const btn = document.getElementById(`run-btn-${name}`);
    btn.disabled = false;
    btn.textContent = '▶ Run Now';

    updateStatusBadge(name, cfg.last_status);

    const lastRunEl = document.getElementById(`last-run-${name}`);
    if (lastRunEl && cfg.last_run) lastRunEl.textContent = formatDatetime(cfg.last_run);

    const nextRunEl = document.getElementById(`next-run-${name}`);
    if (nextRunEl) nextRunEl.textContent = cfg.next_run ? formatDatetime(cfg.next_run) : '—';

    if (window.INTUIFLOW_CONFIG[name]) Object.assign(window.INTUIFLOW_CONFIG[name], cfg);
}

function updateStatusBadge(name, status) {
    const el = document.getElementById(`status-badge-${name}`);
    if (!el) return;
    const badges = {
        running:            'bg-yellow-100 text-yellow-800',
        success:            'bg-green-100 text-green-800',
        error:              'bg-red-100 text-red-800',
        'short-inventory':  'bg-yellow-100 text-yellow-800',
        'default-location': 'bg-yellow-100 text-yellow-800',
    };
    const labels = {
        running:            'Running...',
        success:            'Last run: Success',
        error:              'Last run: Error',
        'short-inventory':  'Last run: Warning - short inventory alert',
        'default-location': 'Last run: Warning - invalid default location alert',
    };
    const cls  = badges[status] || 'bg-gray-100 text-gray-600';
    const text = labels[status] || 'Never run';
    el.innerHTML = `<span class="${cls} text-xs font-bold px-3 py-1 rounded-full">${text}</span>`;
}

// --------------------------------- Schedule tab ------------------------------------- //

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
        document.getElementById(`sched-${t}-${name}`).classList.toggle('hidden', !active);
    });
}

function saveSchedule(name) {
    const type    = document.getElementById(`schedule-type-${name}`).value;
    const enabled = document.getElementById(`enabled-toggle-input-${name}`).checked;
    let payload   = { schedule_type: type, enabled };

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
        const day  = document.getElementById(`weekly-day-${name}`).value;
        const time = document.getElementById(`weekly-time-${name}`).value;
        if (!time) { showNotification('Please select a time', 'error'); return; }
        const [hour, minute] = time.split(':').map(Number);
        payload.schedule_type = 'cron';
        payload.schedule_cron = { day_of_week: day, hour, minute };

    } else if (type === 'custom') {
        const expr  = document.getElementById(`custom-cron-${name}`).value.trim();
        if (!expr) { showNotification('Please enter a cron expression', 'error'); return; }
        const parts = expr.split(/\s+/);
        if (parts.length !== 5) { showNotification('Cron expression must have 5 fields (e.g. 0 9 * * 1-5)', 'error'); return; }
        payload.schedule_type = 'cron';
        payload.schedule_cron = { minute: parts[0], hour: parts[1], day: parts[2], month: parts[3], day_of_week: parts[4] };
    }

    _putConfig(name, payload, (result) => {
        const cfg = result.config;
        showNotification(cfg.enabled ? `${cfg.label}: schedule saved` : `${cfg.label}: schedule disabled`, 'success');
        const nextRunEl = document.getElementById(`next-run-${name}`);
        if (nextRunEl) nextRunEl.textContent = cfg.next_run ? formatDatetime(cfg.next_run) : '—';
        if (window.INTUIFLOW_CONFIG[name]) Object.assign(window.INTUIFLOW_CONFIG[name], cfg);
    });
}

// --------------------------------- Log tab ----------------------------------------- //

async function loadLogs(name) {
    if (_logsLoaded[name]) { renderLogTab(name, 'audit'); renderLogTab(name, 'error'); return; }
    const panel = document.getElementById(`log-loading-${name}`);
    if (panel) panel.classList.remove('hidden');

    try {
        const resp   = await fetch(`/intuiflow/logs/${name}`);
        const result = await resp.json();
        if (resp.ok && result.success) {
            _logsCache[name]  = result.data;
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
    const isAudit  = tab === 'audit';
    const contentEl = document.getElementById(`log-entries-${name}-${isAudit ? 'audit' : 'error'}`);
    if (!contentEl) return;

    const cached = _logsCache[name];
    if (!cached) { contentEl.innerHTML = '<p class="text-gray-400 text-sm">Loading...</p>'; return; }

    const entries = isAudit ? cached.logs.filter(e => e.status !== 'error') : cached.errors;
    const badgeId = isAudit ? `log-count-badge-${name}` : `error-count-badge-${name}`;
    const badgeEl = document.getElementById(badgeId);
    if (badgeEl) badgeEl.textContent = entries ? entries.length : 0;

    if (!entries || entries.length === 0) {
        contentEl.innerHTML = '<p class="text-gray-400 text-sm italic">No records yet.</p>';
        return;
    }

    contentEl.innerHTML = entries.map(e => {
        let statusCls  = undefined
        if (e.status === 'success') {
            statusCls = 'bg-green-100 text-green-800'
        }else if (e.status === 'short-inventory' || e.status === 'default-location') {
            statusCls = 'bg-yellow-100 text-yellow-800'
        } else {
            statusCls = 'bg-red-100 text-red-800';
        }
        const triggerCls = e.triggered_by === 'manual' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700';

        let logRows = '';
        if (e.log_data) {
            for (const [label, value] of Object.entries(e.log_data)) {
                if (Array.isArray(value)) {
                    // Fatal error: { "key: fatal": ["error string"] }
                    logRows += `<div class="mb-2"><span class="font-bold text-gray-700">${escHtml(label)}:</span>`;
                    for (const msg of value) {
                        logRows += `<div class="ml-4 text-gray-600">${escHtml(String(msg))}</div>`;
                    }
                    logRows += '</div>';
                } else {
                    // Nested: { "Module Label (STATUS)": { "Func Name": ["messages"] } }
                    logRows += `<div class="mb-3"><div class="font-bold text-gray-800 border-b border-gray-300 pb-1 mb-1">${escHtml(label)}</div>`;
                    for (const [func, messages] of Object.entries(value)) {
                        logRows += `<div class="mb-1 ml-2"><span class="font-semibold text-gray-700">${escHtml(func)}:</span>`;
                        for (const msg of messages) {
                            logRows += `<div class="ml-4 text-gray-600">${escHtml(String(msg))}</div>`;
                        }
                        logRows += '</div>';
                    }
                    logRows += '</div>';
                }
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
    const body  = headerEl.nextElementSibling;
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
        ? `/intuiflow/logs/${name}/errors`
        : `/intuiflow/logs/${name}`;
    try {
        const resp   = await fetch(url, { method: 'DELETE' });
        const result = await resp.json();
        if (!resp.ok || !result.success) { showNotification(result.error || 'Failed to clear', 'error'); return; }
        if (type === 'errors') {
            if (_logsCache[name]) { _logsCache[name].errors = []; _logsCache[name].error_stats = { total_errors: 0, last_error: null }; }
        } else {
            if (_logsCache[name]) { _logsCache[name].logs = []; _logsCache[name].log_stats = { total_runs: 0, last_run: null }; }
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
    const mode       = document.querySelector(`input[name="notify-mode-${name}"]:checked`)?.value || 'none';
    const chips      = document.querySelectorAll(`#recipient-chips-${name} [data-email]`);
    const recipients = Array.from(chips).map(c => c.dataset.email);

    if (mode !== 'none' && recipients.length === 0) {
        showNotification('Add at least one recipient before enabling notifications', 'error');
        return;
    }

    const payload = { notify_mode: mode, notify_recipients: recipients };

    // Include short inv fields if this card has them
    const shortInvRadio = document.querySelector(`input[name="short-inv-enabled-${name}"]:checked`);
    if (shortInvRadio) {
        const shortInvEnabled    = shortInvRadio.value === 'on';
        const shortInvChips      = document.querySelectorAll(`#short-inv-chips-${name} [data-email]`);
        const shortInvRecipients = Array.from(shortInvChips).map(c => c.dataset.email);
        if (shortInvEnabled && shortInvRecipients.length === 0) {
            showNotification('Add at least one short inventory recipient before enabling short inventory alerts', 'error');
            return;
        }
        payload.short_inv_notify_enabled    = shortInvEnabled;
        payload.short_inv_notify_recipients = shortInvRecipients;
    }

    // Include def location fields if this card has them
    const defLocRadio = document.querySelector(`input[name="def-loc-enabled-${name}"]:checked`);
    if (defLocRadio) {
        const defLocEnabled    = defLocRadio.value === 'on';
        const defLocChips      = document.querySelectorAll(`#def-loc-chips-${name} [data-email]`);
        const defLocRecipients = Array.from(defLocChips).map(c => c.dataset.email);
        if (defLocEnabled && defLocRecipients.length === 0) {
            showNotification('Add at least one invalid default location recipient before enabling default location alerts', 'error');
            return;
        }
        payload.def_loc_notify_enabled    = defLocEnabled;
        payload.def_loc_notify_recipients = defLocRecipients;
    }

    _putConfig(name, payload, (result) => {
        showNotification(`${result.config.label}: notification settings saved`, 'success');
        if (window.INTUIFLOW_CONFIG[name]) Object.assign(window.INTUIFLOW_CONFIG[name], result.config);
    });
}

function addRecipient(name) {
    const input = document.getElementById(`recipient-input-${name}`);
    const email = input.value.trim();
    if (!email || !email.includes('@')) { showNotification('Enter a valid email address', 'error'); return; }

    const existing = Array.from(document.querySelectorAll(`#recipient-chips-${name} [data-email]`)).map(c => c.dataset.email);
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

// ------------------------------- Def. Location notifications ------------------------ //

function addDefLocationRecipient(name) {
    const input = document.getElementById(`def-loc-input-${name}`);
    const email = input.value.trim();
    if (!email || !email.includes('@')) { showNotification('Enter a valid email address', 'error'); return; }

    const existing = Array.from(document.querySelectorAll(`#def-loc-chips-${name} [data-email]`)).map(c => c.dataset.email);
    if (existing.includes(email)) { showNotification('That email is already in the list', 'error'); return; }

    const chip = document.createElement('span');
    chip.dataset.email = email;
    chip.className = 'inline-flex items-center gap-1 bg-purple-100 text-purple-800 text-xs font-semibold px-3 py-1 rounded-full';
    chip.innerHTML = `${escHtml(email)} <button type="button" onclick="removeDefLocationRecipient(this)" class="ml-1 text-purple-500 hover:text-red-500 font-bold leading-none">×</button>`;
    document.getElementById(`def-loc-chips-${name}`).appendChild(chip);
    input.value = '';
}

function removeDefLocationRecipient(btn) {
    btn.closest('[data-email]').remove();
}

// --------------------------------- Short inv notifications -------------------------- //

function addShortInvRecipient(name) {
    const input = document.getElementById(`short-inv-input-${name}`);
    const email = input.value.trim();
    if (!email || !email.includes('@')) { showNotification('Enter a valid email address', 'error'); return; }

    const existing = Array.from(document.querySelectorAll(`#short-inv-chips-${name} [data-email]`)).map(c => c.dataset.email);
    if (existing.includes(email)) { showNotification('That email is already in the list', 'error'); return; }

    const chip = document.createElement('span');
    chip.dataset.email = email;
    chip.className = 'inline-flex items-center gap-1 bg-orange-100 text-orange-800 text-xs font-semibold px-3 py-1 rounded-full';
    chip.innerHTML = `${escHtml(email)} <button type="button" onclick="removeShortInvRecipient(this)" class="ml-1 text-orange-500 hover:text-red-500 font-bold leading-none">×</button>`;
    document.getElementById(`short-inv-chips-${name}`).appendChild(chip);
    input.value = '';
}

function removeShortInvRecipient(btn) {
    btn.closest('[data-email]').remove();
}

// --------------------------------- Shared helpers ----------------------------------- //

function _putConfig(name, payload, onSuccess) {
    fetch(`/intuiflow/config/${name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    })
    .then(r => r.json().then(d => ({ ok: r.ok, data: d })))
    .then(({ ok, data }) => {
        if (ok && data.success) { onSuccess(data); }
        else { showNotification(data.error || 'Failed to save', 'error'); }
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
    for (const [name, cfg] of Object.entries(window.INTUIFLOW_CONFIG || {})) {
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
