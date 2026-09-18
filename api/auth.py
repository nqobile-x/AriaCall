from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import Header, HTTPException, Security
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_COMPANIES_FILE = Path(__file__).parent.parent / "companies.json"


def _load_companies() -> dict:
    try:
        return json.loads(_COMPANIES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def verify_api_key(x_api_key: str | None = Security(_api_key_header)) -> dict:
    """FastAPI dependency — returns company dict or raises 401."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header.")
    companies = _load_companies()
    company = companies.get(x_api_key)
    if not company:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return company


def get_company_id(x_api_key: str | None = Security(_api_key_header)) -> str:
    """Shortcut dependency — returns just the company_id."""
    return verify_api_key(x_api_key)["company_id"]
