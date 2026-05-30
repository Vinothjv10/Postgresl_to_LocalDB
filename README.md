# Postgres_to_LocalDB

Migrate the last **1,00,000 records** from each PostgreSQL table (source) into a local PostgreSQL database (target).

## Project Structure

```
├── config/
│   ├── settings.py           # Loads .env and exposes DSNs + batch config
│   └── yaml_config.py        # Reads tables_config.yaml
├── database/
│   ├── connection.py         # DatabaseManager — connection lifecycle + context managers
│   └── operations.py         # Source: SELECT only · Target: CREATE / INSERT
├── services/
│   └── migrator.py           # DataMigrator — orchestrates migration per table
├── models/
│   └── schemas.py            # TableConfig & AppConfig dataclasses
├── venv/                     # Virtual environment (not committed)
├── main.py                   # CLI entry point
├── tables_config.yaml        # List of schema.table to migrate
├── .env                      # DB credentials (not committed)
└── .env.example              # Template for .env
```

## Setup

```bash
# Create virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure credentials
cp .env.example .env
# Edit .env with your source and target DB credentials
```

## Usage

```bash
source venv/bin/activate

# List configured tables
python main.py --list-tables

# Run migration
python main.py

# Override defaults
python main.py --limit 50000 --batch-size 5000
```

## Key Design

| Layer | Directory | Responsibility |
|-------|-----------|----------------|
| **Config** | `config/` | .env resolution, YAML table list |
| **Database** | `database/` | Connection mgmt, source reads (SELECT only), target writes |
| **Service** | `services/` | Migration orchestration |
| **Models** | `models/` | Typed dataclasses |

## Safety

- **Source database** is strictly read-only — only `SELECT` queries are issued.
- **Target database** receives schema creation (`CREATE TABLE IF NOT EXISTS`) and `INSERT` operations.
- All write operations (`CREATE SCHEMA`, `CREATE TABLE`, `INSERT`) run exclusively on the **local target**.
