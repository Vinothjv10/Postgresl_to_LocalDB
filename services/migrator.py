import logging
import time
from typing import List

from config.settings import settings
from database.connection import source_db, target_db
from database.operations import (
    ensure_schema_exists,
    ensure_table_exists,
    fetch_last_n_records,
    get_table_ddl,
    insert_records,
    truncate_table,
)
from models.schemas import TableConfig

logger = logging.getLogger(__name__)


class DataMigrator:
    def __init__(self, tables: List[TableConfig]):
        self.tables = tables
        self.batch_size = settings.batch_size
        self.limit = settings.limit

    def run(self):
        start_time = time.time()
        total_records = 0

        for table in self.tables:
            logger.info("=" * 60)
            logger.info("Processing table: %s", table.full_name)
            logger.info("=" * 60)

            try:
                count = self._migrate_table(table)
                total_records += count
            except Exception as e:
                logger.error("Failed to migrate table %s: %s", table.full_name, e, exc_info=True)

        elapsed = time.time() - start_time
        logger.info("=" * 60)
        logger.info(
            "Migration complete. Migrated %d records from %d tables in %.2f seconds",
            total_records,
            len(self.tables),
            elapsed,
        )

    def _migrate_table(self, table: TableConfig) -> int:
        ddl = get_table_ddl(source_db, table)
        if not ddl:
            raise RuntimeError(f"Could not retrieve DDL for {table.full_name}")

        ensure_schema_exists(target_db, table.schema_name)

        with source_db.cursor() as src_cur:
            src_cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                (table.schema_name, table.table_name),
            )
            columns = [row[0] for row in src_cur.fetchall()]

        records = fetch_last_n_records(source_db, table, self.limit, self.batch_size)
        if not records:
            logger.info("No records found for %s", table.full_name)
            return 0

        logger.info("Fetched %d records from %s", len(records), table.full_name)

        ensure_table_exists(target_db, table, source_db)
        truncate_table(target_db, table)
        insert_records(target_db, table, columns, records, self.batch_size)

        logger.info(
            "Successfully migrated %d records to %s", len(records), table.full_name
        )
        return len(records)
