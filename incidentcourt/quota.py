"""Durable single-process quota ledger shared with fixture-only tests."""
import fcntl
import hashlib
import os
import sqlite3
import threading
import time
from pathlib import Path


class Quota:
    """Lifetime run reservations; uncertain/failed calls are never refunded."""
    def __init__(self, path, maximum, per_session):
        if not ((maximum is None and per_session is None) or
                (type(maximum) is int and maximum > 0 and type(per_session) is int and per_session > 0)):
            raise ValueError('Run limits must both be positive or both be explicitly unlimited')
        self.path, self.maximum, self.per_session = Path(path), maximum, per_session
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file = open(str(self.path) + '.lock', 'a+')
        os.chmod(str(self.path) + '.lock', 0o600)
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock_file.close()
            raise ValueError('Only one judge server may use this quota ledger') from None
        self.mutex = threading.Lock()
        if not self.path.is_file():
            self.lock_file.close()
            raise ValueError('Quota ledger missing; restore it, do not silently reset the budget')
        try:
            with sqlite3.connect(f'file:{self.path}?mode=rw', uri=True) as db:
                valid = db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                schema = db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
                db.execute('SELECT COUNT(*) FROM reservations').fetchone()
                if not valid or schema != ('judge-quota-v1',): raise ValueError()
        except (sqlite3.Error, ValueError):
            self.lock_file.close()
            raise ValueError('Quota ledger invalid; restore the original ledger') from None
        os.chmod(self.path, 0o600)
        stat = self.path.stat()
        self.identity = (stat.st_dev, stat.st_ino)

    @staticmethod
    def initialize(path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                db.execute("INSERT INTO metadata VALUES ('schema', 'judge-quota-v1')")
                db.execute('CREATE TABLE reservations (session_hash TEXT NOT NULL, created INTEGER NOT NULL)')
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def reserve(self, session):
        with self.mutex:
            try:
                stat = self.path.stat()
                if (stat.st_dev, stat.st_ino) != self.identity:
                    raise ValueError('Quota ledger changed; refusing inference')
                db = sqlite3.connect(f'file:{self.path}?mode=rw', uri=True)
            except (OSError, sqlite3.Error):
                raise ValueError('Quota ledger unavailable; refusing inference') from None
            try:
                with db:
                    return self._reserve(db, session)
            finally:
                db.close()

    def _reserve(self, db, session):
        db.execute('BEGIN IMMEDIATE')
        digest = hashlib.sha256(session.encode()).hexdigest()
        if self.maximum is not None:
            total = db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0]
            count = db.execute('SELECT COUNT(*) FROM reservations WHERE session_hash=?', (digest,)).fetchone()[0]
            if total >= self.maximum or count >= self.per_session:
                return False
        db.execute('INSERT INTO reservations VALUES (?,?)', (digest, int(time.time())))
        return True

    def close(self):
        self.lock_file.close()
