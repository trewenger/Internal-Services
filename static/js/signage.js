'use strict';

const canWrite = window.SIGNAGE_CAN_WRITE ?? false;

const _cardOpen     = {};
const _activeTab    = {};
const _slideshows   = {};
const _media        = {};
const _pendingFiles = [];
const _cardMedia    = {};   // { cardKey: [filename, ...] }

let _dragGalleryFile  = null; // filename being dragged from the gallery
let _dragCardItem     = null; // { name, index } being dragged within a card
let _galleryOffset    = 0;    // current translateX offset in px
let _galleryAllItems  = [];   // full unfiltered item list
const _CARD_SLOT      = 156;  // card width (144) + gap (12)

const _sheetCardOpen  = {};   // { key: bool }
let   _sheets         = {};   // { key: cfg } — kept in sync with server

const VIDEO_EXTS_JS = new Set(['.mp4', '.mov', '.avi', '.mkv', '.webm']);

// Shared insertion-point indicator element (moved in DOM during drag-over)
const _dropIndicator = (() => {
    const el = document.createElement('div');
    el.className = 'h-0.5 bg-blue-400 rounded pointer-events-none mx-1 my-0.5';
    return el;
})();

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

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
        inactive: 'bg-gray-100 text-gray-600 border border-gray-300',
    };
    const cls = styles[status] || styles.inactive;
    const label = status.charAt(0).toUpperCase() + status.slice(1);
    return `<span class="text-xs font-semibold px-2 py-0.5 rounded-full ${cls}">${label}</span>`;
}

function showNotification(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `fixed top-6 right-6 z-50 px-5 py-3 rounded-lg shadow-lg text-white font-semibold text-sm transition-all ${
        type === 'error' ? 'bg-red-600' : 'bg-green-600'
    }`;
    toast.classList.remove('hidden');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => toast.classList.add('hidden'), 4000);
}

function toggleEnabled(name) {
    const btn  = document.getElementById(`toggle-enabled-${name}`);
    const knob = document.getElementById(`toggle-knob-${name}`);
    const now  = btn.dataset.enabled !== 'true';
    btn.dataset.enabled = now ? 'true' : 'false';
    btn.classList.toggle('bg-blue-500', now);
    btn.classList.toggle('bg-gray-300', !now);
    knob.classList.toggle('translate-x-6', now);
    knob.classList.toggle('translate-x-1', !now);
}

function toggleCard(name) {
    const body = document.getElementById(`card-body-${name}`);
    const chevron = document.getElementById(`chevron-${name}`);
    _cardOpen[name] = !_cardOpen[name];

    if (_cardOpen[name]) {
        body.classList.remove('hidden');
        chevron.classList.add('rotate-180');
        switchTab(name, _activeTab[name] || 'settings');
    } else {
        body.classList.add('hidden');
        chevron.classList.remove('rotate-180');
    }
}

