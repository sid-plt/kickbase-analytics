import json
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

import sofascore_kickbase_points as derived
import sofascore_kickbase_points_per_minute_odds_lineup_score as ppm
import sofascore_rating_odds_lineup_score as shared


def record(match_id, points, minutes):
    return {"match_id": match_id, "calculated_kickbase_points": points, "minutes_played": minutes}


def test_weighted_ratio_preserves_missing_slots_and_negative_points():
    value, status = ppm.weighted_points_per_90(
        [record(1, 90, 90), record(3, -30, 30), record(4, 999, 0)],
        {1: 28, 2: 24, 3: 20, 4: 16, 5: 12},
    )
    assert value == pytest.approx(90 * (28 * 90 - 20 * 30) / (28 * 90 + 20 * 30))
    assert status == "usable"
    assert ppm.weighted_points_per_90([record(1, -90, 90)], {1: 28})[0] == -90
    assert ppm.weighted_points_per_90([record(1, 10, 0)], {1: 28}) == (0, "no_matches_with_at_least_10_minutes")


def test_ten_minute_minimum_excludes_short_cameos_without_shifting_weights():
    value, _ = ppm.weighted_points_per_90(
        [record(1, 999, 9), record(2, 20, 10), record(3, 30, 30)], {1: 28, 2: 24, 3: 20})
    assert value == pytest.approx(90 * (24 * 20 + 20 * 30) / (24 * 10 + 20 * 30))
    assert ppm.weighted_points_per_90([record(1, 999, 9)], {1: 28}) == (
        0, "no_matches_with_at_least_10_minutes")


@pytest.mark.parametrize("records, message", [
    ([{"match_id": 1, "calculated_kickbase_points": 10}], "Rerun"),
    ([record(1, 1, -1)], "finite"),
    ([record(1, float("nan"), 90)], "finite"),
    ([record(1, 1, 90), record(1, 1, 90)], "duplicate"),
    ([record(9, 1, 90)], "unknown"),
])
def test_invalid_history_is_rejected(records, message):
    with pytest.raises(ValueError, match=message):
        ppm.weighted_points_per_90(records, {1: 28})


def test_loader_uses_referenced_team_chronology(tmp_path):
    snapshot = {"2026-09-15": {"10": {"overall_matches": [
        {"match_id": 3, "timestamp": 100}, {"match_id": 1, "timestamp": 300},
        {"match_id": 2, "timestamp": 200},
    ]}}}
    (tmp_path / "form.json").write_text(json.dumps(snapshot))
    document = {"category": "overall", "source_file": "form.json", "teams": {
        "10": {"overall": {"players": [{"player_id": 1, "player_name": "Keeper",
            "position": "GK", "appearance_count": 2,
            "match_calculations": [record(3, -30, 30), record(1, 90, 90)]}]}}
    }}
    path = tmp_path / "points.json"
    path.write_text(json.dumps(document))
    frame = ppm.load_points_per_90(path, tmp_path)
    assert frame.iloc[0].average_rating == pytest.approx(90 * 1920 / 3120)
    assert frame.iloc[0].position == "GK"


def test_minutes_survive_match_calculation_and_derived_export(tmp_path):
    catalog = derived.MetricCatalog.from_document(json.loads(
        Path("data/reference/kickbase/kickbase_metrics.json").read_text(encoding="utf-8")))
    match = {"match_id": 1, "timestamp": 100, "home_team_id": 10, "away_team_id": 20,
             "home_score": 0, "away_score": 0}
    lineups = {"home": {"players": [{"player": {"id": 1, "name": "Keeper"},
                "teamId": 10, "position": "G", "substitute": False,
                "statistics": {"minutesPlayed": 90}}]},
               "away": {"players": []}}
    payloads = {"ok": True, "payloads": {"lineups": lineups,
                "incidents": {"incidents": []}, "shotmap": {"shotmap": []}}}
    from collections import Counter
    with patch.object(derived, "cached_match_payloads", return_value=payloads):
        players = derived.evaluate_overall_team(None, 10, "Team", [match], 1, catalog, {}, {}, Counter(), [])
    assert players[0]["match_calculations"][0]["minutes_played"] == 90
    path, _ = derived.export_overall_results(tmp_path, Path("form.json"), 1, {},
        {"10": {"team": "Team", "overall": {"players": players}}}, [])
    assert json.loads(path.read_text())["teams"]["10"]["overall"]["players"][0]["match_calculations"][0]["minutes_played"] == 90


