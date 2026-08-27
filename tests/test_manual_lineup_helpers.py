import unittest

import pandas as pd

from manual_lineup_helpers import (
    PreparedData,
    _candidate_indices,
    canonical_arena,
    normalize_formation,
    validate_manual_lineup,
)


class ManualLineupHelpersTests(unittest.TestCase):
    def setUp(self):
        positions = ["GK"] + ["DEF"] * 4 + ["MID"] * 4 + ["FOR"] * 2
        teams = [
            "bayern", "dortmund", "frankfurt", "freiburg", "hamburg", "leverkusen",
            "schalke", "stuttgart", "bremen", "augsburg", "hoffenheim",
        ]
        frame = pd.DataFrame({
            "id": list(range(1, 12)),
            "name": [f"Manual Player {index}" for index in range(1, 12)],
            "score": [float(index) for index in range(1, 12)],
            "marketValue": [10_000_000] * 11,
        })
        self.prepared = PreparedData(
            df=frame,
            original_columns=list(frame.columns),
            columns={
                "player_id": "id", "player_name": "name", "score": "score",
                "market_value": "marketValue", "club": "club", "position": "position",
            },
            positions=pd.Series(positions),
            score_numeric=pd.Series([float(index) for index in range(1, 12)]),
            score_units=pd.Series(list(range(1, 12)), dtype=object),
            score_scale=1,
            value_numeric=pd.Series([10_000_000.0] * 11),
            value_eur=pd.Series([10_000_000] * 11, dtype=object),
            value_unit="euros",
            team_keys=pd.Series(teams, dtype="string"),
            team_raw_to_key={},
        )

    def test_arena_alias_and_formation_normalization(self):
        self.assertEqual(canonical_arena("Kickbasekis Arena").budget_eur, 150_000_000)
        self.assertEqual(canonical_arena("Bundesliga Arena").max_players_per_club, 3)
        insider = canonical_arena("Kickbase.insider Arena")
        self.assertEqual(insider.budget_eur, 180_000_000)
        self.assertEqual(insider.max_players_per_club, 1)
        self.assertEqual(insider.max_players_per_match, 2)
        self.assertEqual(insider.squad_size, 6)
        self.assertEqual(insider.selected_lineup_filename, "kickbase.insider-arena.json")
        self.assertEqual(set(insider.formations or {}), {"2-2-1", "2-1-2", "1-2-2"})
        all_limits = canonical_arena("All Limits Arena")
        self.assertEqual(all_limits.budget_eur, 150_000_000)
        self.assertEqual(all_limits.max_players_per_club, 1)
        self.assertEqual(all_limits.max_players_per_match, 2)
        self.assertEqual(all_limits.squad_size, 11)
        self.assertEqual(all_limits.selected_lineup_filename, "all-limits-arena.json")
        self.assertEqual(set(all_limits.formations or {}), {
            "4-4-2", "4-2-4", "3-4-3", "4-3-3", "5-3-2",
            "3-5-2", "5-4-1", "4-5-1", "3-6-1", "5-2-3",
        })
        self.assertEqual(normalize_formation(" 4 – 4 – 2 "), "4-4-2")

    def test_player_candidates_use_exact_then_fuzzy_matching(self):
        kind, candidates = _candidate_indices(self.prepared, "Manual Player 1")
        self.assertEqual((kind, candidates), ("exact", [0]))
        kind, candidates = _candidate_indices(self.prepared, "Manual Plaeyr 1")
        self.assertEqual(kind, "fuzzy")
        self.assertEqual(candidates[0], 0)

    def test_budget_is_separate_from_other_rule_validity(self):
        valid = validate_manual_lineup(
            self.prepared, list(range(11)), "4-4-2", canonical_arena("Bundesliga Arena"), [], 0
        )
        self.assertTrue(valid["non_budget_valid"])
        self.assertTrue(valid["budget_valid"])
        self.prepared.value_eur[:] = 20_000_000
        over_budget = validate_manual_lineup(
            self.prepared, list(range(11)), "4-4-2", canonical_arena("KickbaseKIS Arena"), [], 0
        )
        self.assertTrue(over_budget["non_budget_valid"])
        self.assertFalse(over_budget["budget_valid"])
        self.assertEqual(over_budget["budget_excess_eur"], 70_000_000)

    def test_insider_arena_validates_a_six_player_lineup(self):
        selected = [0, 1, 2, 5, 6, 9]
        validation = validate_manual_lineup(
            self.prepared,
            selected,
            "2-2-1",
            canonical_arena("Kickbase.insider Arena"),
            [],
            0,
        )

        self.assertTrue(validation["non_budget_valid"])
        self.assertTrue(validation["budget_valid"])
        self.assertEqual(validation["total_value_eur"], 60_000_000)

    def test_all_limits_arena_validates_a_standard_eleven_player_lineup(self):
        validation = validate_manual_lineup(
            self.prepared,
            list(range(11)),
            "4-4-2",
            canonical_arena("All Limits Arena"),
            [],
            0,
        )

        self.assertTrue(validation["non_budget_valid"])
        self.assertTrue(validation["budget_valid"])
        self.assertEqual(validation["total_value_eur"], 110_000_000)


if __name__ == "__main__":
    unittest.main()
