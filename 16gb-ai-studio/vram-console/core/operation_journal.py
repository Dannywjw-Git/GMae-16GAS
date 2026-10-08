"""Write-ahead evidence for resource mutations that are not queue tasks."""
import json
import time
import uuid

from core.task_store import TaskStore, TaskConflict


class OperationJournal:
    def __init__(self, path):
        self.store = TaskStore(path)
        with self.store._transaction() as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS resource_operations (
                id TEXT PRIMARY KEY, intent TEXT NOT NULL, state TEXT NOT NULL,
                evidence TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL
            )''')

    def begin(self, intent):
        operation_id = uuid.uuid4().hex
        now = time.time()
        encoded = self.store._json(intent)
        with self.store._transaction() as connection:
            connection.execute('INSERT INTO resource_operations VALUES (?,?,?,?,?,?)',
                               (operation_id, encoded, 'inflight', '{}', now, now))
        return operation_id

    def finish(self, operation_id, confirmed, evidence):
        with self.store._transaction() as connection:
            row = connection.execute('SELECT state FROM resource_operations WHERE id=?', (operation_id,)).fetchone()
            if row is None or row['state'] == 'confirmed':
                raise TaskConflict('resource operation is missing or already confirmed')
            connection.execute('UPDATE resource_operations SET state=?, evidence=?, updated=? WHERE id=?',
                               ('confirmed' if confirmed else 'uncertain', self.store._json(evidence),
                                time.time(), operation_id))

    def pending(self):
        with self.store._transaction() as connection:
            return [{'id': row['id'], 'intent': json.loads(row['intent']),
                     'state': row['state'], 'evidence': json.loads(row['evidence'])}
                    for row in connection.execute(
                        "SELECT * FROM resource_operations WHERE state!='confirmed' ORDER BY created,id")]
