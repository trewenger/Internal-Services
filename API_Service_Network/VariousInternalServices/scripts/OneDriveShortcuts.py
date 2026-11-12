"""
script docstring:

OneDrive Shortcuts — pushes an "Add shortcut to OneDrive" shortcut for one or more SharePoint
document libraries to the root of each target user's OneDrive (My Files), exactly as if each user
had clicked the "Add shortcut to OneDrive" button themselves.

Each configured *sync* (site URL + library + targets) is reconciled on every run:
    1. Pending removals (syncs that were deleted, or whose site/library/name was edited) are
       processed first: their tracked shortcuts are deleted from users' OneDrive.
    2. Ensure present: the shortcut is POSTed to every targeted user with conflictBehavior 'fail'
       (so reruns never create "Name 1", "Name 2"). 409 = already has it (verified to point at the
       same library), 404 = OneDrive not provisioned yet (skipped; picked up on a later run). A
       user who deleted their shortcut gets it back.
    3. Users who dropped out of a sync's targets have their tracked shortcut deleted, unless that
       would remove more than max(SHORTCUT_REMOVAL_GUARD_MIN, SHORTCUT_REMOVAL_GUARD_PCT%) of the
       sync's tracked users in one run (mass-removal guard).

Only shortcuts recorded in onedrive_shortcuts_state.json (created, or found already present, by
this service) are ever deleted. Deleting a shortcut never touches the library or its files.

Auth is app-only via GraphSession (certificate). Required Graph application permissions:
Files.ReadWrite.All, Sites.Read.All, User.Read.All, GroupMember.Read.All.
"""

import math
from datetime import datetime
from urllib.parse import quote

from config import Config
from common.Clients.Microsoft.GraphSession import GraphSession
from common.Utils.Logging import SessionLog
from API_Service_Network.VariousInternalServices.data import sync_fingerprint

__all__ = ['onedrive_shortcuts', 'preview_onedrive_shortcuts', 'validate_sync', 'default_shortcut_name']

_USER_SELECT = ['id', 'userPrincipalName', 'displayName', 'accountEnabled', 'userType', 'assignedLicenses']
_ALL_USERS_FILTER = "accountEnabled eq true and userType eq 'Member'"


class LibraryNotFound(LookupError):
    """ Raised when a sync's library name doesn't match any library on its site. """
    def __init__(self, message: str, available: list):
        super().__init__(message)
        self.available = available


# ----------------------------- Resolution ------------------------------- #

def default_shortcut_name(site_display_name: str, library_name: str) -> str:
    """ The name OneDrive gives a library-root shortcut when a user clicks the button, e.g. 'Company Home - Documents'. """
    return f'{site_display_name} - {library_name}'


def _resolve(gs: GraphSession, sync: dict) -> dict:
    """ Resolves a sync's site/library/list IDs and builds the shortcut body. Raises on any failure. """
    site = gs.get_site_by_url(sync['site_url'])
    drives = gs.list_site_drives(site['id'])
    library = (sync.get('library_name') or '').strip()
    drive = next((d for d in drives if d['name'] == library), None)
    if drive is None:
        available = sorted(d['name'] for d in drives)
        raise LibraryNotFound(
            f"Library '{library}' not found on site '{site['display_name']}'. "
            f"Available libraries: {', '.join(available) or '(none)'}",
            available,
        )
    list_id = gs.get_drive_list_id(site['id'], drive['id'])
    # OneDrive always prefixes library shortcuts with '<site name> - ' (verified: POSTing name
    # 'Company Documents' produced 'Company Home - Company Documents'). So we send only the part
    # after the prefix — the library name by default, or the sync's override — and expect
    # '<site> - <part>' back. The name OneDrive actually returns is what gets tracked.
    name_part = (sync.get('shortcut_name') or '').strip() or drive['name']
    default_name = default_shortcut_name(site['display_name'], drive['name'])
    name = default_shortcut_name(site['display_name'], name_part)
    candidates = [name] + ([name_part] if name_part.lower() != name.lower() else [])
    body = {
        'name': name_part,
        'remoteItem': {
            'sharepointIds': {
                'listId': list_id,
                'listItemUniqueId': 'root',
                'siteId': site['site_guid'],
                'siteUrl': site['web_url'],
                'webId': site['web_guid'],
            }
        },
        '@microsoft.graph.conflictBehavior': 'fail',
    }
    return {'site': site, 'drive': drive, 'list_id': list_id, 'name': name, 'candidates': candidates,
            'default_name': default_name, 'body': body, 'library_names': sorted(d['name'] for d in drives)}


