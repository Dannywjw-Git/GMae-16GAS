"""OS-held singleton for GPU 0 servers under one operating-system account."""
import json
import os
from pathlib import Path


class ProcessOwnership:
    """Hold through server lifetime; a crash releases the OS lock, not recovery facts.

    Persistent journal identity prevents a different checkout/database bypassing
    recovery. Lock path is shared by production servers, independent of ports.
    This does not fence external GPU clients or other operating-system accounts.
    """

    def __init__(self, journal_path, lock_path=None):
        root = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share')))
        self.path = Path(lock_path) if lock_path else root / 'GMae' / 'gpu0.lock'
        self.journal_path = os.path.normcase(os.path.realpath(journal_path))
        self.handle = None

    def acquire(self):
        if self.handle is not None:
            raise RuntimeError('ownership already acquired')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        handle = os.fdopen(descriptor, 'r+b')
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            handle.close()
            raise RuntimeError('GPU 0 already owned or process lock unavailable') from None
        self.handle = handle
        try:
            handle.seek(1)
            raw = handle.read()
            if raw:
                previous = json.loads(raw.decode('utf-8'))
                if previous.get('journal_path') != self.journal_path:
                    raise RuntimeError('GPU 0 recovery journal differs; use the original GMAE_TASK_DB')
            metadata = json.dumps({'journal_path': self.journal_path, 'pid': os.getpid()}).encode('utf-8')
            handle.seek(1)
            handle.write(metadata)
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            self.close()
            raise
        return self

    def close(self):
        if self.handle is not None:
            # Closing releases the OS lock even after metadata validation failure.
            self.handle.close()
            self.handle = None
