from pathlib import Path
from typing import List

import yaml

from models.schemas import TableConfig


def load_tables_from_yaml(yaml_path: str) -> List[TableConfig]:
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"YAML config file not found: {yaml_path}")

    with open(path, "r") as f:
        data = yaml.safe_load(f)

    if not data or "tables" not in data:
        raise ValueError("YAML file must contain a 'tables' key with a list of tables")

    raw_tables: List[str] = data["tables"]
    return [TableConfig.from_string(t) for t in raw_tables]
