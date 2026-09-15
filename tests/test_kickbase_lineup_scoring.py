"""Regression checks for the display-name predicted-lineup integrations."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from kickbase_player_name_cross_references import (
    REFERENCE_COLUMNS,
    load_references,
    persist_references,
)
from kbstats_points_odds_lineup_score import COMMON_OUTPUT_COLUMNS, _resolve_lineups
from project_paths import KICKBASE_PREDICTED_LINEUPS_DIR
from sofascore_rating_odds_lineup_score import (
    KB_TEAM_ID_TO_KEY,
    DEFAULT_ALTERNATIVE_STARTING_CHANCE_DECAY,
    DEFAULT_LINEUP_SOURCE_WEIGHTS,
    LINEUP_SOURCE_REGISTRY,
    _fuzzy_candidates,
    _add_kicker_identity_candidates,
    _kickbase_chances,
    _kicker_chances,
    _ligainsider_chances,
    blend_lineup_chances,
    build_kickbase_name_indexes,
    canonical_team,
    confirm_lineup_source_matchdays,
    load_lineup_source,
    resolve_kickbase_display_name,
    resolve_name_only_lineup_match,
    resolve_lineup_source_weights,
    validate_alternative_starting_chance_decay,
)


class KickbaseLineupScoringTests(unittest.TestCase):
    def test_cross_reference_resolves_first_name_surname_collision(self) -> None:
        players = pd.DataFrame([
            {"firstName": "Moritz", "lastName": "Nicolas"},
            {"firstName": "Nicolas", "lastName": "Kühn"},
        ])
        indexes = build_kickbase_name_indexes(players, pd.Series(["gladbach", "gladbach"]))["gladbach"]
        candidate = {"name": "NICOLAS", "chance": 1.0}
        candidates = {"nicolas": candidate}
        for source in ("kickbase", "kicker"):
            with self.subTest(source=source):
                self.assertIsNone(resolve_kickbase_display_name(candidates, players.iloc[0], indexes))
                self.assertIsNone(resolve_kickbase_display_name(candidates, players.iloc[1], indexes))
                chosen, status = resolve_name_only_lineup_match(
                    candidates, "Moritz Nicolas", players.iloc[0], indexes, "Nicolas"
                )
                self.assertIs(chosen, candidate)
                self.assertEqual(status, "override")
                chosen, _ = resolve_name_only_lineup_match(
                    candidates, "Nicolas Kühn", players.iloc[1], indexes
                )
                self.assertIsNone(chosen)

    def test_kicker_starter_abbreviation_uses_url_without_adding_bench(self) -> None:
        kim = {"displayed_name": "M.-J. Kim", "player_url":
               "https://www.kicker.de/min-jae-kim/spieler/bundesliga/2026-27/fc-bayern-muenchen",
               "formation_row": 2, "slot_index": 2, "starting_probability_rank": 1}
        candidates = _kicker_chances([kim])
        team = {"players": [kim], "kicker_details": {
            "bench": {"players": [{"displayed_name": "Bench Player"}]},
            "unavailable": {"players": [{"name": "Absent"}]}}}
        original_keys = set(candidates)
        _add_kicker_identity_candidates(candidates, team)
        self.assertEqual(set(candidates), original_keys)
        offered = _fuzzy_candidates("Kim Minjae", candidates)
        self.assertEqual(offered[0][1]["name"], "M.-J. Kim")
        self.assertEqual(offered[0][1]["chance"], 1.0)

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

    @staticmethod
    def _kickbase_team_players() -> list[dict[str, object]]:
        return [
            {
                "displayed_name": f"STARTER {slot}",
                "formation_row": 1,
                "slot_index": slot,
                "starting_probability_rank": 1,
                "injury_status": None,
            }
            for slot in range(1, 12)
        ]

    def test_repeated_kickbase_alternative_has_more_evidence_than_single_alternative(self) -> None:
        players = self._kickbase_team_players() + [
            {"displayed_name": "SINGLE", "formation_row": 1, "slot_index": 1, "starting_probability_rank": 2, "injury_status": None},
            {"displayed_name": "REPEATED", "formation_row": 1, "slot_index": 2, "starting_probability_rank": 2, "injury_status": None},
            {"displayed_name": "REPEATED", "formation_row": 1, "slot_index": 3, "starting_probability_rank": 2, "injury_status": None},
        ]
        chances = _kickbase_chances(players)
        self.assertGreater(chances["repeated"]["chance"], chances["single"]["chance"])
        self.assertLess(chances["repeated"]["chance"], chances["starter1"]["chance"])
        self.assertEqual(1.0, chances["starter4"]["chance"])

    def test_kickbase_snapshot_parser_keeps_repeated_alternative_evidence(self) -> None:
        source = next(source for source in LINEUP_SOURCE_REGISTRY if source.key == "kickbase")
        players = self._kickbase_team_players() + [
            {"displayed_name": "REPEATED", "formation_row": 1, "slot_index": 1, "starting_probability_rank": 2, "injury_status": None},
            {"displayed_name": "REPEATED", "formation_row": 1, "slot_index": 2, "starting_probability_rank": 2, "injury_status": None},
        ]
        document = {
            "metadata": {"source": "Kickbase"},
            "matches": [
                {
                    "home": {"team_name": "Bayern München", "players": players},
                    "away": {"team_name": "VfB Stuttgart", "players": players},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "kickbase_bundesliga_lineups_20260904_120000.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            _, teams = load_lineup_source(replace(source, directory=Path(temporary_directory)))
        self.assertIn("repeated", teams["bayern"])
        self.assertGreater(teams["bayern"]["repeated"]["chance"], 0.45)
        self.assertEqual(1.0, teams["bayern"]["starter3"]["chance"])

    def test_kicker_abbreviated_gladbach_team_name_is_canonicalized(self) -> None:
        self.assertEqual("gladbach", canonical_team("Bor. Mönchengladbach"))

    def test_kicker_keeps_geometric_slot_normalization(self) -> None:
        chances = _kicker_chances(self._kickbase_slot_players(4))
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

    def test_primary_kickbase_player_stays_primary_when_repeated_as_an_alternative(self) -> None:
        players = self._kickbase_team_players() + [
            {"displayed_name": "STARTER 1", "formation_row": 1, "slot_index": 2, "starting_probability_rank": 2, "injury_status": None},
            {"displayed_name": "ALTERNATIVE", "formation_row": 1, "slot_index": 3, "starting_probability_rank": 2, "injury_status": None},
        ]
        chances = _kickbase_chances(players)
        self.assertGreater(chances["starter1"]["chance"], chances["alternative"]["chance"])
        self.assertEqual(1.0, chances["starter1"]["chance"])
        self.assertLess(chances["starter2"]["chance"], 1.0)

    def test_kickbase_unchallenged_starter_remains_certain(self) -> None:
        players = self._kickbase_team_players() + [
            {"displayed_name": "ALTERNATIVE", "formation_row": 1, "slot_index": 2, "starting_probability_rank": 2, "injury_status": None},
        ]
        chances = _kickbase_chances(players)
        self.assertEqual(1.0, chances["starter1"]["chance"])
        self.assertAlmostEqual(1.0 / 1.45, chances["starter2"]["chance"])
        self.assertAlmostEqual(0.45 / 1.45, chances["alternative"]["chance"])

    def test_kickbase_questionable_alternative_keeps_penalty_interface(self) -> None:
        baseline_players = self._kickbase_team_players() + [
            {"displayed_name": "ALTERNATIVE", "formation_row": 1, "slot_index": 1, "starting_probability_rank": 2, "injury_status": None},
        ]
        questionable_players = [dict(player) for player in baseline_players]
        questionable_players[-1]["injury_status"] = "QUES"
        baseline = _kickbase_chances(baseline_players)["alternative"]["chance"]
        penalized = _kickbase_chances(
            questionable_players,
            questionable_injury_starting_chance_penalty=0.15,
        )["alternative"]["chance"]
        self.assertLess(penalized, baseline)

    def test_decay_and_source_weight_validation(self) -> None:
        self.assertEqual(0.45, DEFAULT_ALTERNATIVE_STARTING_CHANCE_DECAY)
        self.assertEqual(0.45, validate_alternative_starting_chance_decay(0.45))
        with self.assertRaises(ValueError):
            validate_alternative_starting_chance_decay(1.01)
        self.assertEqual(DEFAULT_LINEUP_SOURCE_WEIGHTS, resolve_lineup_source_weights(None))
        self.assertEqual(
            {"ligainsider": 4.0, "kickbase": 0.0, "kicker": 2.0, "rotowire": 1.0},
            resolve_lineup_source_weights(
                {"ligainsider": 4, "kickbase": 0, "kicker": 2, "rotowire": 1}
            ),
        )
        with self.assertRaises(ValueError):
            resolve_lineup_source_weights(
                {"ligainsider": 4.0, "kickbase": 3.0, "rotowire": 1.0}
            )
        with self.assertRaises(ValueError):
            resolve_lineup_source_weights(
                {"ligainsider": 0.0, "kickbase": 0.0, "kicker": 0.0, "rotowire": 0.0}
            )
        with self.assertRaises(ValueError):
            resolve_lineup_source_weights(
                {"ligainsider": True, "kickbase": 3.0, "kicker": 2.0, "rotowire": 1.0}
            )

    def test_configured_weights_blend_only_the_positive_available_sources(self) -> None:
        self.assertAlmostEqual(0.5, blend_lineup_chances([(4.0, 1.0), (3.0, 0.0), (1.0, 0.0)]))
        self.assertAlmostEqual(0.8, blend_lineup_chances([(4.0, 1.0), (1.0, 0.0)]))
        with self.assertRaises(ValueError):
            blend_lineup_chances([])

    def test_previous_matchday_source_is_excluded_after_confirmation(self) -> None:
        source_inputs = {
            source.key: (Path(f"{source.key}.json"), {"bayern": {"player": {"chance": 1.0}}})
            for source in LINEUP_SOURCE_REGISTRY
        }
        with patch("builtins.input", side_effect=["a", "p", "accurate", "previous"]):
            confirmed, source_is_current = confirm_lineup_source_matchdays(2, source_inputs)
        self.assertEqual(
            {
                "ligainsider": True,
                "kickbase": False,
                "kicker": True,
                "rotowire": False,
            },
            source_is_current,
        )
        self.assertEqual({"bayern"}, set(confirmed["ligainsider"][1]))
        self.assertEqual({}, confirmed["kickbase"][1])
        self.assertEqual({"bayern"}, set(confirmed["kicker"][1]))
        self.assertEqual({}, confirmed["rotowire"][1])

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

    def test_kicker_snapshot_uses_name_only_slot_chances(self) -> None:
        source = next(source for source in LINEUP_SOURCE_REGISTRY if source.key == "kicker")
        players = [
            {
                "full_name": None,
                "displayed_name": f"Kicker Player {slot}",
                "formation_row": 1,
                "slot_index": slot,
                "starting_probability_rank": 1,
                "injury_status": None,
            }
            for slot in range(1, 12)
        ]
        document = {
            "metadata": {"source": "Kicker"},
            "matches": [
                {
                    "home": {"team_name": "Bayern München", "players": players},
                    "away": {"team_name": "VfB Stuttgart", "players": players},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "kicker_bundesliga_lineups_20260827_120000.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            _, teams = load_lineup_source(replace(source, directory=Path(temporary_directory)))
        self.assertEqual(1.0, teams["bayern"]["kickerplayer1"]["chance"])

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

    def test_normalized_kickbase_name_beats_a_stale_override_before_fuzzy_matching(self) -> None:
        players = pd.DataFrame([{"firstName": "Josha", "lastName": "Vagnoman"}])
        team_keys = pd.Series(["stuttgart"])
        indexes = build_kickbase_name_indexes(players, team_keys)["stuttgart"]
        candidates = {"vagnoman": {"name": "VAGNOMAN", "chance": 1.0}}
        chosen, status = resolve_name_only_lineup_match(
            candidates,
            "Josha Vagnoman",
            players.iloc[0],
            indexes,
            override_displayed_name="VAGNONAM",
        )
        self.assertEqual("VAGNOMAN", chosen["name"])
        self.assertEqual("normalized", status)

    def test_kbstats_lineup_resolution_prefers_current_name_over_stale_override(self) -> None:
        players = pd.DataFrame(
            [
                {
                    "id": "42",
                    "name": "Josha Vagnoman",
                    "firstName": "Josha",
                    "lastName": "Vagnoman",
                }
            ]
        )
        team_keys = pd.Series(["stuttgart"])
        lineup_inputs = {
            source.key: (Path(f"{source.key}.json"), {})
            for source in LINEUP_SOURCE_REGISTRY
        }
        lineup_inputs["kickbase"] = (
            Path("kickbase.json"),
            {
                "stuttgart": {
                    "vagnoman": {"name": "VAGNOMAN", "chance": 1.0},
                    "vagnonam": {"name": "VAGNONAM", "chance": 0.5},
                }
            },
        )
        override = pd.DataFrame(
            [
                {
                    "source": "kickbase",
                    "canonical_team": "stuttgart",
                    "kbstats_name": "Josha Vagnoman",
                    "displayed_name": "VAGNONAM",
                    "_key": ("kickbase", "stuttgart", "joshavagnoman"),
                }
            ]
        )
        empty = pd.DataFrame()
        with patch("kbstats_points_odds_lineup_score._load_lineup_overrides", return_value=empty), patch(
            "kbstats_points_odds_lineup_score._load_name_only_lineup_overrides", return_value=override
        ):
            resolution, _, _ = _resolve_lineups(
                players, team_keys, {"42"}, lineup_inputs
            )
        chosen, status = resolution[(0, "kickbase")]
        self.assertEqual("VAGNOMAN", chosen["name"])
        self.assertEqual("normalized", status)

    def test_confirmed_name_only_mapping_is_provider_scoped_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "kickbase_player_name_cross_references.csv"
            frame = load_references(path)
            frame.loc[len(frame)] = [
                "kickbase",
                "bayern",
                "KBStats Name",
                "KICKBASE DISPLAY NAME",
                "2026-08-19T00:00:00+02:00",
            ]
            frame.loc[len(frame)] = [
                "kicker",
                "bayern",
                "KBStats Name",
                "KICKER DISPLAY NAME",
                "2026-08-19T00:00:00+02:00",
            ]
            persist_references(frame, path)
            restored = load_references(path)
            self.assertEqual(list(REFERENCE_COLUMNS), list(restored.columns))
            self.assertEqual("KICKBASE DISPLAY NAME", restored.loc[0, "displayed_name"])
            self.assertEqual("KICKER DISPLAY NAME", restored.loc[1, "displayed_name"])

    def test_source_ranks_activate_kicker(self) -> None:
        registry = {source.key: source for source in LINEUP_SOURCE_REGISTRY}
        self.assertEqual(4, registry["ligainsider"].rank)
        self.assertEqual(3, registry["kickbase"].rank)
        self.assertEqual(2, registry["kicker"].rank)
        self.assertTrue(registry["kicker"].active)
        self.assertEqual(1, registry["rotowire"].rank)
        self.assertIn("kickbase_starting_chance", COMMON_OUTPUT_COLUMNS)
        self.assertIn("kicker_starting_chance", COMMON_OUTPUT_COLUMNS)


if __name__ == "__main__":
    unittest.main()