def _is_eligible(user: dict) -> bool:
    """ Enabled, member (not guest), and licensed — unlicensed users have no OneDrive. """
    return (user.get('accountEnabled') is True
            and user.get('userType') in ('Member', None)
            and bool(user.get('assignedLicenses')))


def _enumerate_targets(gs: GraphSession, sync: dict) -> tuple:
    """
    Returns ({userId: user}, [warnings]) for the sync's eligible targets minus exclusions.
    Raises if a lookup fails (so a failed lookup can never look like "everyone left").
    """
    target_type = sync.get('target_type')
    warnings, raw = [], []

    if target_type == 'all_users':
        raw = gs.list_users(filter_query=_ALL_USERS_FILTER, select=_USER_SELECT)
    elif target_type == 'groups':
        for target in sync.get('targets', []):
            group = gs.get_group(target)
            raw.extend(gs.list_group_transitive_users(group['id'], select=_USER_SELECT))
    elif target_type == 'users':
        for upn in sync.get('targets', []):
            user = gs.get_user(upn, select=_USER_SELECT)
            if user is None:
                warnings.append(f'User not found: {upn}')
            else:
                raw.append(user)
    else:
        raise ValueError(f"Unknown target type '{target_type}'")

    excluded = {e.strip().lower() for e in sync.get('exclude_upns', []) if e.strip()}
    users, ineligible = {}, set()
    for user in raw:
        upn = (user.get('userPrincipalName') or '').lower()
        if upn in excluded:
            continue
        if not _is_eligible(user):
            ineligible.add(upn)
            continue
        users[user['id']] = user

    if target_type == 'users':
        for upn in sorted(ineligible):
            warnings.append(f'Not eligible (disabled, guest, or unlicensed): {upn}')
    return users, warnings


def _points_at_library(item: dict, list_id: str) -> bool:
    ids = ((item or {}).get('remoteItem') or {}).get('sharepointIds') or {}
    return (ids.get('listId') or '').lower() == list_id.lower()


def _upn(users: dict, uid: str, fallback: str = '') -> str:
    return (users.get(uid) or {}).get('userPrincipalName') or fallback or uid


def _locate_existing(gs: GraphSession, uids: list, tracked: dict, candidates: list, list_id: str) -> dict:
    """
    Finds each user's existing shortcut to the library. Library shortcuts do NOT appear in
    /drive/root/children listings, so lookup is by tracked item ID first, then by exact name
    (/drive/root:/<name>) for each candidate name. Only the first candidate (the name OneDrive
    will actually use) counts as a name conflict when an unrelated item holds it.
    :return: {uid: (status, detail)} — status 'found' (detail = driveItem), 'conflict' (driveItem),
        'missing', 'no_drive' (OneDrive not provisioned), or 'error' (detail = message).
    """
    out, conflicts = {}, {}
    select = '?$select=id,name,remoteItem'

    by_id = [uid for uid in uids if (tracked.get(uid) or {}).get('item_id')]
    if by_id:
        results = gs.batch([{'method': 'GET', 'url': f"/users/{uid}/drive/items/{tracked[uid]['item_id']}{select}"}
                            for uid in by_id])
        for uid, r in zip(by_id, results):
            if r['status'] == 200 and _points_at_library(r['body'], list_id):
                out[uid] = ('found', r['body'])

    for i, candidate in enumerate(candidates):
        todo = [uid for uid in uids if uid not in out]
        if not todo:
            break
        results = gs.batch([{'method': 'GET', 'url': f"/users/{uid}/drive/root:/{quote(candidate, safe='')}{select}"}
                            for uid in todo])
        for uid, r in zip(todo, results):
            if r['status'] == 200:
                if _points_at_library(r['body'], list_id):
                    out[uid] = ('found', r['body'])
                elif i == 0:
                    conflicts[uid] = r['body']
            elif r['status'] == 404 and gs.batch_error_code(r) == 'itemNotFound':
                continue
            elif r['status'] == 404:
                out[uid] = ('no_drive', None)
            else:
                out[uid] = ('error', gs.batch_error_message(r))

    for uid in uids:
        if uid not in out:
            out[uid] = ('conflict', conflicts[uid]) if uid in conflicts else ('missing', None)
    return out


# ----------------------------- Reconcile ------------------------------- #

