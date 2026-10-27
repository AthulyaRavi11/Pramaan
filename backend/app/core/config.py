"""Loads YAML configuration and runtime settings."""
from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parents[2]          # backend/
CONFIG_DIR = BASE_DIR / "app" / "config"
DATA_DIR = Path(os.environ.get("PRAMAAN_DATA_DIR", BASE_DIR / "data"))
STORAGE_DIR = Path(os.environ.get("PRAMAAN_STORAGE_DIR", BASE_DIR / "storage"))
DB_PATH = Path(os.environ.get("PRAMAAN_DB", BASE_DIR / "storage" / "pramaan.db"))

JWT_SECRET = os.environ.get("PRAMAAN_JWT_SECRET", "dev-only-change-me-0123456789abcdef-pramaan")
JWT_TTL_MIN = int(os.environ.get("PRAMAAN_JWT_TTL_MIN", "480"))
RETENTION_DAYS = int(os.environ.get("PRAMAAN_RETENTION_DAYS", "1825"))
MAX_UPLOAD_MB = int(os.environ.get("PRAMAAN_MAX_UPLOAD_MB", "15"))
ALLOWED_MIME = {"application/pdf", "image/png", "image/jpeg"}


def _load(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def documents() -> dict:
    return _load("documents.yaml")


def categories() -> dict:
    return _load("categories.yaml")


def sources() -> dict:
    return _load("sources.yaml")


def infra_norms() -> dict:
    return _load("infra_norms.yaml")


def reload_all() -> None:
    pass


def ruleset_fingerprint() -> str:
    """Hash of every config file, recorded with each validation run (audit)."""
    h = hashlib.sha256()
    for name in sorted(os.listdir(CONFIG_DIR)):
        if name.endswith(".yaml"):
            h.update((CONFIG_DIR / name).read_bytes())
    return h.hexdigest()[:16]


@lru_cache
def institutional_records() -> dict:
    """Mock of records held in authorized AICTE systems (synthetic data)."""
    with open(DATA_DIR / "aicte_records.json", encoding="utf-8") as f:
        return json.load(f)
