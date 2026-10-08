"""Durable task intent and checkpoints; no backend execution on recovery."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid


class TaskConflict(RuntimeError):
    """A conflicting retry or stale writer cannot mutate durable intent."""


class TaskStore:
    """SQLite transactions provide idempotent acceptance and versioned checkpoints.

    A submitting checkpoint precedes the external RPC. Recovery must treat it as
    ambiguous, not replay it: a process can die after backend acceptance but
    before it records the response. This store never performs backend calls.
    """

    TERMINAL = frozenset({'done', 'failed', 'canceled'})
    STATES = TERMINAL | {'queued', 'waiting_resource', 'precheck', 'submitting', 'running', 'uncertain'}
    EDGES = {
        'queued': {'waiting_resource', 'precheck', 'canceled', 'failed'},
        'waiting_resource': {'precheck', 'canceled', 'failed'},
        'precheck': {'submitting', 'waiting_resource', 'canceled', 'failed'},
        'submitting': {'running', 'uncertain', 'failed'},
        'running': {'done', 'failed', 'canceled', 'uncertain'},
        'uncertain': {'done', 'failed', 'canceled'},
    }

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE,
                    fingerprint TEXT NOT NULL, intent TEXT NOT NULL,
                    state TEXT NOT NULL, checkpoint TEXT NOT NULL,
                    version INTEGER NOT NULL, created REAL NOT NULL, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL, state TEXT NOT NULL,
                    version INTEGER NOT NULL, timestamp REAL NOT NULL
                );
            ''')

    @contextmanager
    def _transaction(self):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _json(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        return {'id': row['id'], 'intent': json.loads(row['intent']), 'status': row['state'],
                'checkpoint': json.loads(row['checkpoint']), 'version': row['version'],
                'created': row['created'], 'updated': row['updated']}

    def accept(self, intent: dict, idempotency_key: str | None = None) -> tuple[dict, bool]:
        """Commit intent before acknowledging; same key + same intent returns one task."""
        if not isinstance(intent, dict):
            raise ValueError('task intent must be an object')
        if idempotency_key is not None and (not isinstance(idempotency_key, str) or
                                           not idempotency_key.strip() or len(idempotency_key) > 200):
            raise ValueError('idempotency key must be a nonempty string of at most 200 characters')
        encoded = self._json(intent)
        fingerprint = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
        with self._transaction() as connection:
            if idempotency_key is not None:
                previous = connection.execute('SELECT * FROM tasks WHERE idempotency_key=?',
                                              (idempotency_key,)).fetchone()
                if previous:
                    if previous['fingerprint'] != fingerprint:
                        raise TaskConflict('idempotency key already belongs to a different intent')
                    return self._decode(previous), False
            task_id, now = uuid.uuid4().hex, time.time()
            connection.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?)',
                               (task_id, idempotency_key, fingerprint, encoded, 'queued', '{}', 0, now, now))
            connection.execute('INSERT INTO task_events(task_id,state,version,timestamp) VALUES (?,?,?,?)',
                               (task_id, 'queued', 0, now))
            return self._decode(connection.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()), True

    def checkpoint(self, task_id: str, expected_version: int, state: str, fields: dict | None = None) -> dict:
        """Compare-and-swap state and associated evidence in a single transaction."""
        if state not in self.STATES or (fields is not None and not isinstance(fields, dict)):
            raise ValueError('invalid task checkpoint')
        with self._transaction() as connection:
            current = connection.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if current is None or current['version'] != expected_version:
                raise TaskConflict('task is missing or its version changed')
            if current['state'] in self.TERMINAL or (state != current['state'] and
                                                     state not in self.EDGES.get(current['state'], set())):
                raise TaskConflict('invalid task lifecycle transition')
            previous = json.loads(current['checkpoint'])
            if state == 'submitting' and not (fields or {}).get('submission_id', previous.get('submission_id')):
                raise ValueError('submission intent requires a durable backend correlation ID')
            for key in ('submission_id', 'prompt_id'):
                if key in previous and key in (fields or {}) and previous[key] != fields[key]:
                    raise TaskConflict('backend correlation identity cannot be replaced')
            details = {**previous, **(fields or {})}
            now, version = time.time(), expected_version + 1
            connection.execute('UPDATE tasks SET state=?, checkpoint=?, version=?, updated=? WHERE id=?',
                               (state, self._json(details), version, now, task_id))
            connection.execute('INSERT INTO task_events(task_id,state,version,timestamp) VALUES (?,?,?,?)',
                               (task_id, state, version, now))
            return self._decode(connection.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone())

    def snapshot(self) -> list[dict]:
        with self._transaction() as connection:
            return [self._decode(row) for row in connection.execute('SELECT * FROM tasks ORDER BY created,id')]

    def get(self, task_id: str) -> dict | None:
        with self._transaction() as connection:
            return self._decode(connection.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone())

    def recovery_plan(self) -> dict:
        """Classify durable facts; never infer backend termination from a restart."""
        tasks = self.snapshot()
        return {
            'resume': [task for task in tasks if task['status'] in {'queued', 'waiting_resource', 'precheck'}],
            'reconcile': [task for task in tasks if task['status'] in {'submitting', 'running', 'uncertain'}],
            'terminal': [task for task in tasks if task['status'] in self.TERMINAL],
        }
