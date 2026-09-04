from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from sofascore_score_reflection import (
    BASELINE_COLUMNS,
    baseline_from_snapshot,
    build_outcomes,
    feature_frame,
    normalize_to_actual_range,
)


def _players(*, games: int, starts: int, points: int, history: str, playtime_seconds: int = 0) -> pd.DataFrame:
    return pd.DataFrame({
        "id": [1], "gamesPlayed": [games], "start11": [starts], "totalPoints": [points],
        "totalPlaytimeS": [playtime_seconds], "history": [history],
    })


def test_outcomes_use_cumulative_baseline_for_played_started_and_points(tmp_path):
    before = _players(games=4, starts=3, points=500, playtime_seconds=18_000, history='[]')
    baseline = baseline_from_snapshot(before, datetime.now(timezone.utc), tmp_path / "before.csv")
    current = _players(
        games=5, starts=4, points=625, playtime_seconds=23_400,
        history='[{"hasPlayed": true, "points": 125}]',
    )

    outcome = build_outcomes(current, baseline).iloc[0]

    assert list(baseline.columns) == list(BASELINE_COLUMNS)
    assert outcome["actual_points"] == 125
    assert bool(outcome["played"]) is True
    assert bool(outcome["started"]) is True
    assert outcome["minutes_played"] == 90
    assert outcome["outcome_status"] == "baseline"


def test_first_run_uses_history_and_zeroes_nonappearance():
    current = _players(games=0, starts=0, points=0, history='[{"hasPlayed": false, "points": null}]')

    outcome = build_outcomes(current, pd.DataFrame(columns=BASELINE_COLUMNS)).iloc[0]

    assert outcome["actual_points"] == 0
    assert bool(outcome["played"]) is False
    assert bool(outcome["started"]) is False


def test_prediction_normalization_starts_at_zero_even_with_negative_actual_points():
    normalized = normalize_to_actual_range([1.0, 3.0, 5.0], [-10.0, 0.0, 20.0])

    assert normalized.tolist() == [0.0, 10.0, 20.0]


def test_feature_frame_prefers_saved_provider_chances_from_expected_points_csv():
    expected = pd.DataFrame({
        "id": [173], "teamId": [2], "name": ["Jonathan Tah"], "position": [2],
        "sofascore_average_rating": [6.94], "expected_match_points": [2.5],
        "starting_chance": [1.0], "questionable_injury_penalty": [0.0], "score": [17.36],
        "ligainsider_starting_chance": [1.0], "kickbase_starting_chance": [1.0],
        "kicker_starting_chance": [1.0], "rotowire_starting_chance": [1.0],
    })
    players = expected[["id", "teamId", "name"]].copy()
    unmatched_sources = {key: {} for key in ("ligainsider", "kickbase", "kicker", "rotowire")}

    result = feature_frame(expected, players, unmatched_sources).iloc[0]

    assert result["kickbase_chance"] == 1.0
    assert result["kicker_chance"] == 1.0
