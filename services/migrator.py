import logging
import time
from typing import List

from config.settings import Settings
from database.connection import DatabaseManager
from database.operations import (
    build_create_table_ddl,
    create_schema,
    create_table,
    fetch_last_n_records,
    fetch_table_columns,
    insert_records,
    schema_exists,
    table_exists,
)
from models.schemas import TableConfig

logger = logging.getLogger(__name__)


class DataMigrator:
    def __init__(self, tables: List[TableConfig], source_db: DatabaseManager, target_db: DatabaseManager, settings: Settings):
        self.tables = tables
        self.source_db = source_db
        self.target_db = target_db
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
                logger.error(
                    "Failed to migrate table %s: %s", table.full_name, e, exc_info=True
                )

        elapsed = time.time() - start_time
        logger.info("=" * 60)
        logger.info(
            "Migration complete. Migrated %d records from %d tables in %.2f seconds",
            total_records,
            len(self.tables),
            elapsed,
        )

    def _migrate_table(self, table: TableConfig) -> int:
        columns = fetch_table_columns(self.source_db, table)
        if not columns:
            logger.warning("No columns found for %s — skipping", table.full_name)
            return 0

        records = fetch_last_n_records(
            self.source_db, table, self.limit, self.batch_size
        )
        if not records:
            logger.info("No records found for %s", table.full_name)
            return 0

        logger.info("Fetched %d records from %s", len(records), table.full_name)

        if not schema_exists(self.target_db, table.schema_name):
            create_schema(self.target_db, table.schema_name)
        else:
            logger.info("Schema '%s' already exists in target", table.schema_name)

        if not table_exists(self.target_db, table):
            ddl = build_create_table_ddl(self.source_db, table)
            if not ddl:
                raise RuntimeError(f"Could not build DDL for {table.full_name}")
            create_table(self.target_db, table, ddl)
        else:
            logger.info("Table '%s' already exists in target", table.full_name)

        insert_records(self.target_db, table, columns, records, self.batch_size)

        logger.info(
            "Successfully migrated %d records to %s", len(records), table.full_name
        )
        return len(records)