function switchTab(name, tab) {
    _activeTab[name] = tab;
    ['settings', 'media'].forEach(t => {
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
        const res = await fetch('/api/get-data');
        if (!res.ok) return;

        const data = await res.json();
        if (!data.success) return;

        _slideshows = {};
        data.slideshows.forEach(s => { _slideshows[s.name] = s; });

        _media = {};
        data.media.forEach(s => { _slideshows[s.name] = s; });

        renderContent(data.slideshows, data.media);
    } catch (e) {
        // silent — will retry on next interval
    }
}

// ─── Rendering ────────────────────────────────────────────────────────────────

function renderSlideshows(slideshows, media) {
    // update the HTML to display the content.
    // slideshows:
    for (let i = 0; i < length(slideshows); i++) {

    }
}

// ─── Add Modal ────────────────────────────────────────────────────────────────

// ─── Media Gallery ────────────────────────────────────────────────────────────

async function loadMedia() {
    try {
        const res = await fetch('/signage/api/media');
        if (!res.ok) return;
        const data = await res.json();
        if (!data.success) return;
        renderMediaGallery(data.media || []);
    } catch (e) {
        // silent — will retry on next interval
    }
}

function renderMediaGallery(items) {
    const gallery  = document.getElementById('media-gallery');
    const empty    = document.getElementById('media-empty');
    const loading  = document.getElementById('media-loading');

    _galleryAllItems = items;
    _galleryOffset   = 0;
    gallery.style.transform = 'translateX(0)';

    loading.classList.add('hidden');
    gallery.querySelectorAll('.media-card').forEach(el => el.remove());

    if (items.length === 0) {
        empty.classList.remove('hidden');
        updateGalleryArrows();
        return;
    }
    empty.classList.add('hidden');

    items.forEach(item => {
        const url  = `/signage/media/file/${encodeURIComponent(item.filename)}`;
        const card = document.createElement('div');
        card.className = 'media-card group w-36 shrink-0 bg-white rounded-lg shadow-sm border overflow-hidden cursor-grab hover:shadow-md transition';
        card.draggable = true;
        card.ondragstart = (e) => { _dragGalleryFile = item.filename; _dragCardItem = null; e.dataTransfer.effectAllowed = 'copy'; };
        card.ondragend   = ()  => { _dragGalleryFile = null; };
        card.onclick = () => { if (!_dragGalleryFile) openPreviewModal(item); };

        const thumb = document.createElement('div');
        thumb.className = 'aspect-square bg-gray-100 overflow-hidden relative';

        if (item.type === 'image') {
            const img = document.createElement('img');
            img.src = url;
            img.alt = item.filename;
            img.className = 'w-full h-full object-cover';
            img.loading = 'lazy';
            thumb.appendChild(img);
        } else {
            const video = document.createElement('video');
            video.src = url;
            video.className = 'w-full h-full object-cover';
            video.preload = 'metadata';
            video.muted = true;
            thumb.appendChild(video);
            const overlay = document.createElement('div');
            overlay.className = 'absolute inset-0 flex items-center justify-center bg-black bg-opacity-20';
            overlay.innerHTML = `<svg class="w-10 h-10 text-white opacity-80" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clip-rule="evenodd"/>
            </svg>`;
            thumb.appendChild(overlay);
        }

        if (canWrite) {
            const delBtn = document.createElement('button');
            delBtn.className = 'absolute top-1 right-1 w-5 h-5 flex items-center justify-center rounded-full bg-black bg-opacity-50 text-white text-xs opacity-0 group-hover:opacity-100 hover:bg-red-600 transition z-10';
            delBtn.textContent = '✕';
            delBtn.title = 'Delete from library';
            delBtn.onclick = (e) => { e.stopPropagation(); deleteMediaFile(item.filename); };
            thumb.appendChild(delBtn);
        }

        const info = document.createElement('div');
        info.className = 'p-2';
        info.innerHTML = `<p class="text-xs font-medium text-gray-700 truncate" title="${escapeHtml(item.filename)}">${escapeHtml(item.filename)}</p>
                          <p class="text-xs text-gray-400">${formatBytes(item.size)}</p>`;

        card.appendChild(thumb);
        card.appendChild(info);
        gallery.appendChild(card);
    });

    updateGalleryArrows();
}

function galleryScroll(dir) {
    const viewport  = document.getElementById('media-gallery-viewport');
    const gallery   = document.getElementById('media-gallery');
    const viewWidth = viewport.clientWidth;
    const totalW    = _galleryAllItems.length * _CARD_SLOT - 12; // subtract trailing gap
    const maxOffset = Math.max(0, totalW - viewWidth);
    const pageStep  = Math.max(1, Math.floor(viewWidth / _CARD_SLOT)) * _CARD_SLOT;

    _galleryOffset = Math.max(0, Math.min(maxOffset, _galleryOffset + dir * pageStep));
    gallery.style.transform = `translateX(-${_galleryOffset}px)`;
    updateGalleryArrows(maxOffset);
}

function updateGalleryArrows(maxOffset) {
    if (maxOffset === undefined) {
        const viewport = document.getElementById('media-gallery-viewport');
        const totalW   = _galleryAllItems.length * _CARD_SLOT - 12;
        maxOffset      = Math.max(0, totalW - viewport.clientWidth);
    }
    const prev = document.getElementById('gallery-prev');
    const next = document.getElementById('gallery-next');
    if (prev) prev.disabled = _galleryOffset <= 0;
    if (next) next.disabled = _galleryOffset >= maxOffset;
}

// ─── Preview Modal ────────────────────────────────────────────────────────────

function openPreviewModal(item) {
    const modal    = document.getElementById('media-preview-modal');
    const content  = document.getElementById('media-preview-content');
    const label    = document.getElementById('media-preview-filename');
    const url      = `/signage/media/file/${encodeURIComponent(item.filename)}`;

    content.innerHTML = '';

    if (item.type === 'image') {
        const img = document.createElement('img');
        img.src = url;
        img.alt = item.filename;
        img.className = 'max-w-full max-h-[80vh] rounded-lg shadow-lg';
        content.appendChild(img);
    } else {
        const video = document.createElement('video');
        video.src = url;
        video.controls = true;
        video.autoplay = true;
        video.className = 'max-w-full max-h-[80vh] rounded-lg shadow-lg';
        content.appendChild(video);
    }

    label.textContent = item.filename;
    modal.classList.remove('hidden');
}

function closePreviewModal() {
    const modal   = document.getElementById('media-preview-modal');
    const content = document.getElementById('media-preview-content');
    modal.classList.add('hidden');
    content.innerHTML = ''; // stops video playback
}

async function deleteMediaFile(filename) {
    if (!confirm(`Delete "${filename}" from the media library? This cannot be undone.`)) return;
    try {
        const res  = await fetch(`/signage/api/media/delete/${encodeURIComponent(filename)}`, { method: 'POST' });
        const data = await res.json();
        if (!data.success) { showNotification(data.error || 'Delete failed.', 'error'); return; }
        showNotification(`"${filename}" deleted.`);
        loadMedia();
    } catch (e) {
        showNotification('Delete failed.', 'error');
    }
}

const ALLOWED_UPLOAD_EXTS = new Set(['.jpg','.jpeg','.png','.gif','.webp','.bmp','.mp4','.mov','.avi','.mkv','.webm']);

function openAddMediaModal() {
    _pendingFiles.splice(0);
    document.getElementById('file-input').value = '';
    document.getElementById('upload-file-list').innerHTML = '';
    document.getElementById('upload-file-list').classList.add('hidden');
    document.getElementById('upload-btn').disabled = true;
    document.getElementById('upload-btn').textContent = 'Upload';
    document.getElementById('add-media-modal').classList.remove('hidden');
}

function closeAddMediaModal() {
    document.getElementById('add-media-modal').classList.add('hidden');
}

function onDragOver(e) {
    e.preventDefault();
    document.getElementById('drop-zone').classList.add('border-blue-400', 'bg-blue-50');
}

function onDragLeave(e) {
    if (!e.currentTarget.contains(e.relatedTarget)) {
        document.getElementById('drop-zone').classList.remove('border-blue-400', 'bg-blue-50');
    }
}

function onDrop(e) {
    e.preventDefault();
    document.getElementById('drop-zone').classList.remove('border-blue-400', 'bg-blue-50');
    queueFiles(e.dataTransfer.files);
}

function onFileInputChange(e) {
    queueFiles(e.target.files);
}

function queueFiles(fileList) {
    for (const file of fileList) {
        const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
        if (!ALLOWED_UPLOAD_EXTS.has(ext)) continue;
        if (_pendingFiles.some(f => f.name === file.name && f.size === file.size)) continue;
        _pendingFiles.push(file);
    }
    renderPendingFiles();
}

function removePendingFile(index) {
    _pendingFiles.splice(index, 1);
    renderPendingFiles();
}

function renderPendingFiles() {
    const list = document.getElementById('upload-file-list');
    const btn  = document.getElementById('upload-btn');

    if (_pendingFiles.length === 0) {
        list.classList.add('hidden');
        btn.disabled = true;
        return;
    }

    list.classList.remove('hidden');
    btn.disabled = false;
    list.innerHTML = '';

    _pendingFiles.forEach((file, i) => {
        const row = document.createElement('div');
        row.className = 'flex items-center gap-2 text-sm bg-gray-50 rounded px-3 py-2';
        row.innerHTML = `
            <span class="flex-1 truncate text-gray-700" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>
            <span class="text-xs text-gray-400 shrink-0">${formatBytes(file.size)}</span>
            <button onclick="removePendingFile(${i})" class="shrink-0 text-gray-400 hover:text-red-500 leading-none">✕</button>
        `;
        list.appendChild(row);
    });
}

async function submitUpload() {
    if (_pendingFiles.length === 0) return;
    const btn = document.getElementById('upload-btn');
    btn.disabled = true;
    btn.textContent = 'Uploading…';

    const form = new FormData();
    _pendingFiles.forEach(f => form.append('files', f));

    try {
        const res  = await fetch('/signage/api/media/upload', { method: 'POST', body: form });
        const data = await res.json();
        if (!data.success) { showNotification(data.error || 'Upload failed.', 'error'); btn.disabled = false; btn.textContent = 'Upload'; return; }
        const failed = (data.results || []).filter(r => !r.success);
        const ok     = data.results.length - failed.length;
        if (failed.length === 0) {
            showNotification(`${ok} file${ok !== 1 ? 's' : ''} uploaded.`);
        } else {
            showNotification(`${ok} uploaded, ${failed.length} failed (invalid type).`, 'error');
        }
        closeAddMediaModal();
        loadMedia();
    } catch (e) {
        showNotification('Upload failed.', 'error');
        btn.disabled = false;
        btn.textContent = 'Upload';
    }
}

function openAddSlideshowModal() {
    document.getElementById('new-slideshow-name').value        = '';
    document.getElementById('new-slideshow-description').value = '';
    document.getElementById('new-slideshow-speed').value       = '20';
    document.getElementById('create-slideshow-btn').disabled   = false;
    document.getElementById('create-slideshow-btn').textContent = 'Create';
    document.getElementById('add-slideshow-modal').classList.remove('hidden');
    setTimeout(() => document.getElementById('new-slideshow-name').focus(), 50);
}

function closeAddSlideshowModal() {
    document.getElementById('add-slideshow-modal').classList.add('hidden');
}

async function submitAddSlideshow() {
    const name      = document.getElementById('new-slideshow-name').value.trim();
    const desc      = document.getElementById('new-slideshow-description').value.trim();
    const speedRaw  = parseInt(document.getElementById('new-slideshow-speed').value, 10);
    const speedSecs = isNaN(speedRaw) || speedRaw < 1 ? 20 : speedRaw;

    if (!name) {
        document.getElementById('new-slideshow-name').focus();
        showNotification('Name is required.', 'error');
        return;
    }

    const btn = document.getElementById('create-slideshow-btn');
    btn.disabled    = true;
    btn.textContent = 'Creating…';

    try {
        const res  = await fetch('/signage/api/slideshow/create', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ name, description: desc, speed_secs: speedSecs }),
        });
        const data = await res.json();
        if (!data.success) {
            showNotification(data.error || 'Create failed.', 'error');
            btn.disabled    = false;
            btn.textContent = 'Create';
            return;
        }
        closeAddSlideshowModal();
        window.location.reload();
    } catch (e) {
        showNotification('Create failed.', 'error');
        btn.disabled    = false;
        btn.textContent = 'Create';
    }
}

