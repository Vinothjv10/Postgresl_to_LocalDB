from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2 import sql
from psycopg2.extras import DictCursor

from config.settings import settings


class DatabaseManager:
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._conn = None

    def connect(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self._dsn)
            self._conn.autocommit = False
        return self._conn

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()

    @contextmanager
    def cursor(self) -> Generator[DictCursor, None, None]:
        conn = self.connect()
        cur = conn.cursor(cursor_factory=DictCursor)
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


source_db = DatabaseManager(settings.source_dsn)
target_db = DatabaseManager(settings.target_dsn)