def _process_pending_removals(gs: GraphSession, state, dry_run: bool, log: SessionLog, report: dict) -> None:
    """ Step 0: delete tracked shortcuts of deleted/edited syncs. Failures stay queued for the next run. """
    key = 'Pending removals'
    if dry_run:
        for entry in state.get_pending_removals():
            report['pending_removals'].append({
                'name': entry.get('name'), 'reason': entry.get('reason'),
                'users': sorted(i.get('upn') or uid for uid, i in entry.get('items', {}).items()),
            })
        return

    pending = state.take_pending_removals()
    if not pending:
        return
    try:
        flat = [(entry, uid, item) for entry in pending for uid, item in list(entry.get('items', {}).items())]
        results = gs.batch([{'method': 'DELETE', 'url': f"/users/{uid}/drive/items/{item['item_id']}"}
                            for _, uid, item in flat])
        removed, failed = 0, 0
        for (entry, uid, item), result in zip(flat, results):
            upn = item.get('upn') or uid
            if result['status'] in (200, 204, 404):
                del entry['items'][uid]
                removed += 1
                log.log(key, f"Removed '{item.get('name') or entry.get('name')}' from {upn} (sync {entry.get('reason')})")
            else:
                failed += 1
                log.log(key, f"Failed to remove shortcut from {upn}: {gs.batch_error_message(result)} - will retry next run", True)
        log.log(key, f'{removed} removed, {failed} failed')
    except Exception as e:
        log.log(key, f'Removal batch failed: {e} - all remaining removals will retry next run', True)
    finally:
        state.requeue_removals(pending)


