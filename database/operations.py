import logging
from typing import Generator, List, Optional

from psycopg2 import sql
from psycopg2.extras import execute_values

from database.connection import DatabaseManager
from models.schemas import TableConfig

logger = logging.getLogger(__name__)


def _log_query(query, params=None):
    q = query if isinstance(query, str) else query.as_string(None)
    logger.info("SQL: %s", q.replace("\n", " ").strip())
    if params:
        logger.info("PARAMS: %s", params)


# ──────────────────────────────────────────────
#  SOURCE DB — READ-ONLY QUERIES (SELECT only)
# ──────────────────────────────────────────────

def fetch_table_columns(db: DatabaseManager, table: TableConfig) -> List[str]:
    q = (
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s "
        "ORDER BY ordinal_position"
    )
    logger.info("SQL: %s", q)
    logger.info("PARAMS: schema=%s table=%s", table.schema_name, table.table_name)
    with db.cursor() as cur:
        cur.execute(q, (table.schema_name, table.table_name))
        cols = [row[0] for row in cur.fetchall()]
    logger.info("RESULT: %d columns found: %s", len(cols), cols)
    return cols


def stream_records(
    db: DatabaseManager,
    table: TableConfig,
    limit: int,
    batch_size: int,
) -> Generator[List[tuple], None, None]:
    with db.cursor() as cur:
        count_sql = sql.SQL("SELECT COUNT(*) FROM {}").format(
            sql.Identifier(table.schema_name, table.table_name)
        )
        logger.info("SQL: %s", count_sql.as_string(cur).replace("\n", " "))
        cur.execute(count_sql)
        total = cur.fetchone()[0]
        logger.info("RESULT: total rows in %s = %d", table.full_name, total)

        if total == 0:
            logger.info("Table %s is empty — nothing to fetch", table.full_name)
            return

        fetch_limit = min(limit, total)
        logger.info(
            "Will fetch %d rows (limit=%d, total=%d)",
            fetch_limit, limit, total,
        )

        order_col = _get_order_column(cur, table)
        logger.info("Order column selected: %s", order_col)

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
            logger.info(
                "SQL: SELECT * FROM %s ORDER BY %s DESC LIMIT %s OFFSET %s",
                table.full_name, order_col, current_batch, offset,
            )
            cur.execute(query, (current_batch, offset))
            batch = cur.fetchall()
            rows = [tuple(row) for row in batch]
            logger.info(
                "BATCH: offset=%d limit=%d fetched=%d rows",
                offset, current_batch, len(rows),
            )
            if not rows:
                logger.info("BATCH: empty result — stopping")
                break
            yield rows
            offset += current_batch


def _get_order_column(cur, table: TableConfig) -> str:
    q1 = (
        "SELECT a.attname "
        "FROM pg_catalog.pg_attribute a "
        "JOIN pg_catalog.pg_class c ON a.attrelid = c.oid "
        "JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid "
        "WHERE n.nspname = %s AND c.relname = %s "
        "AND a.attnum > 0 AND NOT a.attisdropped "
        "AND a.attidentity IN ('a', 'd') "
        "ORDER BY a.attnum LIMIT 1"
    )
    logger.info("SQL: check identity column — %s", q1)
    logger.info("PARAMS: schema=%s table=%s", table.schema_name, table.table_name)
    cur.execute(q1, (table.schema_name, table.table_name))
    row = cur.fetchone()
    if row:
        logger.info("RESULT: identity column → %s", row[0])
        return row[0]

    q2 = (
        "SELECT a.attname "
        "FROM pg_catalog.pg_index i "
        "JOIN pg_catalog.pg_attribute a "
        "  ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
        "JOIN pg_catalog.pg_class c ON i.indrelid = c.oid "
        "JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid "
        "WHERE n.nspname = %s AND c.relname = %s "
        "AND i.indisprimary "
        "ORDER BY a.attnum LIMIT 1"
    )
    logger.info("SQL: check primary key — %s", q2)
    cur.execute(q2, (table.schema_name, table.table_name))
    row = cur.fetchone()
    if row:
        logger.info("RESULT: primary key column → %s", row[0])
        return row[0]

    q3 = (
        "SELECT column_name "
        "FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s "
        "AND (data_type LIKE 'timestamp%%' OR data_type LIKE 'date%%') "
        "ORDER BY ordinal_position LIMIT 1"
    )
    logger.info("SQL: check timestamp/date column — %s", q3)
    cur.execute(q3, (table.schema_name, table.table_name))
    row = cur.fetchone()
    if row:
        logger.info("RESULT: timestamp/date column → %s", row[0])
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
    q = (
        "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = %s)"
    )
    logger.info("SQL: %s", q)
    logger.info("PARAMS: schema=%s", schema)
    with db.cursor() as cur:
        cur.execute(q, (schema,))
        exists = cur.fetchone()[0]
    logger.info("RESULT: schema '%s' exists = %s", schema, exists)
    return exists


