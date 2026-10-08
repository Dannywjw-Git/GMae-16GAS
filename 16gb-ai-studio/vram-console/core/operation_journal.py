"""Write-ahead evidence for resource mutations that are not queue tasks."""
import json
import time
import uuid

from core.task_store import TaskStore, TaskConflict


class OperationJournal:
    def __init__(self, path):
        self.store = TaskStore(path)
        self.supervised = True
        with self.store._transaction() as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS resource_operations (
                id TEXT PRIMARY KEY, intent TEXT NOT NULL, state TEXT NOT NULL,
                evidence TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL
            )''')
            connection.execute('''CREATE TABLE IF NOT EXISTS resource_commands (
                id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, intent TEXT NOT NULL,
                state TEXT NOT NULL, return_code INTEGER, created REAL NOT NULL, updated REAL NOT NULL
            )''')
            connection.execute('''CREATE TABLE IF NOT EXISTS resource_command_results (
                id TEXT PRIMARY KEY, output TEXT NOT NULL
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
            if confirmed and connection.execute(
                    "SELECT 1 FROM resource_commands WHERE operation_id=? AND state!='confirmed' LIMIT 1",
                    (operation_id,)).fetchone():
                raise TaskConflict('resource command termination is unconfirmed')
            connection.execute('UPDATE resource_operations SET state=?, evidence=?, updated=? WHERE id=?',
                               ('confirmed' if confirmed else 'uncertain', self.store._json(evidence),
                                time.time(), operation_id))

    def command_begin(self, operation_id, args, supervised=False):
        if not isinstance(args, list) or not args or not all(isinstance(arg, str) for arg in args):
            raise ValueError('command requires a nonempty string argument list')
        command_id, now = uuid.uuid4().hex, time.time()
        with self.store._transaction() as connection:
            operation = connection.execute('SELECT state FROM resource_operations WHERE id=?', (operation_id,)).fetchone()
            if operation is None or operation['state'] == 'confirmed':
                raise TaskConflict('command requires a live resource operation')
            connection.execute('INSERT INTO resource_commands VALUES (?,?,?,?,?,?,?)',
                               (command_id, operation_id, self.store._json(args),
                                'dispatch_pending' if supervised else 'inflight', None, now, now))
        return command_id

    def command_claim(self, command_id):
        """Only one independently launched worker may cross the spawn boundary."""
        with self.store._transaction() as connection:
            changed = connection.execute(
                "UPDATE resource_commands SET state='inflight',updated=? WHERE id=? AND state='dispatch_pending'",
                (time.time(), command_id))
            if changed.rowcount != 1:
                return None
            return json.loads(connection.execute('SELECT intent FROM resource_commands WHERE id=?',
                                                 (command_id,)).fetchone()['intent'])

    def command_finish(self, command_id, return_code, output=None):
        with self.store._transaction() as connection:
            result = connection.execute(
                "UPDATE resource_commands SET state=?,return_code=?,updated=? WHERE id=? AND state='inflight'",
                ('confirmed' if return_code == 0 else 'uncertain', return_code, time.time(), command_id))
            if result.rowcount != 1:
                raise TaskConflict('command receipt is missing or already saved')
            if output is not None:
                connection.execute('INSERT INTO resource_command_results VALUES (?,?)',
                                   (command_id, output[-65536:]))

    def command_result(self, command_id):
        with self.store._transaction() as connection:
            result = connection.execute(
                'SELECT c.return_code,r.output FROM resource_commands c '
                'JOIN resource_command_results r ON r.id=c.id WHERE c.id=?', (command_id,)).fetchone()
            return (result['return_code'], result['output']) if result is not None else None

    def commands(self, operation_id):
        with self.store._transaction() as connection:
            return [{'id': row['id'], 'intent': json.loads(row['intent']),
                     'state': row['state'], 'return_code': row['return_code']}
                    for row in connection.execute(
                        'SELECT * FROM resource_commands WHERE operation_id=? ORDER BY created,id', (operation_id,))]

    def pending(self):
        with self.store._transaction() as connection:
            return [{'id': row['id'], 'intent': json.loads(row['intent']),
                     'state': row['state'], 'evidence': json.loads(row['evidence'])}
                    for row in connection.execute(
                        "SELECT * FROM resource_operations WHERE state!='confirmed' ORDER BY created,id")]

    def get(self, operation_id):
        with self.store._transaction() as connection:
            row = connection.execute('SELECT * FROM resource_operations WHERE id=?', (operation_id,)).fetchone()
            return ({'id': row['id'], 'intent': json.loads(row['intent']), 'state': row['state'],
                     'evidence': json.loads(row['evidence'])} if row is not None else None)
