"""Create optimizer-ready scores from KBStats point averages, odds, and lineups."""

from __future__ import annotations

import json
import math
import re
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
from IPython.display import display

from project_paths import (
    DERIVED_KBSTATS_MATCHDAY_QUALIFIED_AVERAGE_PLAYERS_DIR,
    DERIVED_KBSTATS_MATCHDAY_QUALIFIED_LAST_5_AVERAGE_PLAYERS_DIR,
    EXPECTED_POINTS_DIR,
    KBSTATS_PLAYERS_DIR,
    ensure_directory,
    prune_timestamped_outputs,
)
from sofascore_average_rating_score import load_kbstats_players, normalize_name, validate_scored_players
from sofascore_rating_odds_lineup_score import (
    DEFAULT_QUESTIONABLE_INJURY_STARTING_CHANCE_PENALTY,
    DEFAULT_ALTERNATIVE_STARTING_CHANCE_DECAY,
    KB_TEAM_ID_TO_KEY,
    LINEUP_OVERRIDE_COLUMNS,
    LINEUP_SOURCES,
    KICKBASE_REFERENCE_COLUMNS,
    _fuzzy_candidates,
    _load_kickbase_lineup_overrides,
    _load_lineup_overrides,
    _persist_kickbase_lineup_overrides,
    _persist_lineup_overrides,
    _prompt_candidate,
    build_kickbase_name_indexes,
    blend_lineup_chances,
    load_expected_match_points,
    load_lineup_source,
    request_matchday,
    resolve_kickbase_display_name,
    resolve_lineup_source_weights,
    validate_alternative_starting_chance_decay,
)


@dataclass(frozen=True)
class MetricConfig:
    """Configuration for one KBStats-derived metric source."""

    key: str
    directory: Path
    filename_pattern: re.Pattern[str]
    metric_field: str
    output_column: str
    output_label: str


METRIC_CONFIGS = {
    "season_average": MetricConfig(
        key="season_average",
        directory=DERIVED_KBSTATS_MATCHDAY_QUALIFIED_AVERAGE_PLAYERS_DIR,
        filename_pattern=re.compile(
            r"^kbstats_matchday_qualified_average_players_"
            r"(?P<timestamp>\d{8}_\d{6}_[+-]\d{4})\.json$"
        ),
        metric_field="averagePoints",
        output_column="kbstats_average_points",
        output_label="season_average",
    ),
    "last5_average": MetricConfig(
        key="last5_average",
        directory=DERIVED_KBSTATS_MATCHDAY_QUALIFIED_LAST_5_AVERAGE_PLAYERS_DIR,
        filename_pattern=re.compile(
            r"^kbstats_matchday_qualified_last_5_average_players_"
            r"(?P<timestamp>\d{8}_\d{6}_[+-]\d{4})\.json$"
        ),
        metric_field="last5AveragePoints",
        output_column="kbstats_last5_average_points",
        output_label="last_5_average",
    ),
}

KBSTATS_SOURCE_FILENAME_RE = re.compile(
    r"^kbstats_players_(?P<timestamp>\d{8}_\d{6}_[+-]\d{4})\.json$"
)
COMMON_OUTPUT_COLUMNS = (
    "expected_match_points",
    "ligainsider_starting_chance",
    "kickbase_starting_chance",
    "rotowire_starting_chance",
    "questionable_injury_penalty",
    "starting_chance",
)


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _normalize_player_id(value: Any) -> str:
    if isinstance(value, bool):
        raise ValueError("player ID cannot be boolean")
    if isinstance(value, str):
        text = value.strip()
        if not text or not text.isdigit() or int(text) < 1:
            raise ValueError(f"invalid player ID {value!r}")
        return str(int(text))
    if _is_finite_number(value) and float(value).is_integer() and float(value) >= 1:
        return str(int(value))
    raise ValueError(f"invalid player ID {value!r}")


def _parse_derived_timestamp(path: Path, config: MetricConfig) -> datetime:
    match = config.filename_pattern.fullmatch(path.name)
    if match is None:
        raise ValueError(f"unsupported {config.output_label} filename: {path.name}")
    try:
        return datetime.strptime(match.group("timestamp"), "%Y%m%d_%H%M%S_%z").astimezone(
            timezone.utc
        )
    except ValueError as exc:
        raise ValueError(f"invalid timestamp in {path.name}: {exc}") from exc


