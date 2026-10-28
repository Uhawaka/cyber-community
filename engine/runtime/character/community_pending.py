"""Rebuildable pending-record index; terminal facts remain available for audit."""

from collections.abc import MutableMapping


class PendingRecords(MutableMapping):
    def __init__(self, identity_field, pending_statuses, participant_fields=()):
        self.identity_field = identity_field
        self.pending_statuses = frozenset(pending_statuses)
        self.participant_fields = tuple(participant_fields)
        self._items = {}
        self.pending_ids = {}
        self.by_owner = {}

    def __getitem__(self, key):
        return self._items[key]

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def __setitem__(self, key, record):
        if key != getattr(record, self.identity_field):
            raise ValueError("pending index key must match record identity")
        old = self._items.get(key)
        if old is not None:
            old_owners = {getattr(old, field) for field in self.participant_fields}
            new_owners = {getattr(record, field) for field in self.participant_fields}
            for owner in old_owners - new_owners:
                self.by_owner[owner].pop(key, None)
        self._items[key] = record
        for field in self.participant_fields:
            self.by_owner.setdefault(getattr(record, field), {})[key] = None
        if record.status in self.pending_statuses:
            self.pending_ids[key] = None
        else:
            self.pending_ids.pop(key, None)

    def __delitem__(self, key):
        record = self._items[key]
        for field in self.participant_fields:
            self.by_owner[getattr(record, field)].pop(key, None)
        del self._items[key]
        self.pending_ids.pop(key, None)

    def pending(self):
        return tuple(self._items[key] for key in self.pending_ids)

    def owned(self, actor_id):
        return tuple(self._items[key] for key in self.by_owner.get(actor_id, ()))

    def pending_owned(self, actor_id):
        owned = self.by_owner.get(actor_id, {})
        return tuple(self._items[key] for key in self.pending_ids if key in owned)
