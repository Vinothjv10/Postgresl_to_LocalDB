from dataclasses import dataclass, field
from typing import List

@dataclass
class TableConfig:
    schema_name: str
    table_name: str

    @property
    def full_name(self) -> str:
        return f"{self.schema_name}.{self.table_name}"

    @staticmethod
    def from_string(value: str) -> "TableConfig":
        parts = value.strip().split(".", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid table format '{value}'. Expected 'schema.table_name'")
        return TableConfig(schema_name=parts[0], table_name=parts[1])


@dataclass
class AppConfig:
    tables: List[TableConfig] = field(default_factory=list)
    batch_size: int = 10000
    limit: int = 100000