// ─── Assigned Media (card Media tab) ─────────────────────────────────────────

function renderAssignedMedia(name) {
    const zone  = document.getElementById(`media-assigned-zone-${name}`);
    if (!zone) return;
    const items = _cardMedia[name] || [];
    zone.innerHTML = '';

    if (items.length === 0) {
        const hint = document.createElement('p');
        hint.className = 'text-sm text-gray-400 text-center py-6 pointer-events-none select-none';
        hint.textContent = 'No files assigned — drag from the library below';
        zone.appendChild(hint);
        return;
    }

    items.forEach((filename, i) => {
        const isSheet = filename.startsWith('sheet:');
        const url     = isSheet ? null : `/signage/media/file/${encodeURIComponent(filename)}`;
        const ext     = isSheet ? '' : filename.slice(filename.lastIndexOf('.')).toLowerCase();
        const isVideo = !isSheet && VIDEO_EXTS_JS.has(ext);

        const row = document.createElement('div');
        row.className = 'flex items-center gap-3 p-2 bg-white rounded-lg border border-gray-200 mb-1.5 cursor-grab select-none';
        row.draggable = true;

        row.ondragstart = (e) => {
            _dragCardItem    = { name, index: i };
            _dragGalleryFile = null;
            e.dataTransfer.effectAllowed = 'move';
            setTimeout(() => row.classList.add('opacity-40'), 0);
        };
        row.ondragend = () => {
            _dragCardItem = null;
            row.classList.remove('opacity-40');
            clearDropIndicator();
        };
        row.ondragover = (e) => {
            const isCardDrag    = _dragCardItem && _dragCardItem.name === name;
            const isGalleryDrag = !!_dragGalleryFile;
            if (!isCardDrag && !isGalleryDrag) return;
            e.preventDefault();
            e.stopPropagation();
            showDropIndicator(row, e);
        };
        row.ondragleave = (e) => {
            if (!e.currentTarget.contains(e.relatedTarget)) clearDropIndicator();
        };
        row.ondrop = (e) => {
            e.preventDefault();
            e.stopPropagation();
            clearDropIndicator();
            if (_dragGalleryFile) {
                if (_cardMedia[name].includes(_dragGalleryFile)) { showNotification('Already in this slideshow.', 'error'); return; }
                const rect     = row.getBoundingClientRect();
                const insertAt = e.clientY < rect.top + rect.height / 2 ? i : i + 1;
                _cardMedia[name].splice(insertAt, 0, _dragGalleryFile);
                renderAssignedMedia(name);
            } else if (_dragCardItem && _dragCardItem.name === name) {
                reorderAssignedMedia(name, _dragCardItem.index, i, e);
            }
        };

        // Grip icon
        const grip = document.createElement('span');
        grip.className = 'text-gray-300 shrink-0';
        grip.innerHTML = `<svg class="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
            <circle cx="5" cy="3.5" r="1.3"/><circle cx="11" cy="3.5" r="1.3"/>
            <circle cx="5" cy="8"   r="1.3"/><circle cx="11" cy="8"   r="1.3"/>
            <circle cx="5" cy="12.5" r="1.3"/><circle cx="11" cy="12.5" r="1.3"/>
        </svg>`;

        // Thumbnail / icon
        const thumb = document.createElement('div');
        thumb.className = 'w-10 h-10 rounded overflow-hidden shrink-0 bg-gray-100 flex items-center justify-center';
        if (isSheet) {
            thumb.innerHTML = `<svg class="w-5 h-5 text-green-500" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                <rect x="3" y="3" width="18" height="18" rx="2" stroke-width="1.5"/>
                <path d="M3 9h18M3 15h18M9 3v18" stroke-width="1.5"/>
            </svg>`;
        } else if (isVideo) {
            const v = document.createElement('video');
            v.src = url; v.className = 'w-full h-full object-cover'; v.preload = 'metadata'; v.muted = true;
            thumb.appendChild(v);
        } else {
            const img = document.createElement('img');
            img.src = url; img.className = 'w-full h-full object-cover'; img.loading = 'lazy';
            thumb.appendChild(img);
        }

        // Label
        const displayName = isSheet
            ? (_sheets[filename.slice(6)]?.name || filename.slice(6))
            : filename;
        const label = document.createElement('span');
        label.className = 'flex-1 text-sm text-gray-700 truncate min-w-0';
        label.textContent = displayName;
        label.title = filename;

        // Remove button
        const removeBtn = document.createElement('button');
        removeBtn.className = 'shrink-0 text-gray-300 hover:text-red-500 transition leading-none';
        removeBtn.textContent = '✕';
        removeBtn.onclick = (e) => { e.stopPropagation(); removeAssignedMedia(name, i); };

        row.append(grip, thumb, label, removeBtn);
        zone.appendChild(row);
    });
}

