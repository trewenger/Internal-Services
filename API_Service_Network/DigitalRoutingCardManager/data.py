import json
import os
import re
import threading
import time
from datetime import datetime, timezone

_DIR  = os.path.dirname(os.path.abspath(__file__))
_FILE = os.path.join(_DIR, 'routing_cards.json')
_lock = threading.Lock()


class CardData:
    """All reads and writes to routing_cards.json."""

    def __init__(self):
        self.filepath = _FILE
        self._lock    = _lock

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read(self) -> dict:
        for _ in range(3):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except FileNotFoundError:
                return {'cards': {}, 'assignments': []}
            except (json.JSONDecodeError, OSError):
                time.sleep(0.05)
        return {'cards': {}, 'assignments': []}

    def _write(self, data: dict) -> None:
        tmp = self.filepath + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.filepath)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # ------------------------------------------------------------------
    # Read operations (no lock needed — atomic reads, replace-safe writes)
    # ------------------------------------------------------------------

    def get_all(self) -> dict:
        return self._read()

    def lookup_card(self, card_id: str) -> dict | None:
        return self._read()['cards'].get(card_id)

    def get_active_assignment(self, card_id: str) -> dict | None:
        actives = [
            a for a in self._read()['assignments']
            if a['card_id'] == card_id and a['status'] == 'active'
        ]
        return actives[-1] if actives else None

    def list_cards_with_assignments(self) -> list:
        data = self._read()
        active_by_card = {}
        for a in data['assignments']:
            if a['status'] == 'active':
                active_by_card[a['card_id']] = a
        result = []
        for card_id, card in sorted(data['cards'].items()):
            result.append({
                'card_id':    card_id,
                'card_status': card['status'],
                'created_at': card['created_at'],
                'assignment': active_by_card.get(card_id),
            })
        return result

    # ------------------------------------------------------------------
    # Write operations — all guarded by _lock, written atomically
    # ------------------------------------------------------------------

    def assign_card(self, card_id: str, order_number: str, part_number: str,
                    revision: str, assigned_by: str, work_order_url: str = '',
                    force: bool = False) -> dict:
        """
        Returns {'ok': True, 'batch_number': N, 'id': M} on success.
        Returns {'ok': False, 'error': '...'} on unknown card.
        Returns {'ok': False, 'conflict': True, 'current_order': '...'} on conflict when force=False.
        Idempotent: same card + same order returns the existing batch number without a new row.
        If force=True and the card is active on a different order, that assignment is closed first.
        """
        with self._lock:
            data = self._read()

            if card_id not in data['cards']:
                return {'ok': False, 'error': 'Unknown card — not in pool'}

            actives_for_card = [
                a for a in data['assignments']
                if a['card_id'] == card_id and a['status'] == 'active'
            ]
            if actives_for_card:
                existing = actives_for_card[-1]
                if existing['order_number'] == order_number:
                    return {'ok': True, 'batch_number': existing['batch_number'], 'id': existing['id']}
                if not force:
                    return {
                        'ok': False,
                        'conflict': True,
                        'current_order': existing['order_number'],
                        'error': f"Card is already assigned to order {existing['order_number']}",
                    }
                # Force reassign: close the conflicting assignment before proceeding
                existing['status']    = 'closed'
                existing['closed_at'] = self._now()

            active_for_order = [
                a for a in data['assignments']
                if a['order_number'] == order_number and a['status'] == 'active'
            ]
            next_batch = max((a['batch_number'] for a in active_for_order), default=0) + 1
            next_id    = max((a['id'] for a in data['assignments']), default=0) + 1

            data['assignments'].append({
                'id':             next_id,
                'card_id':        card_id,
                'order_number':   order_number,
                'part_number':    part_number,
                'revision':       revision,
                'work_order_url': work_order_url,
                'batch_number':   next_batch,
                'is_last_batch':  False,
                'status':         'active',
                'assigned_by':    assigned_by,
                'assigned_at':    self._now(),
                'closed_at':      None,
            })
            self._write(data)
            return {'ok': True, 'batch_number': next_batch, 'id': next_id}

    def set_last_batch(self, assignment_id: int) -> dict:
        with self._lock:
            data = self._read()
            for a in data['assignments']:
                if a['id'] == assignment_id:
                    a['is_last_batch'] = True
                    self._write(data)
                    return {'ok': True}
            return {'ok': False, 'error': 'Assignment not found'}

    def close_work_order(self, order_number: str) -> dict:
        with self._lock:
            data  = self._read()
            now   = self._now()
            count = 0
            for a in data['assignments']:
                if a['order_number'] == order_number and a['status'] == 'active':
                    a['status']    = 'closed'
                    a['closed_at'] = now
                    count += 1
            self._write(data)
            return {'ok': True, 'closed_count': count}

    def register_cards(self, card_ids: list) -> dict:
        with self._lock:
            data       = self._read()
            now        = self._now()
            added      = []
            duplicates = []
            for card_id in card_ids:
                card_id = card_id.strip()
                if not card_id:
                    continue
                if card_id in data['cards']:
                    duplicates.append(card_id)
                else:
                    data['cards'][card_id] = {'status': 'in_pool', 'created_at': now}
                    added.append(card_id)
            if added:
                self._write(data)
            return {'ok': True, 'added': added, 'duplicates': duplicates}
