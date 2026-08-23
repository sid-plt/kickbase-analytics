"""Create optimizer-ready Kickbase score CSVs from Transfermarkt market values."""

from __future__ import annotations

import csv
import math
import re
import unicodedata
import warnings
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd
from IPython.display import display

from project_paths import (
    EXPECTED_POINTS_DIR,
    KBSTATS_PLAYERS_DIR,
    TRANSFERMARKT_SQUADS_DIR,
    ensure_directory,
)
from player_name_cross_references import (
    REFERENCE_COLUMNS,
    REFERENCE_PATH,
    load_references,
    persist_references,
)


SCORE_COLUMN = "score"
OVERRIDE_PATH = REFERENCE_PATH
OVERRIDE_COLUMNS = (
    "kbstats_name",
    "transfermarkt_player_id",
    "transfermarkt_player_name",
    "created_at",
)
KBSTATS_FILENAME_RE = re.compile(
    r"^kbstats_players_(?P<timestamp>\d{8}_\d{6}_[+-]\d{4})\.csv$"
)
TRANSFERMARKT_FILENAME_RE = re.compile(
    r"^transfermarkt_bundesliga_squads_(?P<season>\d{4})_"
    r"(?P<timestamp>\d{8}_\d{6})\.csv$"
)
FUZZY_MATCH_THRESHOLD = 0.50
MAX_PROMPT_CANDIDATES = 5


@dataclass(frozen=True)
class InputFile:
    path: Path
    timestamp_text: str
    timestamp: datetime


def normalize_name(value: Any) -> str:
    """Normalize player names across provider spelling conventions."""
    if not isinstance(value, str) or not value.strip():
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", "", without_marks.casefold())


def _read_csv(path: Path, label: str) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"{label} is empty: {path}") from exc
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise ValueError(f"Could not read {label} {path}: {exc}") from exc
    if frame.empty:
        raise ValueError(f"{label} contains no data rows: {path}")
    return frame


def _select_latest_kbstats_csv() -> InputFile:
    if not KBSTATS_PLAYERS_DIR.is_dir():
        raise FileNotFoundError(f"KBStats player directory does not exist: {KBSTATS_PLAYERS_DIR}")
    candidates: list[InputFile] = []
    for path in sorted(KBSTATS_PLAYERS_DIR.glob("kbstats_players_*.csv")):
        match = KBSTATS_FILENAME_RE.fullmatch(path.name)
        if match is None:
            warnings.warn(f"Ignoring unsupported KBStats filename: {path.name}", stacklevel=2)
            continue
        try:
            timestamp = datetime.strptime(match.group("timestamp"), "%Y%m%d_%H%M%S_%z")
        except ValueError as exc:
            warnings.warn(f"Ignoring {path.name}: invalid timestamp ({exc})", stacklevel=2)
            continue
        candidates.append(InputFile(path, match.group("timestamp"), timestamp))
    if not candidates:
        raise FileNotFoundError(f"No valid KBStats player CSV found in {KBSTATS_PLAYERS_DIR}.")
    latest = max(item.timestamp for item in candidates)
    newest = [item for item in candidates if item.timestamp == latest]
    if len(newest) != 1:
        raise RuntimeError("Multiple KBStats player CSVs share the latest timestamp.")
    return newest[0]


def _select_latest_transfermarkt_csv() -> InputFile:
    if not TRANSFERMARKT_SQUADS_DIR.is_dir():
        raise FileNotFoundError(
            f"Transfermarkt squad directory does not exist: {TRANSFERMARKT_SQUADS_DIR}"
        )
    candidates: list[InputFile] = []
    for path in sorted(TRANSFERMARKT_SQUADS_DIR.glob("transfermarkt_bundesliga_squads_*.csv")):
        match = TRANSFERMARKT_FILENAME_RE.fullmatch(path.name)
        if match is None:
            warnings.warn(
                f"Ignoring non-standard Transfermarkt squad export: {path.name}",
                stacklevel=2,
            )
            continue
        try:
            timestamp = datetime.strptime(match.group("timestamp"), "%Y%m%d_%H%M%S")
        except ValueError as exc:
            warnings.warn(f"Ignoring {path.name}: invalid timestamp ({exc})", stacklevel=2)
            continue
        candidates.append(InputFile(path, match.group("timestamp"), timestamp))
    if not candidates:
        raise FileNotFoundError(
            f"No valid standard Transfermarkt squad CSV found in {TRANSFERMARKT_SQUADS_DIR}."
        )
    latest = max(item.timestamp for item in candidates)
    newest = [item for item in candidates if item.timestamp == latest]
    if len(newest) != 1:
        raise RuntimeError("Multiple Transfermarkt squad CSVs share the latest timestamp.")
    return newest[0]


