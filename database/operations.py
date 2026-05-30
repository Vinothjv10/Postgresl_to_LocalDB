import logging
from typing import List, Optional

from psycopg2 import sql

from database.connection import DatabaseManager
from models.schemas import TableConfig

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  SOURCE DB — READ-ONLY QUERIES (SELECT only)
# ──────────────────────────────────────────────

def fetch_table_columns(db: DatabaseManager, table: TableConfig) -> List[str]:
    with db.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s "
            "ORDER BY ordinal_position",
            (table.schema_name, table.table_name),
        )
        return [row[0] for row in cur.fetchall()]


def fetch_last_n_records(
    db: DatabaseManager,
    table: TableConfig,
    limit: int,
    batch_size: int,
) -> List[tuple]:
    records: List[tuple] = []
    offset = 0

    with db.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier(table.schema_name, table.table_name)
            )
        )
        total = cur.fetchone()[0]
        fetch_limit = min(limit, total)

        while offset < fetch_limit:
            remaining = fetch_limit - offset
            current_batch = min(batch_size, remaining)
            query = sql.SQL(
                "SELECT * FROM {} ORDER BY ctid DESC LIMIT %s OFFSET %s"
            ).format(sql.Identifier(table.schema_name, table.table_name))
            cur.execute(query, (current_batch, offset))
            batch = cur.fetchall()
            if not batch:
                break
            records.extend(batch)
            offset += current_batch
            logger.info(
                "Fetched %d/%d records from %s", offset, fetch_limit, table.full_name
            )

    return records


# ──────────────────────────────────────────────
#  TARGET DB — WRITE QUERIES (local only)
# ──────────────────────────────────────────────

def schema_exists(db: DatabaseManager, schema: str) -> bool:
    with db.cursor() as cur:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = %s)",
            (schema,),
        )
        return cur.fetchone()[0]


def create_schema(db: DatabaseManager, schema: str):
    with db.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    logger.info("Created schema '%s' in target", schema)


def table_exists(db: DatabaseManager, table: TableConfig) -> bool:
    with db.cursor() as cur:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s)",
            (table.schema_name, table.table_name),
        )
        return cur.fetchone()[0]


def build_create_table_ddl(source_db: DatabaseManager, table: TableConfig) -> Optional[str]:
    with source_db.cursor() as cur:
        cur.execute(
            """
            SELECT
                'CREATE TABLE ' || quote_ident(%s) || '.' || quote_ident(%s) || ' (' ||
                string_agg(
                    quote_ident(a.attname) || ' ' ||
                    pg_catalog.format_type(a.atttypid, a.atttypmod) ||
                    CASE WHEN a.attnotnull THEN ' NOT NULL' ELSE '' END,
                    ', '
                    ORDER BY a.attnum
                ) || ')' AS ddl
            FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class c ON a.attrelid = c.oid
            JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = %s
              AND c.relname = %s
              AND a.attnum > 0
              AND NOT a.attisdropped
            """,
            (table.schema_name, table.table_name, table.schema_name, table.table_name),
        )
        row = cur.fetchone()
        return row[0] if row else None


def create_table(db: DatabaseManager, table: TableConfig, ddl: str):
    with db.cursor() as cur:
        cur.execute(ddl)
    logger.info("Created table '%s' in target", table.full_name)


def insert_records(
    db: DatabaseManager,
    table: TableConfig,
    columns: List[str],
    records: List[tuple],
    batch_size: int,
):
    if not records:
        logger.info("No records to insert into %s", table.full_name)
        return

    with db.cursor() as cur:
        insert_query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table.schema_name, table.table_name),
            sql.SQL(", ").join(map(sql.Identifier, columns)),
            sql.SQL(", ").join([sql.Placeholder()] * len(columns)),
        )

        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            values = [tuple(row) for row in batch]
            cur.executemany(insert_query, values)
            logger.info(
                "Inserted %d/%d records into %s",
                min(i + batch_size, len(records)),
                len(records),
                table.full_name,
            )
