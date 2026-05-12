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
    ['schedule', 'notifications', 'logs'].forEach(t => {
        const btn = document.getElementById(`tab-btn-${name}-${t}`);
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
    const d = new Date(iso.replace(/(\.\d{3})\d+/, '$1'));
    if (isNaN(d)) return iso.substring(0, 19).replace('T', ' ');
    return new Intl.DateTimeFormat('en-CA', {
        timeZone: 'America/Los_Angeles',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: 'numeric', minute: '2-digit', second: '2-digit',
        hour12: true,
    }).format(d).replace(',', '');
}

function escHtml(str) {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}