def _load_kbstats_players(path: Path) -> pd.DataFrame:
    players = _read_csv(path, "KBStats player CSV")
    missing = {"id", "name"} - set(players.columns)
    if missing:
        raise ValueError(f"KBStats player CSV is missing required columns: {sorted(missing)}")
    if SCORE_COLUMN in players.columns:
        raise ValueError("KBStats player CSV already contains 'score'; refusing to overwrite it.")
    names = players["name"].map(normalize_name)
    if names.eq("").any():
        raise ValueError("KBStats player CSV contains a missing player name.")
    if players["id"].duplicated().any():
        raise ValueError("KBStats player CSV contains duplicate player IDs.")
    return players


def _load_transfermarkt_players(path: Path) -> pd.DataFrame:
    required = {"player_id", "player_name", "market_value_eur"}
    players = _read_csv(path, "Transfermarkt squad CSV")
    missing = sorted(required - set(players.columns))
    if missing:
        raise ValueError(f"Transfermarkt squad CSV is missing required columns: {missing}")
    players = players.copy()
    players["player_id"] = pd.to_numeric(players["player_id"], errors="coerce")
    if players["player_id"].isna().any() or players["player_id"].le(0).any():
        raise ValueError("Transfermarkt squad CSV contains an invalid player_id.")
    players["player_id"] = players["player_id"].astype(int)
    players["_normalized_name"] = players["player_name"].map(normalize_name)
    if players["_normalized_name"].eq("").any():
        raise ValueError("Transfermarkt squad CSV contains a missing player_name.")
    if players["player_id"].duplicated().any():
        raise ValueError("Transfermarkt squad CSV contains duplicate player IDs.")
    if players["_normalized_name"].duplicated().any():
        duplicates = players.loc[
            players["_normalized_name"].duplicated(keep=False), "player_name"
        ].tolist()
        raise ValueError(f"Transfermarkt squad CSV contains ambiguous player names: {duplicates}")

    raw_values = players["market_value_eur"]
    missing_values = raw_values.isna() | raw_values.astype(str).str.strip().eq("")
    numeric_values = pd.to_numeric(raw_values, errors="coerce")
    invalid_values = (~missing_values) & (
        numeric_values.isna()
        | ~numeric_values.map(lambda value: math.isfinite(value) if pd.notna(value) else False)
        | numeric_values.lt(0)
    )
    if invalid_values.any():
        rows = ", ".join(str(index + 2) for index in players.index[invalid_values][:10])
        raise ValueError(f"Transfermarkt market values are invalid at source row(s): {rows}")
    players["_market_value"] = numeric_values.where(~missing_values, other=pd.NA)
    return players


def _load_overrides(path: Path = OVERRIDE_PATH) -> pd.DataFrame:
    references = load_references(path)
    provider_rows = references.loc[references["provider"].eq("transfermarkt")].copy()
    if provider_rows["canonical_team"].ne("").any():
        raise ValueError("Transfermarkt cross references must not specify canonical_team.")
    overrides = provider_rows.rename(
        columns={
            "provider_player_id": "transfermarkt_player_id",
            "provider_player_name": "transfermarkt_player_name",
        }
    ).loc[:, list(OVERRIDE_COLUMNS)]
    if overrides.empty:
        return overrides
    overrides = overrides.copy()
    overrides["_normalized_name"] = overrides["kbstats_name"].map(normalize_name)
    overrides["transfermarkt_player_id"] = pd.to_numeric(
        overrides["transfermarkt_player_id"], errors="coerce"
    )
    if (
        overrides["_normalized_name"].eq("").any()
        or overrides["transfermarkt_player_id"].isna().any()
        or overrides["transfermarkt_player_id"].le(0).any()
    ):
        raise ValueError("Overrides contain an empty KBStats name or invalid Transfermarkt player ID.")
    overrides["transfermarkt_player_id"] = overrides["transfermarkt_player_id"].astype(int)
    if (
        overrides["_normalized_name"].duplicated().any()
        or overrides["transfermarkt_player_id"].duplicated().any()
    ):
        raise ValueError("Overrides contain duplicate KBStats names or Transfermarkt player IDs.")
    return overrides


