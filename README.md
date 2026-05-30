# Postgres_to_LocalDB

Migrate the last **1,00,000 records** from each PostgreSQL table (source) into a local PostgreSQL database (target).

## Project Structure

```
├── config/
│   ├── settings.py           # Loads env/<env>/.env and exposes DSNs + batch config
│   └── yaml_config.py        # Reads tables_config.yaml
├── database/
│   ├── connection.py         # DatabaseManager — connection lifecycle + context managers
│   └── operations.py         # Source: SELECT only · Target: CREATE / INSERT
├── services/
│   └── migrator.py           # DataMigrator — orchestrates migration per table
├── models/
│   └── schemas.py            # TableConfig & AppConfig dataclasses
├── env/                      # Environment-specific .env files
│   ├── dev/.env
│   ├── staging/.env
│   └── prod/.env
├── main.py                   # CLI entry point
└── tables_config.yaml        # List of schema.table to migrate
```

## Usage

```bash
# Install dependencies
pip install -r requirements.txt

# Set up your env file (edit env/<env>/.env with your DB credentials)
cp .env.example env/dev/.env

# List tables
python main.py --env dev --list-tables

# Run migration
python main.py --env dev

# Override limits
python main.py --env dev --limit 50000 --batch-size 5000
```

### Key Design

| Layer | Directory | Responsibility |
|-------|-----------|----------------|
| **Config** | `config/` | Environment resolution (env folder), YAML table list |
| **Database** | `database/` | Connection mgmt, source reads (SELECT only), target writes |
| **Service** | `services/` | Migration orchestration |
| **Models** | `models/` | Typed dataclasses |

### Safety

- **Source database** is strictly read-only — only `SELECT` queries are issued.
- **Target database** receives schema creation (`CREATE TABLE IF NOT EXISTS`) and `INSERT` operations.
- All write operations (`CREATE SCHEMA`, `CREATE TABLE`, `INSERT`) run exclusively on the **local target**.
