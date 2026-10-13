"""Configuration from the environment.

Every setting is an environment variable; `.env` in the project folder is read
for convenience (see `.env.example`). A variable that is already set wins over
the file. Setting AUDITIQ_NO_DOTENV makes the application ignore the file,
which is what the tests do so that they never touch a developer's database or
model.

    AUDITIQ_DATABASE_URL    postgresql://user:password@host:port/database
    AUDITIQ_DB              SQLite file, used when no URL is set
    AUDITIQ_LLM_*           the chat model (auditiq/llm.py)
    AUDITIQ_EMBED_*         the embedding model (auditiq/retrieval.py)
    AUDITIQ_LOG_LEVEL       DEBUG, INFO (default), WARNING
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


def load_env(env_file: Path | None = ENV_FILE) -> None:
    """Read the `.env` file into the environment, unless AUDITIQ_NO_DOTENV is set."""
    if env_file is not None and not os.environ.get("AUDITIQ_NO_DOTENV"):
        load_dotenv(env_file)


def configure_logging() -> None:
    """One log format for the command line and the dashboard; the level comes from AUDITIQ_LOG_LEVEL."""
    load_env()
    logging.basicConfig(level=os.environ.get("AUDITIQ_LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
