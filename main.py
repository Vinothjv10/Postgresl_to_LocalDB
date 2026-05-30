import argparse
import logging
import sys

from config.settings import settings
from config.yaml_config import load_tables_from_yaml
from database.connection import DatabaseManager
from services.migrator import DataMigrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Migrate last N records from source PostgreSQL tables to local PostgreSQL."
    )
    parser.add_argument(
        "-c", "--config",
        default="tables_config.yaml",
        help="Path to YAML config file with table list (default: tables_config.yaml)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Override record limit per table (default: from .env or 100000)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Override batch size for fetch/insert (default: from .env or 10000)",
    )
    parser.add_argument(
        "--list-tables",
        action="store_true",
        help="Only list the tables from config and exit",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        tables = load_tables_from_yaml(args.config)
    except (FileNotFoundError, ValueError) as e:
        logger.error(e)
        sys.exit(1)

    if args.list_tables:
        print(f"Tables loaded from '{args.config}':")
        for t in tables:
            print(f"  - {t.full_name}")
        print(f"\nTotal: {len(tables)} tables")
        return

    logger.info("Loaded %d tables from '%s'", len(tables), args.config)
    for t in tables:
        logger.info("  - %s", t.full_name)

    if args.limit:
        settings.limit = args.limit
    if args.batch_size:
        settings.batch_size = args.batch_size

    source_db = DatabaseManager(settings.source_dsn)
    target_db = DatabaseManager(settings.target_dsn)

    try:
        migrator = DataMigrator(tables, source_db, target_db, settings)
        migrator.run()
    finally:
        source_db.close()
        target_db.close()


if __name__ == "__main__":
    main()