function showDropIndicator(referenceEl, e) {
    const rect    = referenceEl.getBoundingClientRect();
    const isAbove = e.clientY < rect.top + rect.height / 2;
    referenceEl.parentNode.insertBefore(_dropIndicator, isAbove ? referenceEl : referenceEl.nextSibling);
}

function clearDropIndicator() {
    if (_dropIndicator.parentNode) _dropIndicator.parentNode.removeChild(_dropIndicator);
}

function reorderAssignedMedia(name, fromIndex, targetIndex, e) {
    const rect      = e.currentTarget.getBoundingClientRect();
    const dropAbove = e.clientY < rect.top + rect.height / 2;
    const items     = [..._cardMedia[name]];
    const [item]    = items.splice(fromIndex, 1);
    let insertAt    = fromIndex < targetIndex ? targetIndex - 1 : targetIndex;
    if (!dropAbove) insertAt++;
    items.splice(Math.max(0, Math.min(items.length, insertAt)), 0, item);
    _cardMedia[name] = items;
    renderAssignedMedia(name);
}

function removeAssignedMedia(name, index) {
    _cardMedia[name].splice(index, 1);
    renderAssignedMedia(name);
}

function onAssignedZoneDragOver(e, name) {
    const isCardDrag    = _dragCardItem && _dragCardItem.name === name;
    const isGalleryDrag = !!_dragGalleryFile;
    if (!isCardDrag && !isGalleryDrag) return;
    e.preventDefault();
    if (isGalleryDrag) document.getElementById(`media-assigned-zone-${name}`).classList.add('border-blue-400', 'bg-blue-50');
}

