"""Derived Transfermarkt team percentiles and optimizer-ready score creation."""

from __future__ import annotations

import math
import re
import warnings
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd
from IPython.display import display

from project_paths import (
    DERIVED_TRANSFERMARKT_TEAM_MARKET_VALUE_PERCENTILES_DIR,
    EXPECTED_POINTS_DIR,
    ensure_directory,
    prune_timestamped_outputs,
)
from transfermarkt_market_value_score import (
    FUZZY_MATCH_THRESHOLD,
    MAX_PROMPT_CANDIDATES,
    OVERRIDE_COLUMNS,
    OVERRIDE_PATH,
    _load_kbstats_players,
    _load_overrides,
    _load_transfermarkt_players,
    _persist_overrides,
    _select_latest_kbstats_csv,
    _select_latest_transfermarkt_csv,
    _validate_scored_players,
    normalize_name,
)


PERCENTILE_COLUMN = "market_value_percentile_within_team"
DERIVED_FILENAME_RE = re.compile(
    r"^transfermarkt_team_market_value_percentiles_"
    r"(?P<source>\d{8}_\d{6})_(?P<created>\d{8}_\d{6}_[+-]\d{4})\.csv$"
)


def derive_team_market_value_percentiles() -> dict[str, Any]:
    """Create the complete Transfermarkt within-team percentile CSV."""
    source = _select_latest_transfermarkt_csv()
    players = _load_transfermarkt_players(source.path)
    if "team" not in players.columns:
        raise ValueError("Transfermarkt squad CSV is missing required column: 'team'.")
    if players["team"].isna().any() or players["team"].astype(str).str.strip().eq("").any():
        raise ValueError("Transfermarkt squad CSV contains a missing team value.")

    original_columns = [column for column in players.columns if not column.startswith("_")]
    derived = players.loc[:, original_columns].copy()
    percentiles = (
        players.groupby("team", sort=False)["_market_value"]
        .rank(method="average", pct=True)
        .mul(100)
        .round(2)
    )
    derived[PERCENTILE_COLUMN] = percentiles
    if len(derived) != len(players):
        raise RuntimeError("Derived percentile output did not retain every Transfermarkt player row.")

    created = datetime.now().astimezone()
    created_timestamp = created.strftime("%Y%m%d_%H%M%S_%z")
    output_path = ensure_directory(DERIVED_TRANSFERMARKT_TEAM_MARKET_VALUE_PERCENTILES_DIR) / (
        f"transfermarkt_team_market_value_percentiles_{source.timestamp_text}_"
        f"{created_timestamp}.csv"
    )
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing derived CSV: {output_path}")
    try:
        derived.to_csv(output_path, index=False, encoding="utf-8-sig")
    except OSError as exc:
        raise OSError(f"Could not write derived percentile CSV {output_path}: {exc}") from exc
    prune_timestamped_outputs()

    populated = derived[PERCENTILE_COLUMN].notna().sum()
    print("Input")
    print(f"  Transfermarkt: {source.path}")
    print("\nDerived percentile summary")
    print(f"  Player rows retained: {len(derived):,}")
    print(f"  Players with a percentile: {populated:,}")
    print(f"  Players without a market value: {len(derived) - populated:,}")
    print(f"\nOutput: {output_path}")
    display(derived.head())
    return {"output_path": output_path, "derived_players": derived, "source_path": source.path}


def _select_latest_derived_csv() -> Path:
    directory = DERIVED_TRANSFERMARKT_TEAM_MARKET_VALUE_PERCENTILES_DIR
    if not directory.is_dir():
        raise FileNotFoundError(
            f"Derived Transfermarkt percentile directory does not exist: {directory}. "
            "Run the derived-analysis notebook first."
        )
    candidates: list[tuple[datetime, Path]] = []
    for path in sorted(directory.glob("transfermarkt_team_market_value_percentiles_*.csv")):
        match = DERIVED_FILENAME_RE.fullmatch(path.name)
        if match is None:
            warnings.warn(f"Ignoring unsupported derived percentile filename: {path.name}", stacklevel=2)
            continue
        try:
            created = datetime.strptime(match.group("created"), "%Y%m%d_%H%M%S_%z").astimezone(timezone.utc)
        except ValueError as exc:
            warnings.warn(f"Ignoring {path.name}: invalid creation timestamp ({exc})", stacklevel=2)
            continue
        candidates.append((created, path))
    if not candidates:
        raise FileNotFoundError(
            f"No valid derived Transfermarkt percentile CSV found in {directory}."
        )
    latest = max(created for created, _ in candidates)
    newest = [path for created, path in candidates if created == latest]
    if len(newest) != 1:
        raise RuntimeError("Multiple derived percentile CSVs share the latest creation timestamp.")
    return newest[0]


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