def _candidate_rows(
    player_name: str, transfermarkt_players: pd.DataFrame
) -> list[tuple[float, pd.Series]]:
    normalized_name = normalize_name(player_name)
    candidates = [
        (
            SequenceMatcher(None, normalized_name, row["_normalized_name"]).ratio(),
            row,
        )
        for _, row in transfermarkt_players.loc[
            transfermarkt_players["_market_value"].notna()
        ].iterrows()
    ]
    return sorted(
        (item for item in candidates if item[0] >= FUZZY_MATCH_THRESHOLD),
        key=lambda item: (
            -item[0],
            str(item[1]["player_name"]).casefold(),
            int(item[1]["player_id"]),
        ),
    )[:MAX_PROMPT_CANDIDATES]


def _prompt_for_candidate(
    kbstats_name: str, candidates: list[tuple[float, pd.Series]]
) -> tuple[pd.Series | None, float | None]:
    print(f"\nNo exact Transfermarkt match for KBStats player: {kbstats_name}")
    for number, (similarity, candidate) in enumerate(candidates, start=1):
        print(
            f"  {number}. {candidate['player_name']} "
            f"(Transfermarkt ID {candidate['player_id']}, €{int(candidate['_market_value']):,}, "
            f"similarity {similarity:.0%})"
        )
    while True:
        try:
            answer = input("Choose a candidate number, or press Enter to skip (score 0): ").strip()
        except EOFError as exc:
            raise RuntimeError(
                "Interactive name review requires a Jupyter input prompt. "
                "Run this notebook interactively or add a valid override first."
            ) from exc
        if not answer:
            return None, None
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            selected = candidates[int(answer) - 1]
            return selected[1], selected[0]
        print(f"Enter a number from 1 to {len(candidates)}, or press Enter to skip.")


def _persist_overrides(overrides: pd.DataFrame, path: Path = OVERRIDE_PATH) -> None:
    output = overrides.loc[:, list(OVERRIDE_COLUMNS)].copy().rename(
        columns={
            "transfermarkt_player_id": "provider_player_id",
            "transfermarkt_player_name": "provider_player_name",
        }
    )
    output.insert(0, "provider", "transfermarkt")
    output.insert(1, "canonical_team", "")
    references = load_references(path)
    remaining = references.loc[~references["provider"].eq("transfermarkt")]
    persist_references(
        pd.concat([remaining, output.loc[:, list(REFERENCE_COLUMNS)]], ignore_index=True), path
    )


