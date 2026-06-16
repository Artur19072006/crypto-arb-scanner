from pathlib import Path


DEFAULT_DATABASE_PATH = Path("data/scanner.sqlite3")


def get_database_path() -> Path:
    # TODO: Initialize SQLite schema for spread history, alerts, settings, and blacklist.
    return DEFAULT_DATABASE_PATH
