import logging
from typing import List, Optional

from psycopg2 import sql

from database.connection import DatabaseManager
from models.schemas import TableConfig

logger = logging.getLogger(__name__)


def ensure_schema_exists(db: DatabaseManager, schema: str):
    with db.cursor() as cur:
        cur.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema))
        )
    logger.info("Ensured schema '%s' exists", schema)


def ensure_table_exists(db: DatabaseManager, table: TableConfig, source_db: DatabaseManager):
    ddl = get_table_ddl(source_db, table)
    if not ddl:
        raise RuntimeError(f"Could not get DDL for {table.full_name}")

    with db.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(table.schema_name)))
        cur.execute(ddl)
    logger.info("Ensured table '%s' exists in target", table.full_name)


def get_table_ddl(db: DatabaseManager, table: TableConfig) -> Optional[str]:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT pg_get_server_def(pg_class.oid)
            FROM pg_class
            INNER JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
            WHERE pg_namespace.nspname = %s AND pg_class.relname = %s
            """,
            (table.schema_name, table.table_name)
        )
        row = cur.fetchone()
        if not row:
            cur.execute(
                """
                SELECT
                    'CREATE TABLE ' || quote_ident(%s) || '.' || quote_ident(%s) || ' (' ||
                    string_agg(
                        quote_ident(column_name) || ' ' || data_type ||
                        CASE WHEN character_maximum_length IS NOT NULL
                            THEN '(' || character_maximum_length || ')'
                            ELSE ''
                        END ||
                        CASE WHEN is_nullable = 'NO' THEN ' NOT NULL' ELSE '' END,
                        ', '
                    ) || ')' AS ddl
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                GROUP BY table_schema, table_name
                """,
                (table.schema_name, table.table_name, table.schema_name, table.table_name)
            )
            row = cur.fetchone()
        return row[0] if row else None


def fetch_last_n_records(
    db: DatabaseManager,
    table: TableConfig,
    limit: int,
    batch_size: int,
) -> List[tuple]:
    records: List[tuple] = []
    offset = 0
    with db.cursor() as cur:
        count_query = sql.SQL("SELECT COUNT(*) FROM {}").format(
            sql.Identifier(table.schema_name, table.table_name)
        )
        cur.execute(count_query)
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


def truncate_table(db: DatabaseManager, table: TableConfig):
    with db.cursor() as cur:
        query = sql.SQL("TRUNCATE TABLE {}").format(
            sql.Identifier(table.schema_name, table.table_name)
        )
        cur.execute(query)
    logger.info("Truncated table %s", table.full_name)
