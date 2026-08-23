"""Regression checks for the name-only Kickbase lineup snapshot integration."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from kickbase_player_name_cross_references import (
    REFERENCE_COLUMNS,
    load_references,
    persist_references,
)
from kbstats_points_odds_lineup_score import COMMON_OUTPUT_COLUMNS
from project_paths import KICKBASE_PREDICTED_LINEUPS_DIR
from sofascore_rating_odds_lineup_score import (
    KB_TEAM_ID_TO_KEY,
    DEFAULT_ALTERNATIVE_STARTING_CHANCE_DECAY,
    DEFAULT_LINEUP_SOURCE_WEIGHTS,
    LINEUP_SOURCE_REGISTRY,
    _fuzzy_candidates,
    _kickbase_chances,
    _ligainsider_chances,
    blend_lineup_chances,
    build_kickbase_name_indexes,
    load_lineup_source,
    resolve_kickbase_display_name,
    resolve_lineup_source_weights,
    validate_alternative_starting_chance_decay,
)


class KickbaseLineupScoringTests(unittest.TestCase):
    @staticmethod
    def _kickbase_slot_players(count: int, questionable_rank: int | None = None) -> list[dict[str, object]]:
        return [
            {
                "displayed_name": f"DISPLAY {rank}",
                "formation_row": 1,
                "slot_index": 1,
                "starting_probability_rank": rank,
                "injury_status": "QUES" if rank == questionable_rank else None,
            }
            for rank in range(1, count + 1)
        ]

    def test_geometric_decay_normalizes_three_kickbase_alternatives(self) -> None:
        chances = _kickbase_chances(self._kickbase_slot_players(3))
        denominator = 1.0 + 0.45 + 0.2025
        self.assertAlmostEqual(1.0 / denominator, chances["display1"]["chance"])
        self.assertAlmostEqual(0.45 / denominator, chances["display2"]["chance"])
        self.assertAlmostEqual(0.2025 / denominator, chances["display3"]["chance"])
        self.assertAlmostEqual(1.0, sum(entry["chance"] for entry in chances.values()))

    def test_geometric_decay_supports_four_or_more_alternatives(self) -> None:
        chances = _kickbase_chances(self._kickbase_slot_players(4))
        denominator = sum(0.45 ** exponent for exponent in range(4))
        self.assertAlmostEqual(0.45 ** 3 / denominator, chances["display4"]["chance"])
        self.assertAlmostEqual(1.0, sum(entry["chance"] for entry in chances.values()))

    def test_ligainsider_uses_the_same_geometric_slot_decay(self) -> None:
        players = [
            {
                "full_name": f"Player {rank}",
                "player_id": rank,
                "formation_row": 1,
                "slot_index": 1,
                "starting_probability_rank": rank,
                "injury_status": None,
            }
            for rank in range(1, 4)
        ]
        chances = _ligainsider_chances(players)
        denominator = 1.0 + 0.45 + 0.2025
        self.assertAlmostEqual(0.45 / denominator, chances["player2"]["chance"])

    def test_questionable_penalty_stays_after_geometric_base_chances(self) -> None:
        chances = _kickbase_chances(
            self._kickbase_slot_players(2, questionable_rank=1),
            questionable_injury_starting_chance_penalty=0.15,
        )
        initial_first = 1.0 / 1.45
        initial_second = 0.45 / 1.45
        remaining_total = initial_first - 0.15 + initial_second
        self.assertAlmostEqual((initial_first - 0.15) / remaining_total, chances["display1"]["chance"])
        self.assertAlmostEqual(initial_second / remaining_total, chances["display2"]["chance"])

    def test_decay_and_source_weight_validation(self) -> None:
        self.assertEqual(0.45, DEFAULT_ALTERNATIVE_STARTING_CHANCE_DECAY)
        self.assertEqual(0.45, validate_alternative_starting_chance_decay(0.45))
        with self.assertRaises(ValueError):
            validate_alternative_starting_chance_decay(1.01)
        self.assertEqual(DEFAULT_LINEUP_SOURCE_WEIGHTS, resolve_lineup_source_weights(None))
        self.assertEqual(
            {"ligainsider": 4.0, "kickbase": 0.0, "rotowire": 1.0},
            resolve_lineup_source_weights(
                {"ligainsider": 4, "kickbase": 0, "rotowire": 1}
            ),
        )
        with self.assertRaises(ValueError):
            resolve_lineup_source_weights({"ligainsider": 4.0, "kickbase": 3.0})
        with self.assertRaises(ValueError):
            resolve_lineup_source_weights(
                {"ligainsider": 0.0, "kickbase": 0.0, "rotowire": 0.0}
            )
        with self.assertRaises(ValueError):
            resolve_lineup_source_weights(
                {"ligainsider": True, "kickbase": 3.0, "rotowire": 1.0}
            )

    def test_configured_weights_blend_only_the_positive_available_sources(self) -> None:
        self.assertAlmostEqual(0.5, blend_lineup_chances([(4.0, 1.0), (3.0, 0.0), (1.0, 0.0)]))
        self.assertAlmostEqual(0.8, blend_lineup_chances([(4.0, 1.0), (1.0, 0.0)]))
        with self.assertRaises(ValueError):
            blend_lineup_chances([])

    def test_saved_matchday_one_snapshot_has_name_only_primary_starters(self) -> None:
        snapshots = sorted(KICKBASE_PREDICTED_LINEUPS_DIR.glob("kickbase_bundesliga_lineups_*.json"))
        self.assertTrue(snapshots, "expected the saved Kickbase Matchday 1 snapshot")
        document = json.loads(snapshots[-1].read_text(encoding="utf-8"))
        teams = [team for match in document["matches"] for team in (match["home"], match["away"])]
        self.assertEqual(18, len(teams))
        self.assertEqual(18, len({team["team_name"] for team in teams}))
        self.assertEqual(198, sum(player["starting_probability_rank"] == 1 for team in teams for player in team["players"]))
        for player in (player for team in teams for player in team["players"]):
            self.assertIsNone(player["full_name"])
            self.assertIsNone(player["player_id"])
            self.assertIsNone(player["player_url"])

    def test_parser_excludes_placeholders_and_keeps_slot_alternatives(self) -> None:
        source = next(source for source in LINEUP_SOURCE_REGISTRY if source.key == "kickbase")
        _, teams = load_lineup_source(source)
        self.assertEqual(set(KB_TEAM_ID_TO_KEY.values()), set(teams))
        self.assertFalse(any(entry["name"].casefold() == "neuzugang" for team in teams.values() for entry in team.values()))
        self.assertTrue(any(entry["chance"] < 1.0 for team in teams.values() for entry in team.values()))

    def test_kickbase_prompt_candidates_require_fifty_percent_similarity(self) -> None:
        candidates = {
            "displayone": {"name": "Display One", "chance": 1.0},
            "completelydifferent": {"name": "Completely Different", "chance": 1.0},
        }
        choices = _fuzzy_candidates("Display Name", candidates)
        self.assertEqual(
            {"Display One"},
            {candidate["name"] for _, candidate in choices},
        )
        self.assertEqual([], _fuzzy_candidates("zzzz", candidates))

    def test_unique_last_name_then_first_name_resolve_without_prompt(self) -> None:
        players = pd.DataFrame(
            [
                {"firstName": "Jonathan", "lastName": "Tah"},
                {"firstName": "Manuel", "lastName": "Neuer"},
            ]
        )
        team_keys = pd.Series(["bayern", "bayern"])
        indexes = build_kickbase_name_indexes(players, team_keys)["bayern"]
        candidates = {
            "tah": {"name": "TAH", "chance": 1.0},
            "manuel": {"name": "MANUEL", "chance": 1.0},
        }
        self.assertEqual(
            "TAH",
            resolve_kickbase_display_name(candidates, players.iloc[0], indexes)["name"],
        )
        self.assertEqual(
            "MANUEL",
            resolve_kickbase_display_name(candidates, players.iloc[1], indexes)["name"],
        )

    def test_shared_name_part_remains_unresolved_for_notebook_confirmation(self) -> None:
        players = pd.DataFrame(
            [
                {"firstName": "Max", "lastName": "Muster"},
                {"firstName": "Moritz", "lastName": "Muster"},
            ]
        )
        team_keys = pd.Series(["bayern", "bayern"])
        indexes = build_kickbase_name_indexes(players, team_keys)["bayern"]
        candidates = {"muster": {"name": "MUSTER", "chance": 1.0}}
        self.assertIsNone(resolve_kickbase_display_name(candidates, players.iloc[0], indexes))

    def test_confirmed_kickbase_mapping_is_team_scoped_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "kickbase_player_name_cross_references.csv"
            frame = load_references(path)
            frame.loc[len(frame)] = ["bayern", "KBStats Name", "DISPLAY NAME", "2026-08-19T00:00:00+02:00"]
            persist_references(frame, path)
            restored = load_references(path)
            self.assertEqual(list(REFERENCE_COLUMNS), list(restored.columns))
            self.assertEqual("DISPLAY NAME", restored.loc[0, "kickbase_displayed_name"])

    def test_source_ranks_reserve_inactive_kicker(self) -> None:
        registry = {source.key: source for source in LINEUP_SOURCE_REGISTRY}
        self.assertEqual(4, registry["ligainsider"].rank)
        self.assertEqual(3, registry["kickbase"].rank)
        self.assertEqual(2, registry["kicker"].rank)
        self.assertFalse(registry["kicker"].active)
        self.assertEqual(1, registry["rotowire"].rank)
        self.assertIn("kickbase_starting_chance", COMMON_OUTPUT_COLUMNS)


if __name__ == "__main__":
    unittest.main()