function onAssignedZoneDragLeave(e, name) {
    if (e.currentTarget.contains(e.relatedTarget)) return;
    document.getElementById(`media-assigned-zone-${name}`).classList.remove('border-blue-400', 'bg-blue-50');
    clearDropIndicator();
}

function onAssignedZoneDrop(e, name) {
    e.preventDefault();
    document.getElementById(`media-assigned-zone-${name}`).classList.remove('border-blue-400', 'bg-blue-50');
    clearDropIndicator();
    if (!_dragGalleryFile) return;
    if ((_cardMedia[name] || []).includes(_dragGalleryFile)) { showNotification('Already in this slideshow.', 'error'); return; }
    if (!_cardMedia[name]) _cardMedia[name] = [];
    _cardMedia[name].push(_dragGalleryFile);
    renderAssignedMedia(name);
}

// ─── Sheet Resources ──────────────────────────────────────────────────────────

function toggleSheetCard(key) {
    const body    = document.getElementById(`sheet-card-body-${key}`);
    const chevron = document.getElementById(`sheet-chevron-${key}`);
    _sheetCardOpen[key] = !_sheetCardOpen[key];
    body.classList.toggle('hidden', !_sheetCardOpen[key]);
    chevron.classList.toggle('rotate-180', !!_sheetCardOpen[key]);
}