def _process_sync(gs: GraphSession, sync: dict, state, dry_run: bool, log: SessionLog) -> dict:
    """ Steps 1-3 for one enabled sync. Returns a report dict (used by preview and for counts). """
    key = f"Sync: {sync.get('name')}"
    rep = {'id': sync['id'], 'name': sync.get('name'), 'fatal': None, 'shortcut_name': None,
           'target_count': 0, 'created': [], 'existing': [], 'removed': [], 'replaced': [],
           'skipped': [], 'conflict': [], 'errors': [], 'warnings': [],
           'guard_tripped': False, 'guard_detail': ''}
    messages = []  # (message, is_error) — logged after the summary line

    # --- 1. Resolve ---
    try:
        res = _resolve(gs, sync)
    except Exception as e:
        rep['fatal'] = f'Could not resolve the SharePoint library: {e}'
        log.log(key, rep['fatal'] + ' Nothing was created or removed for this sync.', True)
        return rep
    rep['shortcut_name'] = name = res['name']
    list_id = res['list_id']

    # --- 2. Enumerate targets ---
    try:
        desired, warnings = _enumerate_targets(gs, sync)
    except Exception as e:
        rep['fatal'] = f'Could not look up target users: {e}'
        log.log(key, rep['fatal'] + ' Nothing was created or removed for this sync.', True)
        return rep
    rep['target_count'] = len(desired)
    rep['warnings'].extend(warnings)
    messages.extend((w, False) for w in warnings)

    st = state.get_sync(sync['id'])
    tracked = st['items'] if st.get('fingerprint') == sync_fingerprint(sync) else {}
    items = dict(tracked)
    now = datetime.now().isoformat()
    uids = list(desired)
    established = {}  # uid -> (item_id, actual name) of the shortcut confirmed present this run

    def _track(uid, item):
        item_name = (item or {}).get('name') or name
        established[uid] = ((item or {}).get('id'), item_name)
        items[uid] = {'upn': _upn(desired, uid), 'item_id': (item or {}).get('id'), 'name': item_name, 'tracked_at': now}

    def _apply_located(uid, status, detail, after_conflict):
        """ Records a _locate_existing() result. after_conflict=True when a POST just returned 409. """
        upn = _upn(desired, uid)
        if status == 'found':
            if not dry_run:
                _track(uid, detail)
            else:
                established[uid] = (detail.get('id'), detail.get('name'))
            rep['existing'].append(upn)
        elif status == 'conflict':
            rep['conflict'].append(upn)
            messages.append((f"Name conflict for {upn}: an unrelated item named '{name}' already exists "
                             f"in their OneDrive - left untouched", False))
        elif status == 'missing' and after_conflict:
            # OneDrive refused the create as a duplicate but no item by the expected name/ID points
            # at the library (e.g. the user renamed their shortcut). Present, but can't be tracked.
            rep['existing'].append(upn)
            rep['warnings'].append(f'{upn}: shortcut exists under a different name (untracked)')
            messages.append((f'{upn} already has a shortcut to this library under a different name '
                             f'(likely renamed by the user) - left as-is, not tracked', False))
        elif status == 'missing':
            rep['created'].append(upn)  # preview: would create
        elif status == 'no_drive':
            rep['skipped'].append(upn)
            if not dry_run:
                messages.append((f'Skipped {upn}: OneDrive not provisioned yet (will retry next run)', False))
        else:
            rep['errors'].append(f'{upn}: {detail}')
            messages.append((f'Could not verify existing shortcut for {upn}: {detail}', True))

    # --- 3. Ensure present ---
    if dry_run:
        for uid, (status, detail) in _locate_existing(gs, uids, tracked, res['candidates'], list_id).items():
            _apply_located(uid, status, detail, after_conflict=False)
    else:
        posts = gs.batch([{'method': 'POST', 'url': f'/users/{uid}/drive/root/children', 'body': res['body']}
                          for uid in uids])
        recheck = []
        for uid, r in zip(uids, posts):
            upn = _upn(desired, uid)
            if r['status'] in (200, 201):
                _track(uid, r['body'])
                rep['created'].append(upn)
                messages.append((f"Created '{established[uid][1]}' for {upn}", False))
            elif r['status'] == 409:
                recheck.append(uid)
            elif r['status'] == 404:
                rep['skipped'].append(upn)
                messages.append((f'Skipped {upn}: OneDrive not provisioned yet (will retry next run)', False))
            else:
                rep['errors'].append(f'{upn}: {gs.batch_error_message(r)}')
                messages.append((f'Failed to create shortcut for {upn}: {gs.batch_error_message(r)}', True))

        if recheck:
            for uid, (status, detail) in _locate_existing(gs, recheck, tracked, res['candidates'], list_id).items():
                _apply_located(uid, status, detail, after_conflict=True)

    # Tracked shortcuts under an old name (e.g. the site was renamed) are replaced once the new one exists.
    replace = [(uid, tracked[uid]) for uid in tracked
               if uid in established
               and (tracked[uid].get('name') or '').lower() != (established[uid][1] or '').lower()
               and tracked[uid].get('item_id') != established[uid][0]]
    rep['replaced'] = [t.get('upn') or uid for uid, t in replace]

    # --- 4. Remove users who left the targets (with mass-removal guard) ---
    dropped = [uid for uid in tracked if uid not in desired]
    threshold = max(Config.SHORTCUT_REMOVAL_GUARD_MIN,
                    math.ceil(len(tracked) * Config.SHORTCUT_REMOVAL_GUARD_PCT / 100))
    if dropped and len(dropped) > threshold and not st.get('force_removals'):
        rep['guard_tripped'] = True
        rep['guard_detail'] = (f'{len(dropped)} of {len(tracked)} tracked users are no longer targeted '
                               f'(limit {threshold} per run)')
        rep['removed'] = [tracked[uid].get('upn') or uid for uid in dropped]
        messages.append((f"Removal guard tripped: {rep['guard_detail']}. No shortcuts were removed. "
                         f"Check the sync's targets, then use Preview > Allow removals to proceed.", True))
        dropped = []

    deletes = [(uid, tracked[uid], 'no longer targeted') for uid in dropped] + \
              [(uid, t, 'replaced by renamed shortcut') for uid, t in replace]
    if dry_run:
        if not rep['guard_tripped']:
            rep['removed'] = [tracked[uid].get('upn') or uid for uid in dropped]
    elif deletes:
        results = gs.batch([{'method': 'DELETE', 'url': f"/users/{uid}/drive/items/{t['item_id']}"}
                            for uid, t, _ in deletes])
        for (uid, t, why), r in zip(deletes, results):
            upn = t.get('upn') or uid
            if r['status'] in (200, 204, 404):
                if why == 'no longer targeted':
                    items.pop(uid, None)
                    rep['removed'].append(upn)
                messages.append((f"Removed '{t.get('name') or name}' from {upn} ({why})", False))
            else:
                rep['errors'].append(f'{upn}: {gs.batch_error_message(r)}')
                messages.append((f'Failed to remove shortcut from {upn} ({why}): {gs.batch_error_message(r)}', True))

    if not dry_run:
        state.save_sync_items(sync, items)
        if st.get('force_removals'):
            state.set_force_removals(sync['id'], False)

    # --- Log: summary first, then details ---
    created_label = 'would create' if dry_run else 'created'
    removed_label = 'would remove' if dry_run else 'removed'
    log.log(key, (f"'{name}': targets {rep['target_count']} | {created_label} {len(rep['created'])} | "
                  f"existing {len(rep['existing'])} | {removed_label} {0 if rep['guard_tripped'] else len(rep['removed'])} | "
                  f"skipped {len(rep['skipped'])} | conflict {len(rep['conflict'])} | errors {len(rep['errors'])}"))
    for message, is_error in messages:
        log.log(key, message, is_error)
    return rep