def _load_derived_percentiles(path: Path) -> pd.DataFrame:
    required = {"player_id", "player_name", PERCENTILE_COLUMN}
    players = _read_csv(path, "derived Transfermarkt percentile CSV")
    missing = sorted(required - set(players.columns))
    if missing:
        raise ValueError(f"Derived percentile CSV is missing required columns: {missing}")
    players = players.copy()
    players["player_id"] = pd.to_numeric(players["player_id"], errors="coerce")
    if players["player_id"].isna().any() or players["player_id"].le(0).any():
        raise ValueError("Derived percentile CSV contains an invalid player_id.")
    players["player_id"] = players["player_id"].astype(int)
    players["_normalized_name"] = players["player_name"].map(normalize_name)
    if players["_normalized_name"].eq("").any():
        raise ValueError("Derived percentile CSV contains a missing player_name.")
    if players["player_id"].duplicated().any() or players["_normalized_name"].duplicated().any():
        raise ValueError("Derived percentile CSV contains duplicate player IDs or ambiguous player names.")

    raw_percentiles = players[PERCENTILE_COLUMN]
    missing_percentiles = raw_percentiles.isna() | raw_percentiles.astype(str).str.strip().eq("")
    numeric_percentiles = pd.to_numeric(raw_percentiles, errors="coerce")
    invalid = (~missing_percentiles) & (
        numeric_percentiles.isna()
        | ~numeric_percentiles.map(lambda value: math.isfinite(value) if pd.notna(value) else False)
        | numeric_percentiles.lt(0)
        | numeric_percentiles.gt(100)
    )
    if invalid.any():
        rows = ", ".join(str(index + 2) for index in players.index[invalid][:10])
        raise ValueError(f"Derived percentiles are invalid at source row(s): {rows}")
    players["_percentile"] = numeric_percentiles.where(~missing_percentiles, other=pd.NA)
    return players


def _candidate_rows(name: str, players: pd.DataFrame) -> list[tuple[float, pd.Series]]:
    normalized_name = normalize_name(name)
    candidates = [
        (SequenceMatcher(None, normalized_name, row["_normalized_name"]).ratio(), row)
        for _, row in players.loc[players["_percentile"].notna()].iterrows()
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
            f"(Transfermarkt ID {candidate['player_id']}, percentile "
            f"{float(candidate['_percentile']):.2f}, similarity {similarity:.0%})"
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
            chosen = candidates[int(answer) - 1]
            return chosen[1], chosen[0]
        print(f"Enter a number from 1 to {len(candidates)}, or press Enter to skip.")


def _build_scored_players(
    kbstats_players: pd.DataFrame,
    percentile_players: pd.DataFrame,
    overrides: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    by_name = {row["_normalized_name"]: row for _, row in percentile_players.iterrows()}
    by_id = {int(row["player_id"]): row for _, row in percentile_players.iterrows()}
    overrides_by_name = {row["_normalized_name"]: row for _, row in overrides.iterrows()}
    scores: list[float] = []
    reviews: list[dict[str, Any]] = []
    additions: list[dict[str, Any]] = []

    for _, player in kbstats_players.iterrows():
        name = str(player["name"]).strip()
        normalized_name = normalize_name(name)
        selected: pd.Series | None = by_name.get(normalized_name)
        status = "exact_normalized" if selected is not None else "zero_unmatched"
        similarity: float | None = None
        if selected is None and normalized_name in overrides_by_name:
            selected = by_id.get(int(overrides_by_name[normalized_name]["transfermarkt_player_id"]))
            status = "persisted_override" if selected is not None else "zero_missing_override"
            if selected is None:
                warnings.warn(
                    f"Override for {name!r} is absent from the derived percentile input; score is 0.",
                    stacklevel=2,
                )
        elif selected is None:
            candidates = _candidate_rows(name, percentile_players)
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

        percentile = None if selected is None else selected["_percentile"]
        if percentile is None or pd.isna(percentile):
            score = 0.0
            if selected is not None:
                status = "zero_missing_percentile"
        else:
            score = float(percentile)
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
    scored["score"] = scores
    return scored, pd.DataFrame(reviews), pd.DataFrame(additions, columns=OVERRIDE_COLUMNS)


def run_percentile_score_creation() -> dict[str, Any]:
    """Create an optimizer-ready score CSV from the latest derived percentiles."""
    kbstats_input = _select_latest_kbstats_csv()
    percentile_input = _select_latest_derived_csv()
    kbstats_players = _load_kbstats_players(kbstats_input.path)
    percentile_players = _load_derived_percentiles(percentile_input)
    overrides = _load_overrides()
    scored, review, additions = _build_scored_players(
        kbstats_players, percentile_players, overrides
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
    print(f"  Derived Transfermarkt percentiles: {percentile_input}")
    print("\nMatching summary")
    print(f"  Exact normalized matches: {status_counts.get('exact_normalized', 0)}")
    print(f"  Persisted-override matches: {status_counts.get('persisted_override', 0)}")
    print(f"  Prompted matches: {status_counts.get('prompted_override', 0)}")
    print(f"  Zero-score players: {zero_count}")
    review_rows = review.loc[review["status"].ne("exact_normalized")].copy()
    print("\nName and percentile review (non-exact or zero-score rows)")
    display(review_rows if not review_rows.empty else pd.DataFrame({"status": ["No review rows"]}))

    created_timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%z")
    output_path = ensure_directory(EXPECTED_POINTS_DIR) / (
        f"expected_points_{kbstats_input.timestamp_text}_"
        f"transfermarkt_team_market_value_percentile_{created_timestamp}.csv"
    )
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing score CSV: {output_path}")
    try:
        scored.to_csv(output_path, index=False, encoding="utf-8-sig")
    except OSError as exc:
        raise OSError(f"Could not write score CSV {output_path}: {exc}") from exc
    prune_timestamped_outputs()
    print(f"\nOutput: {output_path}")
    if not additions.empty:
        print(f"Saved {len(additions)} confirmed name override(s): {OVERRIDE_PATH}")
    return {
        "output_path": output_path,
        "scored_players": scored,
        "review": review,
        "kbstats_input": kbstats_input.path,
        "percentile_input": percentile_input,
    }