function toggleSheetEnabled(key) {
    const btn  = document.getElementById(`sheet-toggle-enabled-${key}`);
    const knob = document.getElementById(`sheet-toggle-knob-${key}`);
    const now  = btn.dataset.enabled !== 'true';
    btn.dataset.enabled = now ? 'true' : 'false';
    btn.classList.toggle('bg-blue-500', now);
    btn.classList.toggle('bg-gray-300', !now);
    knob.classList.toggle('translate-x-6', now);
    knob.classList.toggle('translate-x-1', !now);
}

// Generic toggle for export option fields (landscape, fitwidth, gridlines)
function toggleSheetBool(key, field) {
    const btn  = document.getElementById(`sheet-toggle-${field}-${key}`);
    const knob = document.getElementById(`sheet-toggle-${field}-knob-${key}`);
    const now  = btn.dataset.enabled !== 'true';
    btn.dataset.enabled = now ? 'true' : 'false';
    btn.classList.toggle('bg-blue-500', now);
    btn.classList.toggle('bg-gray-300', !now);
    if (knob) {
        knob.classList.toggle('translate-x-6', now);
        knob.classList.toggle('translate-x-1', !now);
    }
}

async function saveSheetSettings(key) {
    const enabled       = document.getElementById(`sheet-toggle-enabled-${key}`).dataset.enabled === 'true';
    const name          = document.getElementById(`sheet-input-name-${key}`).value.trim();
    const desc          = document.getElementById(`sheet-input-description-${key}`).value.trim();
    const sheetId       = document.getElementById(`sheet-input-id-${key}`).value.trim();
    const interval      = parseInt(document.getElementById(`sheet-input-interval-${key}`).value, 10);
    const landscape     = document.getElementById(`sheet-toggle-landscape-${key}`).dataset.enabled === 'true';
    const fitWidth      = document.getElementById(`sheet-toggle-fitwidth-${key}`).dataset.enabled === 'true';
    const hideGridlines = document.getElementById(`sheet-toggle-gridlines-${key}`).dataset.enabled === 'true';
    const sheetGid      = document.getElementById(`sheet-input-gid-${key}`).value.trim() || '0';
    const exportRange   = document.getElementById(`sheet-input-range-${key}`).value.trim();

    if (!name)    { showNotification('Name is required.', 'error'); return; }
    if (!sheetId) { showNotification('Sheet ID is required.', 'error'); return; }

    try {
        const res  = await fetch(`/signage/api/sheet/${encodeURIComponent(key)}/update`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                name, description: desc, sheet_id: sheetId,
                refresh_interval_mins: interval, enabled,
                portrait: !landscape, fit_width: fitWidth,
                hide_gridlines: hideGridlines, sheet_gid: sheetGid, export_range: exportRange,
            }),
        });
        const data = await res.json();
        if (!data.success) { showNotification(data.error || 'Save failed.', 'error'); return; }
        _sheets[key] = data.config;
        document.getElementById(`sheet-header-name-${key}`).textContent = name;
        showNotification('Sheet settings saved.');
        populateSheetPickers();
    } catch (e) { showNotification('Save failed.', 'error'); }
}

async function refreshSheet(key) {
    try {
        const res  = await fetch(`/signage/api/sheet/${encodeURIComponent(key)}/refresh`, { method: 'POST' });
        const data = await res.json();
        if (!data.success) { showNotification(data.error || 'Refresh failed.', 'error'); return; }
        const label = document.getElementById(`sheet-last-fetched-${key}`);
        if (label && data.fetched_at) {
            const d = new Date(data.fetched_at);
            label.textContent = `Updated ${d.toLocaleTimeString()}`;
        }
        if (data.error) { showNotification(`Refreshed with error: ${data.error}`, 'error'); }
        else            { showNotification('Sheet refreshed — PNG updated.'); }
    } catch (e) { showNotification('Refresh failed.', 'error'); }
}

async function deleteSheet(key) {
    const displayName = document.getElementById(`sheet-header-name-${key}`)?.textContent || key;
    if (!confirm(`Delete "${displayName}"? This cannot be undone.`)) return;
    try {
        const res  = await fetch(`/signage/api/sheet/${encodeURIComponent(key)}/delete`, { method: 'POST' });
        const data = await res.json();
        if (!data.success) { showNotification(data.error || 'Delete failed.', 'error'); return; }
        delete _sheets[key];
        document.getElementById(`sheet-card-${key}`)?.remove();
        showNotification(`"${displayName}" deleted.`);
        populateSheetPickers();
    } catch (e) { showNotification('Delete failed.', 'error'); }
}