def create_schema(db: DatabaseManager, schema: str):
    q = sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
    logger.info("SQL: %s", q.as_string(None).replace("\n", " "))
    with db.cursor() as cur:
        cur.execute(q)
    logger.info("RESULT: schema '%s' created", schema)


def table_exists(db: DatabaseManager, table: TableConfig) -> bool:
    q = (
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = %s AND table_name = %s)"
    )
    logger.info("SQL: %s", q)
    logger.info("PARAMS: schema=%s table=%s", table.schema_name, table.table_name)
    with db.cursor() as cur:
        cur.execute(q, (table.schema_name, table.table_name))
        exists = cur.fetchone()[0]
    logger.info("RESULT: table '%s' exists = %s", table.full_name, exists)
    return exists


def build_create_table_ddl(source_db: DatabaseManager, table: TableConfig) -> Optional[str]:
    q = (
        "SELECT 'CREATE TABLE ' || quote_ident(%s) || '.' || quote_ident(%s) || ' (' || "
        "string_agg(col_def, ', ' ORDER BY attnum) || ')' AS ddl "
        "FROM ("
        "SELECT a.attnum, "
        "quote_ident(a.attname) || ' ' || pg_catalog.format_type(a.atttypid, a.atttypmod) || "
        "CASE WHEN a.attidentity = 'a' THEN ' GENERATED BY DEFAULT AS IDENTITY' "
        "WHEN a.attidentity = 'd' THEN ' GENERATED ALWAYS AS IDENTITY' ELSE '' END || "
        "CASE WHEN a.attnotnull THEN ' NOT NULL' ELSE '' END || "
        "CASE WHEN d.adbin IS NOT NULL THEN ' DEFAULT ' || pg_catalog.pg_get_expr(d.adbin, d.adrelid) ELSE '' END "
        "AS col_def "
        "FROM pg_catalog.pg_attribute a "
        "JOIN pg_catalog.pg_class c ON a.attrelid = c.oid "
        "JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid "
        "LEFT JOIN pg_catalog.pg_attrdef d ON a.attrelid = d.adrelid AND a.attnum = d.adnum "
        "WHERE n.nspname = %s AND c.relname = %s "
        "AND a.attnum > 0 AND NOT a.attisdropped"
        ") sub"
    )
    logger.info("SQL: build DDL for %s", table.full_name)
    with source_db.cursor() as cur:
        cur.execute(
            q,
            (table.schema_name, table.table_name, table.schema_name, table.table_name),
        )
        row = cur.fetchone()
    ddl = row[0] if row else None
    logger.info("RESULT: DDL = %s", ddl)
    return ddl


def create_table(db: DatabaseManager, table: TableConfig, ddl: str):
    logger.info("SQL: %s", ddl)
    with db.cursor() as cur:
        cur.execute(ddl)
    logger.info("RESULT: table '%s' created in target", table.full_name)


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
    logger.info(
        "SQL: INSERT INTO %s (%s) VALUES %%s [batch of %d rows]",
        table.full_name, ", ".join(columns), len(records),
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
    for batch_idx, batch in enumerate(record_stream, start=1):
        logger.info(
            "INSERT BATCH #%d: inserting %d rows into %s",
            batch_idx, len(batch), table.full_name,
        )
        insert_records_batch(db, table, columns, batch)
        total += len(batch)
        logger.info(
            "INSERT BATCH #%d: done — %d rows inserted (cumulative: %d)",
            batch_idx, len(batch), total,
        )
    return total