def _build_scored_players(
    kbstats_players: pd.DataFrame,
    transfermarkt_players: pd.DataFrame,
    overrides: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    by_name = {
        row["_normalized_name"]: row for _, row in transfermarkt_players.iterrows()
    }
    by_id = {
        int(row["player_id"]): row for _, row in transfermarkt_players.iterrows()
    }
    override_by_name = {
        row["_normalized_name"]: row for _, row in overrides.iterrows()
    }
    scores: list[int] = []
    reviews: list[dict[str, Any]] = []
    additions: list[dict[str, Any]] = []

    for _, player in kbstats_players.iterrows():
        name = str(player["name"]).strip()
        normalized_name = normalize_name(name)
        selected: pd.Series | None = by_name.get(normalized_name)
        status = "exact_normalized" if selected is not None else "zero_unmatched"
        similarity: float | None = None
        if selected is None and normalized_name in override_by_name:
            selected = by_id.get(
                int(override_by_name[normalized_name]["transfermarkt_player_id"])
            )
            status = "persisted_override" if selected is not None else "zero_missing_override"
            if selected is None:
                warnings.warn(
                    f"Override for {name!r} is absent from the current Transfermarkt export; score is 0.",
                    stacklevel=2,
                )
        elif selected is None:
            candidates = _candidate_rows(name, transfermarkt_players)
            if candidates:
                selected, similarity = _prompt_for_candidate(name, candidates)
                if selected is None:
                    status = "zero_skipped_candidate"
                else:
                    status = "prompted_override"
                    additions.append(
                        {
                            "kbstats_name": name,
                            "transfermarkt_player_id": int(selected["player_id"]),
                            "transfermarkt_player_name": str(selected["player_name"]),
                            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                        }
                    )

        value = None if selected is None else selected["_market_value"]
        if value is None or pd.isna(value):
            score = 0
            if selected is not None:
                status = "zero_missing_market_value"
        else:
            score = int(value)
        scores.append(score)
        reviews.append(
            {
                "kbstats_name": name,
                "status": status,
                "transfermarkt_player_name": None if selected is None else selected["player_name"],
                "transfermarkt_player_id": None if selected is None else int(selected["player_id"]),
                "score": score,
                "similarity": None if similarity is None else round(similarity, 3),
            }
        )

    scored = kbstats_players.copy()
    scored[SCORE_COLUMN] = scores
    return scored, pd.DataFrame(reviews), pd.DataFrame(additions, columns=OVERRIDE_COLUMNS)


def _validate_scored_players(source: pd.DataFrame, scored: pd.DataFrame) -> None:
    if len(scored) != len(source):
        raise RuntimeError("Scored output does not retain every KBStats player row.")
    if list(scored.columns) != [*source.columns, SCORE_COLUMN]:
        raise RuntimeError("Scored output changed the original KBStats columns or their order.")
    scores = pd.to_numeric(scored[SCORE_COLUMN], errors="coerce")
    if scores.isna().any() or not scores.map(math.isfinite).all():
        raise RuntimeError("Scored output contains a missing, invalid, or non-finite score.")


def _save_scored_players(scored: pd.DataFrame, kbstats_timestamp: str) -> Path:
    created_timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%z")
    output_path = ensure_directory(EXPECTED_POINTS_DIR) / (
        f"expected_points_{kbstats_timestamp}_transfermarkt_market_value_"
        f"{created_timestamp}.csv"
    )
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing score CSV: {output_path}")
    try:
        scored.to_csv(output_path, index=False, encoding="utf-8-sig")
    except OSError as exc:
        raise OSError(f"Could not write score CSV {output_path}: {exc}") from exc
    return output_path


def run_score_creation() -> dict[str, Any]:
    """Run the complete Transfermarkt market-value score workflow."""
    kbstats_input = _select_latest_kbstats_csv()
    transfermarkt_input = _select_latest_transfermarkt_csv()
    kbstats_players = _load_kbstats_players(kbstats_input.path)
    transfermarkt_players = _load_transfermarkt_players(transfermarkt_input.path)
    overrides = _load_overrides()
    scored, review, additions = _build_scored_players(
        kbstats_players, transfermarkt_players, overrides
    )
    _validate_scored_players(kbstats_players, scored)

    if not additions.empty:
        combined = pd.concat(
            [overrides.loc[:, list(OVERRIDE_COLUMNS)], additions], ignore_index=True
        )
        _persist_overrides(combined)

    status_counts = review["status"].value_counts().to_dict()
    zero_count = sum(count for status, count in status_counts.items() if status.startswith("zero_"))
    print("Input files")
    print(f"  KBStats: {kbstats_input.path}")
    print(f"  Transfermarkt: {transfermarkt_input.path}")
    print("\nMatching summary")
    print(f"  Exact normalized matches: {status_counts.get('exact_normalized', 0)}")
    print(f"  Persisted-override matches: {status_counts.get('persisted_override', 0)}")
    print(f"  Prompted matches: {status_counts.get('prompted_override', 0)}")
    print(f"  Zero-score players: {zero_count}")
    review_rows = review.loc[review["status"].ne("exact_normalized")].copy()
    print("\nName and market-value review (non-exact or zero-score rows)")
    display(review_rows if not review_rows.empty else pd.DataFrame({"status": ["No review rows"]}))

    output_path = _save_scored_players(scored, kbstats_input.timestamp_text)
    print(f"\nOutput: {output_path}")
    if not additions.empty:
        print(f"Saved {len(additions)} confirmed name override(s): {OVERRIDE_PATH}")
    return {
        "output_path": output_path,
        "scored_players": scored,
        "review": review,
        "kbstats_input": kbstats_input.path,
        "transfermarkt_input": transfermarkt_input.path,
    }
