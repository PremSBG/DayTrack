"""
Turso HTTP Client
=================
Pure Python client for Turso database via HTTP API.
No Rust, no compilation, works everywhere.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class TursoClient:
    """HTTP client for Turso database."""

    def __init__(self, url: str, token: str):
        # Convert libsql:// to https://
        self.base_url = url.replace("libsql://", "https://")
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def execute(self, sql: str, args: Optional[list] = None) -> Dict[str, Any]:
        """Execute a single SQL statement."""
        stmt = {"type": "execute", "stmt": {"sql": sql}}
        if args:
            stmt["stmt"]["args"] = [self._convert_arg(a) for a in args]

        payload = {"requests": [stmt, {"type": "close"}]}
        resp = requests.post(
            f"{self.base_url}/v2/pipeline",
            headers=self.headers,
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if results and results[0].get("type") == "ok":
            return results[0]["response"]["result"]
        elif results and results[0].get("type") == "error":
            error = results[0].get("error", {})
            raise Exception(f"Turso error: {error.get('message', 'Unknown')}")
        return {}

    def execute_batch(self, statements: List[dict]) -> List[Dict]:
        """Execute multiple SQL statements in a batch."""
        reqs = []
        for s in statements:
            stmt = {"type": "execute", "stmt": {"sql": s["sql"]}}
            if s.get("args"):
                stmt["stmt"]["args"] = [self._convert_arg(a) for a in s["args"]]
            reqs.append(stmt)
        reqs.append({"type": "close"})

        resp = requests.post(
            f"{self.base_url}/v2/pipeline",
            headers=self.headers,
            json={"requests": reqs},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", [])

    def _convert_arg(self, value) -> dict:
        """Convert Python value to Turso wire format."""
        if value is None:
            return {"type": "null", "value": None}
        elif isinstance(value, int):
            return {"type": "integer", "value": str(value)}
        elif isinstance(value, float):
            return {"type": "float", "value": value}
        else:
            return {"type": "text", "value": str(value)}

    def rows_to_dicts(self, result: dict) -> List[dict]:
        """Convert Turso result to list of dicts."""
        cols = [c["name"] for c in result.get("cols", [])]
        rows = result.get("rows", [])
        return [{cols[i]: row[i].get("value") for i in range(len(cols))} for row in rows]

    def first_row(self, result: dict) -> Optional[dict]:
        """Get first row as dict or None."""
        dicts = self.rows_to_dicts(result)
        return dicts[0] if dicts else None

    def last_insert_id(self, result: dict) -> int:
        """Get last insert rowid."""
        return result.get("last_insert_rowid", 0)

    def affected_rows(self, result: dict) -> int:
        """Get affected row count."""
        return result.get("affected_row_count", 0)
