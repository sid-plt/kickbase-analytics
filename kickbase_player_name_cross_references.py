"""Confirmed provider-scoped display-name mappings for name-only lineup sources."""

from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

import pandas as pd


REFERENCE_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "reference"
    / "kickbase_player_name_cross_references.csv"
)
REFERENCE_COLUMNS = (
    "source",
    "canonical_team",
    "kbstats_name",
    "displayed_name",
    "created_at",
)
NAME_ONLY_LINEUP_SOURCES = frozenset({"kickbase", "kicker"})


def _key(value: object) -> str:
    """Normalize names only to detect duplicate persisted mappings."""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _validate(frame: pd.DataFrame) -> pd.DataFrame:
    if list(frame.columns) != list(REFERENCE_COLUMNS):
        raise ValueError(f"Name-only lineup cross references must use columns {list(REFERENCE_COLUMNS)}")
    output = frame.loc[:, list(REFERENCE_COLUMNS)].copy()
    for column in REFERENCE_COLUMNS:
        output[column] = output[column].fillna("").astype(str).str.strip()
    invalid = output.eq("").any(axis=1)
    if invalid.any():
        raise ValueError("Name-only lineup cross references contain empty required fields.")
    output["source"] = output["source"].str.casefold()
    if not output["source"].isin(NAME_ONLY_LINEUP_SOURCES).all():
        raise ValueError(
            "Name-only lineup cross references contain an unsupported source; "
            f"expected one of {sorted(NAME_ONLY_LINEUP_SOURCES)}."
        )
    mapping_key = list(
        zip(
            output["source"],
            output["canonical_team"].str.casefold(),
            output["kbstats_name"].map(_key),
        )
    )
    if pd.Series(mapping_key).duplicated().any():
        raise ValueError("Name-only lineup cross references contain duplicate source/team/KBStats mappings.")
    return output


def load_references(path: Path = REFERENCE_PATH) -> pd.DataFrame:
    """Load confirmed mappings for Kickbase and Kicker without provider IDs."""
    if not path.exists():
        return pd.DataFrame(columns=REFERENCE_COLUMNS)
    try:
        frame = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    except (OSError, UnicodeError, pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        raise ValueError(f"Could not read name-only lineup cross references {path}: {exc}") from exc
    return _validate(frame)


def persist_references(references: pd.DataFrame, path: Path = REFERENCE_PATH) -> None:
    """Validate and atomically replace the name-only lineup mapping store."""
    output = _validate(references)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    try:
        output.to_csv(temporary_path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
        temporary_path.replace(path)
    except OSError as exc:
        raise OSError(f"Could not save Kickbase cross references to {path}: {exc}") from exc
