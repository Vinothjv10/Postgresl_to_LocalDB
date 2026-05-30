import os
from pathlib import Path

from dotenv import load_dotenv


class Settings:
    def __init__(self, env: str = "dev"):
        env_file = Path(__file__).resolve().parent.parent / "env" / env / ".env"
        if not env_file.exists():
            raise FileNotFoundError(
                f"Environment file not found: {env_file}. "
                f"Available environments: dev, staging, prod"
            )
        load_dotenv(env_file)

        self.source_host: str = os.getenv("SOURCE_DB_HOST", "localhost")
        self.source_port: int = int(os.getenv("SOURCE_DB_PORT", "5432"))
        self.source_db: str = os.getenv("SOURCE_DB_NAME", "source_db")
        self.source_user: str = os.getenv("SOURCE_DB_USER", "postgres")
        self.source_password: str = os.getenv("SOURCE_DB_PASSWORD", "postgres")

        self.target_host: str = os.getenv("TARGET_DB_HOST", "localhost")
        self.target_port: int = int(os.getenv("TARGET_DB_PORT", "5432"))
        self.target_db: str = os.getenv("TARGET_DB_NAME", "local_db")
        self.target_user: str = os.getenv("TARGET_DB_USER", "postgres")
        self.target_password: str = os.getenv("TARGET_DB_PASSWORD", "postgres")

        self.batch_size: int = int(os.getenv("BATCH_SIZE", "10000"))
        self.limit: int = int(os.getenv("RECORD_LIMIT", "100000"))

    @property
    def source_dsn(self) -> str:
        return f"postgresql://{self.source_user}:{self.source_password}@{self.source_host}:{self.source_port}/{self.source_db}"

    @property
    def target_dsn(self) -> str:
        return f"postgresql://{self.target_user}:{self.target_password}@{self.target_host}:{self.target_port}/{self.target_db}"


settings: Settings = None