@pytest.mark.parametrize("source_key", ["ligainsider", "kickbase", "kicker", "rotowire"])
@pytest.mark.parametrize("injured", [False, True])
def test_goalkeeper_chances_keep_provider_normalization(tmp_path, source_key, injured):
    players = [{"full_name": f"Player {rank}", "displayed_name": f"Player {rank}",
                "player_id": rank, "formation_row": 1, "slot_index": 1,
                "starting_probability_rank": rank, "injury_status": "QUES" if rank == 1 and injured else None}
               for rank in range(1, 4)]
    if source_key == "kicker":
        players += [{"displayed_name": f"Field {rank}", "formation_row": 2, "slot_index": rank,
                     "starting_probability_rank": 1} for rank in range(8)]
    path = tmp_path / "lineups.json"
    path.write_text(json.dumps({"matches": [{
        "home": {"team_name": "Bayern Munich", "players": players},
        "away": {"team_name": "Borussia Dortmund", "players": players},
    }]}))
    source = next(source for source in shared.LINEUP_SOURCES if source.key == source_key)
    _, original = shared.load_lineup_source(source, 0.15, 0.45, path)
    _, special = shared.load_lineup_source(source, 0.15, 0.45, path,
        goalkeeper_alternative_starting_chance_decay=0.6)
    _, expected = shared.load_lineup_source(source, 0.15, 0.6, path)
    for name, candidate in special["bayern"].items():
        assert candidate["chance"] == original["bayern"][name]["chance"]
        assert candidate["goalkeeper_chance"] == expected["bayern"][name]["chance"]
    if source_key != "rotowire" and not injured:
        for rank in range(1, 4):
            candidate = special["bayern"][shared.normalize_name(f"Player {rank}")]
            assert candidate["goalkeeper_chance"] == pytest.approx(0.6 ** (rank - 1) / 1.96)


def test_shared_workflow_exports_new_metric_with_goalkeeper_rules(tmp_path):
    players = pd.DataFrame([
        {"id": 1, "name": "Keeper", "teamId": 2, "position": 1},
        {"id": 2, "name": "Field", "teamId": 2, "position": 2},
        {"id": 3, "name": "Zzzzz", "teamId": 2, "position": 1},
    ])
    values = pd.DataFrame([
        {"player_id": 1, "player_name": "Keeper", "average_rating": 2, "history_status": "usable"},
        {"player_id": 2, "player_name": "Field", "average_rating": -1, "history_status": "usable"},
    ])
    metric = shared.ScoreMetricInput(Path("points.json"), values, ppm.METRIC_COLUMN, "Points/90", ppm.OUTPUT_LABEL)
    chances = {"ligainsider": 0.8, "kickbase": 0.6, "kicker": 0.4, "rotowire": 0.2}

    def load_source(source, *args, **kwargs):
        return Path(f"{source.key}.json"), {"bayern": {
            shared.normalize_name(name): {"name": name, "id": index + 1,
                "chance": 0.9, "goalkeeper_chance": chances[source.key]}
            for index, name in enumerate(players.name)
        }}

    mocks = {
        "request_matchday": lambda: 3,
        "select_latest_kbstats_csv": lambda: SimpleNamespace(path=Path("players.csv"), timestamp_text="test"),
        "load_kbstats_players": lambda path: players,
        "load_expected_match_points": lambda day: ({"bayern": 2.8}, pd.DataFrame()),
        "load_lineup_source": load_source,
        "_load_lineup_overrides": lambda: pd.DataFrame(),
        "_load_name_only_lineup_overrides": lambda: pd.DataFrame(),
        "load_rating_overrides": lambda: pd.DataFrame(),
        "display": lambda value: None,
        "prune_timestamped_outputs": lambda: None,
    }
    with ExitStack() as stack:
        for name, replacement in mocks.items():
            stack.enter_context(patch.object(shared, name, replacement))
        stack.enter_context(patch.object(shared, "EXPECTED_POINTS_DIR", tmp_path))
        # Exclude the stale RotoWire source using the real confirmation workflow.
        stack.enter_context(patch("builtins.input", side_effect=["y", "y", "y", "n"]))
        result = shared.run_score_creation("overall", metric_input=metric,
            goalkeeper_alternative_starting_chance_decay=0.6)
    scored = result["scored_players"]
    keeper_points = 1.1 + 2.8 * (0.6 / 3)
    assert scored.expected_match_points.tolist() == pytest.approx([keeper_points, 2.8, keeper_points])
    chance = (4 * 0.8 + 3 * 0.6 + 2 * 0.4) / 9
    assert scored.iloc[0].score == pytest.approx(round(2 * keeper_points * chance, 6))
    assert scored.iloc[1].score == pytest.approx(-1 * 2.8 * 0.9)
    assert scored.iloc[2].score == 0
    assert result["review"].iloc[2].metric_status == "missing_history"
    assert not result["lineup_source_is_current"]["rotowire"]
    assert ppm.OUTPUT_LABEL in result["output_path"].name
    exported = pd.read_csv(result["output_path"])
    assert exported.columns[:len(players.columns)].tolist() == players.columns.tolist()
    assert ppm.METRIC_COLUMN in exported
    assert "sofascore_average_rating" not in exported
