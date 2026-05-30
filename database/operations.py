import logging
from typing import Generator, List, Optional

from psycopg2 import sql
from psycopg2.extras import execute_values

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


def stream_records(
    db: DatabaseManager,
    table: TableConfig,
    limit: int,
    batch_size: int,
) -> Generator[List[tuple], None, None]:
    with db.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier(table.schema_name, table.table_name)
            )
        )
        total = cur.fetchone()[0]
        fetch_limit = min(limit, total)

        if fetch_limit == 0:
            return

        order_col = _get_order_column(cur, table)
        offset = 0

        while offset < fetch_limit:
            remaining = fetch_limit - offset
            current_batch = min(batch_size, remaining)
            query = sql.SQL(
                "SELECT * FROM {} ORDER BY {} DESC LIMIT %s OFFSET %s"
            ).format(
                sql.Identifier(table.schema_name, table.table_name),
                sql.Identifier(order_col),
            )
            cur.execute(query, (current_batch, offset))
            batch = cur.fetchall()
            if not batch:
                break
            yield [tuple(row) for row in batch]
            offset += current_batch
            logger.info(
                "Fetched %d/%d records from %s", offset, fetch_limit, table.full_name
            )


def _get_order_column(cur, table: TableConfig) -> str:
    cur.execute(
        """
        SELECT a.attname
        FROM pg_catalog.pg_attribute a
        JOIN pg_catalog.pg_class c ON a.attrelid = c.oid
        JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid
        WHERE n.nspname = %s AND c.relname = %s
          AND a.attnum > 0 AND NOT a.attisdropped
          AND a.attidentity IN ('a', 'd')
        ORDER BY a.attnum
        LIMIT 1
        """,
        (table.schema_name, table.table_name),
    )
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute(
        """
        SELECT a.attname
        FROM pg_catalog.pg_index i
        JOIN pg_catalog.pg_attribute a
          ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        JOIN pg_catalog.pg_class c ON i.indrelid = c.oid
        JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid
        WHERE n.nspname = %s AND c.relname = %s
          AND i.indisprimary
        ORDER BY a.attnum
        LIMIT 1
        """,
        (table.schema_name, table.table_name),
    )
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
          AND (data_type LIKE 'timestamp%' OR data_type LIKE 'date%')
        ORDER BY ordinal_position
        LIMIT 1
        """,
        (table.schema_name, table.table_name),
    )
    row = cur.fetchone()
    if row:
        return row[0]

    logger.warning(
        "No identity/pk/timestamp column found for %s — falling back to ctid "
        "(ordering may be unreliable after VACUUM)",
        table.full_name,
    )
    return "ctid"


# ──────────────────────────────────────────────
#  TARGET DB — WRITE QUERIES (local only)
# ──────────────────────────────────────────────

def schema_exists(db: DatabaseManager, schema: str) -> bool:
    with db.cursor() as cur:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = %s)",
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
                    col_def,
                    ', '
                    ORDER BY a.attnum
                ) || ')' AS ddl
            FROM (
                SELECT
                    a.attnum,
                    quote_ident(a.attname) || ' ' ||
                    pg_catalog.format_type(a.atttypid, a.atttypmod) ||
                    CASE
                        WHEN a.attidentity = 'a' THEN ' GENERATED BY DEFAULT AS IDENTITY'
                        WHEN a.attidentity = 'd' THEN ' GENERATED ALWAYS AS IDENTITY'
                        ELSE ''
                    END ||
                    CASE WHEN a.attnotnull THEN ' NOT NULL' ELSE '' END ||
                    CASE WHEN d.adbin IS NOT NULL
                        THEN ' DEFAULT ' || pg_catalog.pg_get_expr(d.adbin, d.adrelid)
                        ELSE ''
                    END AS col_def
                FROM pg_catalog.pg_attribute a
                JOIN pg_catalog.pg_class c ON a.attrelid = c.oid
                JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid
                LEFT JOIN pg_catalog.pg_attrdef d
                    ON a.attrelid = d.adrelid AND a.attnum = d.adnum
                WHERE n.nspname = %s
                  AND c.relname = %s
                  AND a.attnum > 0
                  AND NOT a.attisdropped
            ) sub
            """,
            (
                table.schema_name, table.table_name,
                table.schema_name, table.table_name,
            ),
        )
        row = cur.fetchone()
        return row[0] if row else None


def create_table(db: DatabaseManager, table: TableConfig, ddl: str):
    with db.cursor() as cur:
        cur.execute(ddl)
    logger.info("Created table '%s' in target", table.full_name)


def insert_records_batch(
    db: DatabaseManager,
    table: TableConfig,
    columns: List[str],
    records: List[tuple],
):
    if not records:
        return

    insert_sql = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
        sql.Identifier(table.schema_name, table.table_name),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
    )

    with db.cursor() as cur:
        execute_values(cur, insert_sql, records, template=None, page_size=len(records))


def insert_records_stream(
    db: DatabaseManager,
    table: TableConfig,
    columns: List[str],
    record_stream: Generator[List[tuple], None, None],
    batch_size: int,
) -> int:
    total = 0
    for batch in record_stream:
        insert_records_batch(db, table, columns, batch)
        total += len(batch)
        logger.info(
            "Inserted %d records into %s (running total: %d)",
            len(batch),
            table.full_name,
            total,
        )
    return total
