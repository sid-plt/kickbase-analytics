"""Shared provider-to-KBStats player-name reference storage."""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd


REFERENCE_PATH = Path(__file__).resolve().parent / "data" / "reference" / "player_name_cross_references.csv"
REFERENCE_COLUMNS = (
    "provider",
    "canonical_team",
    "kbstats_name",
    "provider_player_id",
    "provider_player_name",
    "created_at",
)


def load_references(path: Path = REFERENCE_PATH) -> pd.DataFrame:
    """Load and validate all provider mappings from the shared reference CSV."""
    if not path.exists():
        return pd.DataFrame(columns=REFERENCE_COLUMNS)
    try:
        frame = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    except (OSError, UnicodeError, pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        raise ValueError(f"Could not read player-name cross references {path}: {exc}") from exc
    if list(frame.columns) != list(REFERENCE_COLUMNS):
        raise ValueError(f"Player-name cross references must use columns {list(REFERENCE_COLUMNS)}")
    if frame.empty:
        return frame
    frame = frame.copy()
    for column in REFERENCE_COLUMNS:
        frame[column] = frame[column].astype(str).str.strip()
    frame["provider_player_id"] = pd.to_numeric(frame["provider_player_id"], errors="coerce")
    invalid = (
        frame["provider"].eq("")
        | frame["kbstats_name"].eq("")
        | frame["provider_player_name"].eq("")
        | frame["created_at"].eq("")
        | frame["provider_player_id"].isna()
        | frame["provider_player_id"].le(0)
    )
    if invalid.any():
        raise ValueError("Player-name cross references contain empty required fields or invalid provider IDs.")
    frame["provider_player_id"] = frame["provider_player_id"].astype(int)
    mapping_key = list(zip(frame["provider"], frame["canonical_team"], frame["kbstats_name"].str.casefold()))
    if pd.Series(mapping_key).duplicated().any():
        raise ValueError("Player-name cross references contain duplicate provider/team/KBStats mappings.")
    return frame.loc[:, list(REFERENCE_COLUMNS)]


def persist_references(references: pd.DataFrame, path: Path = REFERENCE_PATH) -> None:
    """Validate and replace the shared reference CSV content."""
    output = references.loc[:, list(REFERENCE_COLUMNS)].copy()
    # Reuse the full validation path without writing a temporary file.
    for column in REFERENCE_COLUMNS:
        output[column] = output[column].fillna("").astype(str).str.strip()
    output["provider_player_id"] = pd.to_numeric(output["provider_player_id"], errors="coerce")
    invalid = (
        output["provider"].eq("")
        | output["kbstats_name"].eq("")
        | output["provider_player_name"].eq("")
        | output["created_at"].eq("")
        | output["provider_player_id"].isna()
        | output["provider_player_id"].le(0)
    )
    if invalid.any():
        raise ValueError("Cannot save player-name cross references with empty required fields or invalid provider IDs.")
    output["provider_player_id"] = output["provider_player_id"].astype(int)
    mapping_key = list(zip(output["provider"], output["canonical_team"], output["kbstats_name"].str.casefold()))
    if pd.Series(mapping_key).duplicated().any():
        raise ValueError("Cannot save duplicate provider/team/KBStats mappings.")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    except OSError as exc:
        raise OSError(f"Could not save player-name cross references to {path}: {exc}") from exc