def select_latest_metric_file(config: MetricConfig) -> Path:
    if not config.directory.is_dir():
        raise FileNotFoundError(
            f"Derived {config.output_label} directory does not exist: {config.directory}. "
            "Run its analysis notebook first."
        )
    candidates: list[tuple[datetime, Path]] = []
    for path in sorted(config.directory.glob("*.json")):
        try:
            candidates.append((_parse_derived_timestamp(path, config), path))
        except ValueError as exc:
            warnings.warn(f"Ignoring {path.name}: {exc}", stacklevel=2)
    if not candidates:
        raise FileNotFoundError(
            f"No valid derived {config.output_label} JSON files were found in {config.directory}."
        )
    newest_timestamp = max(timestamp for timestamp, _ in candidates)
    newest_paths = [path for timestamp, path in candidates if timestamp == newest_timestamp]
    if len(newest_paths) != 1:
        raise RuntimeError("Multiple derived metric files share the newest timestamp.")
    return newest_paths[0]


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load {label} {path}: {exc}") from exc


def load_metric_document(path: Path, config: MetricConfig) -> tuple[pd.DataFrame, int, Path, str]:
    """Load the qualified metric rows and their exact KBStats CSV source."""
    document = _load_json(path, f"derived {config.output_label} input")
    if not isinstance(document, dict):
        raise ValueError("Derived metric JSON must be an object.")
    eligibility = document.get("eligibility")
    source_file = document.get("source_file")
    raw_players = document.get("players")
    if not isinstance(eligibility, dict) or not isinstance(raw_players, list):
        raise ValueError("Derived metric JSON has no valid eligibility or players fields.")
    matchday = eligibility.get("bundesliga_matchday")
    if not isinstance(matchday, int) or isinstance(matchday, bool) or not 1 <= matchday <= 34:
        raise ValueError("Derived metric JSON has an invalid Bundesliga matchday.")
    if not isinstance(source_file, str) or KBSTATS_SOURCE_FILENAME_RE.fullmatch(source_file) is None:
        raise ValueError("Derived metric JSON has an unsupported KBStats source_file.")
    source_csv_path = KBSTATS_PLAYERS_DIR / Path(source_file).with_suffix(".csv").name
    if not source_csv_path.is_file():
        raise FileNotFoundError(
            f"The KBStats CSV paired with {path.name} is missing: {source_csv_path}."
        )

    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for source_index, player in enumerate(raw_players):
        if not isinstance(player, dict):
            raise ValueError(f"Derived metric player {source_index} is not an object.")
        try:
            player_id = _normalize_player_id(player.get("id"))
        except ValueError as exc:
            raise ValueError(f"Derived metric player {source_index}: {exc}") from exc
        if player_id in seen_ids:
            raise ValueError(f"Derived metric JSON contains duplicate player ID {player_id}.")
        seen_ids.add(player_id)
        metric = player.get(config.metric_field)
        # Kickbase match points, and therefore derived averages, may be negative.
        # Preserve every finite metric value so a negative form value can produce
        # the corresponding negative optimizer score.
        if metric is not None and not _is_finite_number(metric):
            raise ValueError(
                f"Derived metric player {player_id} has invalid {config.metric_field}."
            )
        rows.append({"_player_id": player_id, "_metric": None if metric is None else float(metric)})
    return pd.DataFrame(rows, columns=["_player_id", "_metric"]), matchday, source_csv_path, source_file