function toggleNewSheetBool(field) {
    const btn  = document.getElementById(`new-sheet-toggle-${field}`);
    const knob = document.getElementById(`new-sheet-toggle-${field}-knob`);
    const now  = btn.dataset.enabled !== 'true';
    btn.dataset.enabled = now ? 'true' : 'false';
    btn.classList.toggle('bg-blue-500', now);
    btn.classList.toggle('bg-gray-300', !now);
    if (knob) { knob.classList.toggle('translate-x-6', now); knob.classList.toggle('translate-x-1', !now); }
}

function _resetNewSheetToggle(field, defaultOn) {
    const btn  = document.getElementById(`new-sheet-toggle-${field}`);
    const knob = document.getElementById(`new-sheet-toggle-${field}-knob`);
    if (!btn) return;
    btn.dataset.enabled = defaultOn ? 'true' : 'false';
    btn.classList.toggle('bg-blue-500', defaultOn);
    btn.classList.toggle('bg-gray-300', !defaultOn);
    if (knob) { knob.classList.toggle('translate-x-6', defaultOn); knob.classList.toggle('translate-x-1', !defaultOn); }
}

function openAddSheetModal() {
    ['new-sheet-name', 'new-sheet-id', 'new-sheet-range'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    document.getElementById('new-sheet-interval').value = '15';
    document.getElementById('new-sheet-gid').value = '0';
    _resetNewSheetToggle('landscape', true);
    _resetNewSheetToggle('fitwidth',  true);
    _resetNewSheetToggle('gridlines', true);
    const btn = document.getElementById('create-sheet-btn');
    btn.disabled = false; btn.textContent = 'Create';
    document.getElementById('add-sheet-modal').classList.remove('hidden');
    setTimeout(() => document.getElementById('new-sheet-name').focus(), 50);
}

function closeAddSheetModal() {
    document.getElementById('add-sheet-modal').classList.add('hidden');
}

async function submitAddSheet() {
    const name          = document.getElementById('new-sheet-name').value.trim();
    const sheetId       = document.getElementById('new-sheet-id').value.trim();
    const interval      = parseInt(document.getElementById('new-sheet-interval').value, 10) || 15;
    const landscape     = document.getElementById('new-sheet-toggle-landscape').dataset.enabled === 'true';
    const fitWidth      = document.getElementById('new-sheet-toggle-fitwidth').dataset.enabled === 'true';
    const hideGridlines = document.getElementById('new-sheet-toggle-gridlines').dataset.enabled === 'true';
    const sheetGid      = document.getElementById('new-sheet-gid').value.trim() || '0';
    const exportRange   = document.getElementById('new-sheet-range').value.trim();

    if (!name)    { showNotification('Name is required.', 'error'); return; }
    if (!sheetId) { showNotification('Sheet ID is required.', 'error'); return; }

    const btn = document.getElementById('create-sheet-btn');
    btn.disabled = true; btn.textContent = 'Creating…';

    try {
        const res  = await fetch('/signage/api/sheet/create', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                name, sheet_id: sheetId, refresh_interval_mins: interval,
                portrait: !landscape, fit_width: fitWidth,
                hide_gridlines: hideGridlines, sheet_gid: sheetGid, export_range: exportRange,
            }),
        });
        const data = await res.json();
        if (!data.success) {
            showNotification(data.error || 'Create failed.', 'error');
            btn.disabled = false; btn.textContent = 'Create';
            return;
        }
        closeAddSheetModal();
        window.location.reload();
    } catch (e) {
        showNotification('Create failed.', 'error');
        btn.disabled = false; btn.textContent = 'Create';
    }
}

function populateSheetPickers() {
    // Update the "Add sheet resource…" dropdowns in every slideshow's media tab
    document.querySelectorAll('[id^="sheet-picker-wrap-"]').forEach(wrap => {
        const slideshowKey = wrap.id.replace('sheet-picker-wrap-', '');
        const select       = document.getElementById(`sheet-picker-${slideshowKey}`);
        if (!select) return;

        // Rebuild options
        select.innerHTML = '<option value="">Add sheet resource…</option>';
        Object.entries(_sheets).forEach(([key, cfg]) => {
            const opt = document.createElement('option');
            opt.value       = key;
            opt.textContent = cfg.name || key;
            select.appendChild(opt);
        });

        // Show/hide based on whether any sheets exist
        if (Object.keys(_sheets).length > 0) {
            wrap.classList.remove('hidden');
            // Wire up change handler (idempotent — replace each time)
            select.onchange = () => {
                const sheetKey = select.value;
                if (!sheetKey) return;
                select.value = '';
                const ref = `sheet:${sheetKey}`;
                if ((_cardMedia[slideshowKey] || []).includes(ref)) {
                    showNotification('Already in this slideshow.', 'error');
                    return;
                }
                if (!_cardMedia[slideshowKey]) _cardMedia[slideshowKey] = [];
                _cardMedia[slideshowKey].push(ref);
                renderAssignedMedia(slideshowKey);
            };
        } else {
            wrap.classList.add('hidden');
        }
    });
}

