"""Masking for row values that leave the platform: for an agent, or in a prompt to a model.

One rule everywhere, the same one run_sql applies: a column is personal when the
profile tagged it so, or when its name says so (``query.is_personal``). Its values
are replaced; e-mail addresses and phone numbers are redacted from every other
text value. Geography follows the SQL_MASK_GEOGRAPHY setting.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

from kairos_kb.config import get_settings
from kairos_kb.context.files import redact_values
from kairos_kb.context.query import MASK, is_personal

_PERSONAL_TAGS = ("pii", "personal")


def tagged_personal(shape_columns: Optional[Iterable[Any]]) -> Set[str]:
    """Column names a profile's shape tags as personal data (lower-case)."""
    out: Set[str] = set()
    for c in shape_columns or []:
        if isinstance(c, dict) and c.get("name"):
            tags = str(c.get("tags") or "").lower()
            if any(t in tags for t in _PERSONAL_TAGS):
                out.add(str(c["name"]).lower())
    return out


def is_masked(column: str, tagged: Set[str], geography: Optional[bool] = None) -> bool:
    geo = get_settings().sql_mask_geography if geography is None else geography
    return column.lower() in tagged or is_personal(column, geography=geo)


def mask_rows(rows: List[Dict[str, Any]], tagged: Optional[Set[str]] = None,
              geography: Optional[bool] = None) -> List[Dict[str, Any]]:
    """Rows with personal columns masked and e-mails / phone numbers redacted from the rest."""
    tagged = {t.lower() for t in tagged or ()}
    masked_cols: Dict[str, bool] = {}
    out = []
    for row in rows:
        clean: Dict[str, Any] = {}
        for key, value in row.items():
            if key not in masked_cols:
                masked_cols[key] = is_masked(str(key), tagged, geography)
            if masked_cols[key] and value is not None:
                clean[key] = MASK
            elif isinstance(value, str):
                clean[key] = redact_values(value)
            else:
                clean[key] = value
        out.append(clean)
    return out
