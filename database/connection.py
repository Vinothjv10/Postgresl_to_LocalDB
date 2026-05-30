import logging
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2.extras import DictCursor

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, dsn: str, label: str = "db", connect_timeout: int = 30):
        self._dsn = dsn
        self._label = label
        self._connect_timeout = connect_timeout
        self._conn = None

    def connect(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(
                self._dsn,
                connect_timeout=self._connect_timeout,
                keepalives=1,
                keepalives_idle=300,
                keepalives_interval=60,
                keepalives_count=5,
                application_name="postgres_to_localdb",
                options="-c statement_timeout=0",
            )
            self._conn.autocommit = False
        return self._conn

    def reconnect(self):
        self.close()
        return self.connect()

    @property
    def is_connected(self) -> bool:
        return self._conn is not None and not self._conn.closed

    def check_connection(self) -> tuple[bool, str]:
        try:
            conn = self.connect()
            cur = conn.cursor()
            logger.info("SQL: SELECT 1 — checking %s connection", self._label)
            cur.execute("SELECT 1")
            result = cur.fetchone()
            logger.info("RESULT: %s — %s", self._label, result)
            cur.close()
            return True, ""
        except Exception as e:
            return False, str(e)

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()

    @contextmanager
    def cursor(self) -> Generator[DictCursor, None, None]:
        if not self.is_connected:
            self.connect()
        conn = self._conn
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
