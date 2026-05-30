from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import os


class Settings:
    source_host: str = os.getenv("SOURCE_DB_HOST", "localhost")
    source_port: int = int(os.getenv("SOURCE_DB_PORT", "5432"))
    source_db: str = os.getenv("SOURCE_DB_NAME", "source_db")
    source_user: str = os.getenv("SOURCE_DB_USER", "postgres")
    source_password: str = os.getenv("SOURCE_DB_PASSWORD", "postgres")

    target_host: str = os.getenv("TARGET_DB_HOST", "localhost")
    target_port: int = int(os.getenv("TARGET_DB_PORT", "5432"))
    target_db: str = os.getenv("TARGET_DB_NAME", "local_db")
    target_user: str = os.getenv("TARGET_DB_USER", "postgres")
    target_password: str = os.getenv("TARGET_DB_PASSWORD", "postgres")

    batch_size: int = int(os.getenv("BATCH_SIZE", "10000"))
    limit: int = int(os.getenv("RECORD_LIMIT", "100000"))

    @property
    def source_dsn(self) -> str:
        return f"postgresql://{self.source_user}:{self.source_password}@{self.source_host}:{self.source_port}/{self.source_db}"

    @property
    def target_dsn(self) -> str:
        return f"postgresql://{self.target_user}:{self.target_password}@{self.target_host}:{self.target_port}/{self.target_db}"


settings = Settings()
