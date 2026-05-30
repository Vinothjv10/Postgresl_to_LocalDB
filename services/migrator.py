import logging
import time
from functools import wraps
from typing import List

import psycopg2

from config.settings import Settings
from database.connection import DatabaseManager
from database.operations import (
    build_create_table_ddl,
    create_schema,
    create_table,
    fetch_table_columns,
    insert_records_stream,
    schema_exists,
    stream_records,
    table_exists,
)
from models.schemas import TableConfig

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [5, 30, 120]


def retry_on_disconnect(func):
    @wraps(func)
    def wrapper(self, table, *args, **kwargs):
        last_exc = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return func(self, table, *args, **kwargs)
            except psycopg2.OperationalError as e:
                last_exc = e
                if attempt == MAX_RETRIES:
                    raise
                delay = RETRY_DELAYS[attempt - 1]
                logger.warning(
                    "Connection lost on %s (attempt %d/%d). "
                    "Retrying in %ds... Error: %s",
                    table.full_name, attempt, MAX_RETRIES, delay, e,
                )
                time.sleep(delay)
                self.source_db.reconnect()
                self.target_db.reconnect()
        raise last_exc
    return wrapper


class DataMigrator:
    def __init__(
        self,
        tables: List[TableConfig],
        source_db: DatabaseManager,
        target_db: DatabaseManager,
        settings: Settings,
    ):
        self.tables = tables
        self.source_db = source_db
        self.target_db = target_db
        self.batch_size = settings.batch_size
        self.limit = settings.limit

    def run(self):
        start_time = time.time()
        total_records = 0
        success_count = 0
        fail_count = 0

        for table in self.tables:
            logger.info("=" * 60)
            logger.info("Processing table: %s", table.full_name)
            logger.info("=" * 60)

            try:
                count = self._migrate_table(table)
                total_records += count
                success_count += 1
                logger.info(
                    "✓ %s — migrated %d records", table.full_name, count
                )
            except Exception as e:
                fail_count += 1
                logger.error(
                    "✗ %s — migration failed: %s", table.full_name, e, exc_info=True
                )

        elapsed = time.time() - start_time
        logger.info("=" * 60)
        logger.info(
            "Migration complete: %d succeeded, %d failed, "
            "%d total records migrated in %.2fs",
            success_count, fail_count, total_records, elapsed,
        )

    @retry_on_disconnect
    def _migrate_table(self, table: TableConfig) -> int:
        columns = fetch_table_columns(self.source_db, table)
        if not columns:
            logger.warning("No columns found for %s — skipping", table.full_name)
            return 0

        record_stream = stream_records(
            self.source_db, table, self.limit, self.batch_size
        )

        if not schema_exists(self.target_db, table.schema_name):
            create_schema(self.target_db, table.schema_name)
        else:
            logger.info("Schema '%s' already exists", table.schema_name)

        if not table_exists(self.target_db, table):
            ddl = build_create_table_ddl(self.source_db, table)
            if not ddl:
                raise RuntimeError(f"Could not build DDL for {table.full_name}")
            create_table(self.target_db, table, ddl)
        else:
            logger.info("Table '%s' already exists", table.full_name)

        count = insert_records_stream(
            self.target_db, table, columns, record_stream, self.batch_size
        )
        return count
