# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: GPL-3.0-or-later

"""CSV (de)serialization for the contestants exchange (WeighIn side).

Sibling format to ``contestants_*.json`` — a 1:1 mirror of the same schema,
read/written by both edv and WeighIn. See the ``contestants_*.csv`` cross-repo
invariant in ``WSP/CLAUDE.md`` (Decision 2026-06-03). This is a by-convention
copy of edv's ``backend/services/contestants_csv.py`` — keep them in lockstep.

Contract:
- Columns (canonical order, header row mandatory, English JSON keys):
  ``ID;Firstname;Lastname;Birthyear;Club;Association;Weight;Valid;Gender;Paid;Doublestart``
- Delimiter ``;``, encoding UTF-8 **with BOM** (write BOM; read ``utf-8-sig``).
- Write canonically (Valid/Paid -> true/false, Weight with ``.``, Gender verbatim,
  Doublestart verbatim — sourced from ``Doublestart`` OR WeighIn's legacy ``mode``).
- Read tolerantly (bool synonyms, ``.``/``,`` decimal, ``Doublestart``|``mode``).
"""

import csv
from typing import Any, Dict, List

CONTESTANTS_CSV_FIELDS = [
    "ID", "Firstname", "Lastname", "Birthyear", "Club",
    "Association", "Weight", "Valid", "Gender", "Paid", "Doublestart",
]

CSV_DELIMITER = ";"
CSV_ENCODING = "utf-8-sig"

_TRUE_TOKENS = {"true", "1", "ja", "yes", "y", "wahr", "x"}
_FALSE_TOKENS = {"false", "0", "nein", "no", "n", "falsch", ""}


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    token = str(value or "").strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    return False


def _parse_weight(value: Any):
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return value


def _parse_int(value: Any):
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return value


def _format_weight(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return repr(value)
    return str(value)


def read_contestants_csv(path: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with open(path, "r", encoding=CSV_ENCODING, newline="") as f:
        reader = csv.DictReader(f, delimiter=CSV_DELIMITER)
        for row in reader:
            if row is None:
                continue
            if not any(str(v or "").strip() for v in row.values()):
                continue

            def get(key: str):
                v = row.get(key)
                return v.strip() if isinstance(v, str) else v

            d: Dict[str, Any] = {}
            if str(get("ID") or "").strip():
                d["ID"] = _parse_int(get("ID"))
            for key in ("Firstname", "Lastname", "Club", "Association", "Gender"):
                v = get(key)
                if v is not None:
                    d[key] = v or ""
            if str(get("Birthyear") or "").strip():
                d["Birthyear"] = _parse_int(get("Birthyear"))
            if str(get("Weight") or "").strip():
                d["Weight"] = _parse_weight(get("Weight"))
            for key in ("Valid", "Paid"):
                v = get(key)
                if v is not None and str(v).strip() != "":
                    d[key] = _parse_bool(v)
            ds = get("Doublestart") or get("mode")
            if ds:
                d["Doublestart"] = ds
            # Mirror the JSON path: ensure a display Name exists.
            if d.get("Firstname") or d.get("Lastname"):
                d.setdefault("Name", f"{d.get('Firstname', '')} {d.get('Lastname', '')}".strip())
            out.append(d)
    return out


def write_contestants_csv(path: str, contestants: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding=CSV_ENCODING, newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=CONTESTANTS_CSV_FIELDS, delimiter=CSV_DELIMITER,
            extrasaction="ignore", lineterminator="\r\n",
        )
        writer.writeheader()
        for c in contestants:
            row: Dict[str, Any] = {}
            for key in CONTESTANTS_CSV_FIELDS:
                value = c.get(key)
                if key in ("Valid", "Paid"):
                    row[key] = "true" if _parse_bool(value) else "false"
                elif key == "Doublestart":
                    # `mode` first: WeighIn's legacy `mode` is the fresh UI edit
                    # and must win over a stale `Doublestart` from a prior load.
                    ds = c.get("mode") or c.get("Doublestart")
                    row[key] = str(ds).strip() if ds else "standard"
                elif key == "Weight":
                    row[key] = _format_weight(value)
                elif value is None:
                    row[key] = ""
                else:
                    row[key] = value
            writer.writerow(row)