def _run(syncs: list, state, dry_run: bool) -> tuple:
    log = SessionLog()
    report = {'generated_at': datetime.now().isoformat(), 'dry_run': dry_run,
              'pending_removals': [], 'syncs': [], 'error': None}

    if not dry_run:
        state.reconcile_with_config(syncs)  # safety net; the save route normally does this

    enabled = [s for s in syncs if s.get('enabled')]
    report['syncs'].extend({'id': s.get('id'), 'name': s.get('name'), 'disabled': True}
                           for s in syncs if not s.get('enabled'))
    if not enabled and not state.get_pending_removals():
        log.log('OneDrive Shortcuts', 'No enabled syncs and no pending removals - nothing to do.')
        return log, report

    try:
        gs = GraphSession()
    except Exception as e:
        report['error'] = f'Could not authenticate to Microsoft Graph: {e}'
        log.log('OneDrive Shortcuts', report['error'], True)
        return log, report

    _process_pending_removals(gs, state, dry_run, log, report)

    for sync in enabled:
        try:
            report['syncs'].append(_process_sync(gs, sync, state, dry_run, log))
        except Exception as e:
            log.log(f"Sync: {sync.get('name')}", f'Unexpected error: {e}', True)
            report['syncs'].append({'id': sync.get('id'), 'name': sync.get('name'), 'fatal': f'Unexpected error: {e}'})
    return log, report


# ----------------------------- Public entry points ------------------------------- #

def onedrive_shortcuts(syncs: list, state) -> SessionLog:
    """
    Reconciles every enabled sync (create missing shortcuts, remove dropped users) and processes
    pending removals for deleted/edited syncs.
    :param syncs: The 'syncs' list from services_config.json['onedrive-shortcuts'].
    :param state: A ShortcutState instance (VariousInternalServices/data.py).
    :return: SessionLog — one log key per sync (summary line first) plus 'Pending removals'.
        Skipped (no OneDrive yet) and name conflicts are warnings; resolve/lookup failures,
        per-user API errors, and removal-guard trips set the error flag.
    """
    log, _ = _run(syncs, state, dry_run=False)
    return log


def preview_onedrive_shortcuts(syncs: list, state) -> dict:
    """
    Dry run of onedrive_shortcuts(): performs only GETs and returns what a run would do.
    No shortcuts are created or removed and the state file is not modified.
    :return: {"generated_at", "dry_run": True, "error", "pending_removals": [{name, reason, users}],
              "syncs": [{id, name, fatal, shortcut_name, target_count, created (= would create),
                         existing, removed (= would remove), replaced, skipped, conflict, errors,
                         warnings, guard_tripped, guard_detail} | {id, name, disabled: True}]}
    """
    _, report = _run(syncs, state, dry_run=True)
    return report


def validate_sync(sync: dict) -> dict:
    """
    Resolves one sync (site, library, targets) without writing anything — used by the UI's
    Validate button.
    :return: {"ok", "errors", "warnings", "site_display_name", "library_names",
              "default_shortcut_name", "shortcut_name", "target_count"}
    """
    out = {'ok': False, 'errors': [], 'warnings': [], 'site_display_name': None, 'library_names': [],
           'default_shortcut_name': None, 'shortcut_name': None, 'target_count': None}
    try:
        gs = GraphSession()
    except Exception as e:
        out['errors'].append(f'Could not authenticate to Microsoft Graph: {e}')
        return out

    try:
        res = _resolve(gs, sync)
        out.update(site_display_name=res['site']['display_name'], library_names=res['library_names'],
                   default_shortcut_name=res['default_name'], shortcut_name=res['name'])
    except LibraryNotFound as e:
        out['errors'].append(str(e))
        out['library_names'] = e.available
    except Exception as e:
        out['errors'].append(f'Could not resolve the SharePoint site: {e}')

    try:
        users, warnings = _enumerate_targets(gs, sync)
        out['target_count'] = len(users)
        out['warnings'].extend(warnings)
        if not users:
            out['warnings'].append('No eligible users match these targets.')
    except Exception as e:
        out['errors'].append(f'Could not look up target users: {e}')

    out['ok'] = not out['errors']
    return out