// ─── Edit Modal ───────────────────────────────────────────────────────────────

function openEditModal(name) {
    // need to complete. Opens the modal to edit the slideshow
}

async function saveSettings(name) {
    const enabled     = document.getElementById(`toggle-enabled-${name}`).dataset.enabled === 'true';
    const displayName = document.getElementById(`input-name-${name}`).value.trim();
    const description = document.getElementById(`input-description-${name}`).value.trim();
    const speedSecs   = parseInt(document.getElementById(`input-speed-${name}`).value, 10);

    if (!displayName) { showNotification('Name is required.', 'error'); return; }
    if (isNaN(speedSecs) || speedSecs < 1) { showNotification('Speed must be at least 1 second.', 'error'); return; }

    try {
        const res = await fetch(`/signage/api/update/${encodeURIComponent(name)}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name: displayName, description, speed_secs: speedSecs, enabled }),
        });
        const data = await res.json();
        if (!data.success) { showNotification(data.error || 'Save failed.', 'error'); return; }
        showNotification('Settings saved.');
        document.getElementById(`header-name-${name}`).textContent = displayName;
        document.getElementById(`header-desc-${name}`).textContent = description;
        const badge = document.getElementById(`status-badge-${name}`);
        badge.innerHTML = enabled
            ? '<span class="bg-green-100 text-green-800 text-xs font-bold px-3 py-1 rounded-full">Enabled</span>'
            : '<span class="bg-gray-100 text-gray-600 text-xs font-bold px-3 py-1 rounded-full">Disabled</span>';
    } catch (e) {
        showNotification('Save failed.', 'error');
    }
}

async function deleteSlideshow(name) {
    const displayName = document.getElementById(`header-name-${name}`)?.textContent || name;
    if (!confirm(`Delete "${displayName}"? This cannot be undone.`)) return;
    try {
        const res  = await fetch(`/signage/api/slideshow/${encodeURIComponent(name)}/delete`, { method: 'POST' });
        const data = await res.json();
        if (!data.success) { showNotification(data.error || 'Delete failed.', 'error'); return; }
        document.getElementById(`card-${name}`)?.remove();
        showNotification(`"${displayName}" deleted.`);
    } catch (e) {
        showNotification('Delete failed.', 'error');
    }
}

async function saveMedia(name) {
    try {
        const res = await fetch(`/signage/api/update/${encodeURIComponent(name)}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ media: _cardMedia[name] || [] }),
        });
        const data = await res.json();
        if (!data.success) { showNotification(data.error || 'Save failed.', 'error'); return; }
        showNotification('Media saved.');
    } catch (e) {
        showNotification('Save failed.', 'error');
    }
}

// ─── Logs ─────────────────────────────────────────────────────────────────────

async function loadLogs() {
    try {
        const res = await fetch('/signage/api/logs?limit=50');
        if (!res.ok) return;
        const data = await res.json();
        if (!data.success) return;
        displayErrors(data.errors || []);
        displayLogs(data.logs || []);
    } catch (e) {
        // silent
    }
}

async function clearAllErrors() {
    if (!confirm('Clear all error logs?')) return;
    try {
        await fetch('/signage/api/errors/clear', {method: 'POST'});
        loadLogs();
        showNotification('Error logs cleared.');
    } catch (e) {
        showNotification('Failed to clear errors.', 'error');
    }
}

async function clearAllLogs() {
    if (!confirm('Clear all audit logs?')) return;
    try {
        await fetch('/signage/api/logs/clear', {method: 'POST'});
        loadLogs();
        showNotification('Audit logs cleared.');
    } catch (e) {
        showNotification('Failed to clear logs.', 'error');
    }
}

// ─── Init ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    // Seed sheets state
    if (window.INITIAL_SHEETS) {
        _sheets = { ...window.INITIAL_SHEETS };
    }

    if (window.INITIAL_MEDIA) {
        Object.entries(window.INITIAL_MEDIA).forEach(([name, mediaList]) => {
            _cardMedia[name] = [...mediaList];
            renderAssignedMedia(name);
        });
    }

    populateSheetPickers();
    refreshData();
    loadLogs();
    loadMedia();
    setInterval(refreshData, 60000);
    setInterval(loadLogs, 60000);
    setInterval(loadMedia, 60000);
});

document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    closePreviewModal();
    closeAddMediaModal();
    closeAddSlideshowModal();
    closeAddSheetModal();
});