def _resolve_lineups(
    players: pd.DataFrame,
    team_keys: pd.Series,
    eligible_ids: set[str],
    lineup_inputs: dict[str, tuple[Path, dict[str, dict[str, dict[str, Any]]]]],
) -> tuple[
    dict[tuple[int, str], tuple[dict[str, Any] | None, str]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Resolve only players with a usable metric against lineup providers."""
    overrides = _load_lineup_overrides()
    kickbase_overrides = _load_kickbase_lineup_overrides()
    override_by_key = {row["_key"]: row for _, row in overrides.iterrows()}
    kickbase_override_by_key = {row["_key"]: row for _, row in kickbase_overrides.iterrows()}
    resolution: dict[tuple[int, str], tuple[dict[str, Any] | None, str]] = {}
    prompts: list[tuple[float, str, int, Any, list[tuple[float, dict[str, Any]]]]] = []
    contexts: dict[int, dict[str, Any]] = {}

    for index, player in players.iterrows():
        player_id = _normalize_player_id(player["id"])
        if player_id not in eligible_ids:
            continue
        name = str(player["name"]).strip()
        contexts[int(index)] = {
            "name": name,
            "normalized": normalize_name(name),
            "team_key": str(team_keys.loc[index]),
            "first_name": player.get("firstName"),
            "last_name": player.get("lastName"),
        }
    kickbase_name_indexes = build_kickbase_name_indexes(players, team_keys)

    for index, context in contexts.items():
        name, normalized, team_key = context["name"], context["normalized"], context["team_key"]
        for source in LINEUP_SOURCES:
            _, source_teams = lineup_inputs[source.key]
            candidates = source_teams.get(team_key)
            if candidates is None:
                continue
            chosen = candidates.get(normalized)
            if chosen is not None:
                resolution[(index, source.key)] = (chosen, "exact")
                continue
            if source.key == "kickbase":
                override = kickbase_override_by_key.get((team_key, normalized))
                if override is not None:
                    chosen = candidates.get(normalize_name(override["kickbase_displayed_name"]))
                    resolution[(index, source.key)] = (
                        chosen,
                        "override" if chosen is not None else "missing",
                    )
                    continue
                chosen = resolve_kickbase_display_name(
                    candidates,
                    {"firstName": context["first_name"], "lastName": context["last_name"]},
                    kickbase_name_indexes.get(team_key, {"first": {}, "last": {}}),
                )
                if chosen is not None:
                    resolution[(index, source.key)] = (chosen, "exact")
                    continue
                fuzzy = _fuzzy_candidates(name, candidates)
                if fuzzy:
                    prompts.append((fuzzy[0][0], name.casefold(), index, source, fuzzy))
                else:
                    resolution[(index, source.key)] = (None, "missing")
                continue
            override_key = (source.key, team_key, normalized)
            if override_key in override_by_key:
                override = override_by_key[override_key]
                chosen = next(
                    (
                        value
                        for value in candidates.values()
                        if value["id"] == int(override["provider_player_id"])
                    ),
                    None,
                )
                resolution[(index, source.key)] = (
                    chosen,
                    "override" if chosen is not None else "missing",
                )
                continue
            fuzzy = _fuzzy_candidates(name, candidates)
            if fuzzy:
                prompts.append((fuzzy[0][0], name.casefold(), index, source, fuzzy))
            else:
                resolution[(index, source.key)] = (None, "missing")

    new_overrides: list[dict[str, Any]] = []
    new_kickbase_overrides: list[dict[str, Any]] = []
    for _, _, index, source, candidates in sorted(
        prompts, key=lambda item: (-item[0], item[1], item[3].key, item[2])
    ):
        context = contexts[index]
        name, normalized, team_key = context["name"], context["normalized"], context["team_key"]
        chosen, _ = _prompt_candidate(f"{source.key} lineup for {name} ({team_key})", candidates)
        if chosen is None:
            resolution[(index, source.key)] = (None, "missing")
            continue
        resolution[(index, source.key)] = (chosen, "prompted")
        if source.key == "kickbase":
            new_kickbase_overrides.append(
                {
                    "canonical_team": team_key,
                    "kbstats_name": name,
                    "kickbase_displayed_name": chosen["name"],
                    "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                }
            )
        else:
            new_overrides.append(
                {
                    "source": source.key,
                    "canonical_team": team_key,
                    "kbstats_name": name,
                    "provider_player_id": chosen["id"],
                    "provider_player_name": chosen["name"],
                    "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                }
            )
    return resolution, new_overrides, new_kickbase_overrides


def run_score_creation(
    metric_key: str,
    questionable_injury_starting_chance_penalty: float = DEFAULT_QUESTIONABLE_INJURY_STARTING_CHANCE_PENALTY,
    alternative_starting_chance_decay: float = DEFAULT_ALTERNATIVE_STARTING_CHANCE_DECAY,
    lineup_source_weights: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Score the latest qualified KBStats metric against odds and lineups."""
    try:
        config = METRIC_CONFIGS[metric_key]
    except KeyError as exc:
        raise ValueError(f"Unsupported metric {metric_key!r}.") from exc
    if not LINEUP_SOURCES or len({source.key for source in LINEUP_SOURCES}) != len(LINEUP_SOURCES):
        raise ValueError("Active lineup sources must have unique keys.")
    alternative_starting_chance_decay = validate_alternative_starting_chance_decay(
        alternative_starting_chance_decay
    )
    source_weights = resolve_lineup_source_weights(lineup_source_weights)
    if (
        not _is_finite_number(questionable_injury_starting_chance_penalty)
        or not 0 <= float(questionable_injury_starting_chance_penalty) <= 1
    ):
        raise ValueError("Questionable-injury starting-chance penalty must be a finite value from 0 to 1.")

    metric_input = select_latest_metric_file(config)
    metrics, analysis_matchday, source_csv_path, source_json_name = load_metric_document(
        metric_input, config
    )
    matchday = request_matchday()
    if matchday != analysis_matchday:
        raise ValueError(
            f"The selected analysis was created for matchday {analysis_matchday}, "
            f"not requested matchday {matchday}."
        )
    players = load_kbstats_players(source_csv_path)
    expected_points, odds_table = load_expected_match_points(matchday)
    lineup_inputs = {
        source.key: load_lineup_source(
            source,
            questionable_injury_starting_chance_penalty,
            alternative_starting_chance_decay,
        )
        for source in LINEUP_SOURCES
    }

    player_teams = pd.to_numeric(players["teamId"], errors="coerce")
    if player_teams.isna().any() or not set(player_teams.astype(int)).issubset(KB_TEAM_ID_TO_KEY):
        raise ValueError("KBStats teamId values cannot be mapped to the current Bundesliga clubs.")
    team_keys = player_teams.astype(int).map(KB_TEAM_ID_TO_KEY)
    if set(team_keys) != set(expected_points):
        raise ValueError("KBStats clubs do not match the requested odds matchday.")

    # Pandas stores the JSON null used for a qualified player with no played
    # last-five slot as NaN. Convert it back to the workflow's explicit
    # no-metric value before deciding whether to resolve lineups or emit a
    # numeric output value.
    metric_by_id = {
        player_id: None if pd.isna(value) else float(value)
        for player_id, value in zip(metrics["_player_id"], metrics["_metric"], strict=True)
    }
    source_ids = [_normalize_player_id(value) for value in players["id"]]
    absent_ids = sorted(set(metric_by_id) - set(source_ids))
    if absent_ids:
        raise ValueError(
            "Derived metric contains player IDs absent from its recorded KBStats CSV: "
            + ", ".join(absent_ids[:10])
        )
    usable_metric_ids = {player_id for player_id, value in metric_by_id.items() if value is not None}
    lineup_resolution, new_lineup_overrides, new_kickbase_lineup_overrides = _resolve_lineups(
        players, team_keys, usable_metric_ids, lineup_inputs
    )

    metric_values: list[float] = []
    match_point_values: list[float] = []
    ligainsider_chances: list[float] = []
    kickbase_chances: list[float] = []
    rotowire_chances: list[float] = []
    injury_penalties: list[float] = []
    starting_chances: list[float] = []
    scores: list[float] = []
    review_rows: list[dict[str, Any]] = []

    for index, player in players.iterrows():
        player_id = _normalize_player_id(player["id"])
        name = str(player["name"]).strip()
        team_key = str(team_keys.loc[index])
        raw_metric = metric_by_id.get(player_id)
        metric_status = "qualified" if raw_metric is not None else (
            "qualified_without_last_five_average" if player_id in metric_by_id else "not_qualified"
        )
        metric_value = 0.0 if raw_metric is None else float(raw_metric)
        source_chance_by_key = {source.key: 0.0 for source in LINEUP_SOURCES}
        lineup_statuses: list[str] = []
        injury_penalty = 0.0

        if raw_metric is None:
            starting_chance = 0.0
            lineup_statuses.append("not_evaluated_missing_metric")
        else:
            source_chances: list[tuple[float, float]] = []
            is_questionable = False
            for source in LINEUP_SOURCES:
                _, source_teams = lineup_inputs[source.key]
                if team_key not in source_teams:
                    continue
                try:
                    chosen, status = lineup_resolution[(int(index), source.key)]
                except KeyError as exc:
                    raise RuntimeError(
                        f"No resolved lineup match exists for {name!r} from {source.key}."
                    ) from exc
                chance = 0.0 if chosen is None else float(chosen["chance"])
                source_weight = source_weights[source.key]
                if source_weight > 0:
                    source_chances.append((source_weight, chance))
                source_chance_by_key[source.key] = chance
                is_questionable = is_questionable or bool(
                    chosen is not None and chosen.get("questionable", False)
                )
                lineup_statuses.append(f"{source.key}:{status}")
            try:
                blended_chance = blend_lineup_chances(source_chances)
            except ValueError as exc:
                raise ValueError(f"No positive-weight lineup source covers team {team_key}.") from exc
            injury_penalty = (
                float(questionable_injury_starting_chance_penalty) if is_questionable else 0.0
            )
            starting_chance = blended_chance

        match_points = float(expected_points[team_key])
        score = round(metric_value * match_points * starting_chance, 6)
        metric_values.append(metric_value)
        match_point_values.append(match_points)
        ligainsider_chances.append(source_chance_by_key["ligainsider"])
        kickbase_chances.append(source_chance_by_key["kickbase"])
        rotowire_chances.append(source_chance_by_key["rotowire"])
        injury_penalties.append(injury_penalty)
        starting_chances.append(starting_chance)
        scores.append(score)
        review_rows.append(
            {
                "name": name,
                "team": team_key,
                "metric_status": metric_status,
                "metric": metric_value,
                "lineup_status": "; ".join(lineup_statuses),
                "expected_match_points": match_points,
                "ligainsider_starting_chance": source_chance_by_key["ligainsider"],
                "kickbase_starting_chance": source_chance_by_key["kickbase"],
                "rotowire_starting_chance": source_chance_by_key["rotowire"],
                "questionable_injury_penalty": injury_penalty,
                "starting_chance": starting_chance,
                "score": score,
            }
        )

    scored = players.copy()
    scored[config.output_column] = metric_values
    scored["expected_match_points"] = match_point_values
    scored["ligainsider_starting_chance"] = ligainsider_chances
    scored["kickbase_starting_chance"] = kickbase_chances
    scored["rotowire_starting_chance"] = rotowire_chances
    scored["questionable_injury_penalty"] = injury_penalties
    scored["starting_chance"] = starting_chances
    scored["score"] = scores
    validate_scored_players(
        players, scored, additional_columns=(config.output_column, *COMMON_OUTPUT_COLUMNS)
    )

    if new_lineup_overrides:
        existing_overrides = _load_lineup_overrides()
        _persist_lineup_overrides(
            pd.concat(
                [
                    existing_overrides.loc[:, list(LINEUP_OVERRIDE_COLUMNS)],
                    pd.DataFrame(new_lineup_overrides),
                ],
                ignore_index=True,
            )
        )
    if new_kickbase_lineup_overrides:
        existing_kickbase_overrides = _load_kickbase_lineup_overrides()
        _persist_kickbase_lineup_overrides(
            pd.concat(
                [
                    existing_kickbase_overrides.loc[:, list(KICKBASE_REFERENCE_COLUMNS)],
                    pd.DataFrame(new_kickbase_lineup_overrides),
                ],
                ignore_index=True,
            )
        )

    created_timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%z")
    source_timestamp = KBSTATS_SOURCE_FILENAME_RE.fullmatch(source_json_name).group("timestamp")
    output_path = ensure_directory(EXPECTED_POINTS_DIR) / (
        f"expected_points_{source_timestamp}_kbstats_{config.output_label}_odds_lineup_"
        f"{created_timestamp}.csv"
    )
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing score CSV: {output_path}")
    scored.to_csv(output_path, index=False, encoding="utf-8-sig")
    prune_timestamped_outputs()

    review = pd.DataFrame(review_rows)
    print("Input summary")
    print(f"  Matchday: {matchday}; derived metric: {metric_input.name}")
    print(f"  KBStats source CSV: {source_csv_path.name}")
    for source in LINEUP_SOURCES:
        print(f"  {source.key.title()} (weight {source_weights[source.key]:g}): {lineup_inputs[source.key][0].name}")
    print(f"  Alternative starting-chance decay: {alternative_starting_chance_decay:.2f}")
    print(f"  Questionable-injury starting-chance penalty: {questionable_injury_starting_chance_penalty:.2f}")
    print(f"  Output: {output_path}")
    print("\nTeam odds and expected match points")
    display(odds_table)
    print("\nPlayer score review (not qualified, missing metric, or non-positive score)")
    display(review.loc[(review["score"].le(0)) | (review["metric_status"].ne("qualified"))])
    return {
        "output_path": output_path,
        "scored_players": scored,
        "odds": odds_table,
        "review": review,
        "metric_input": metric_input,
        "kbstats_input": source_csv_path,
    }
