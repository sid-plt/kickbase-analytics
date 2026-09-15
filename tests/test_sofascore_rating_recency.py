"""Recency weighting uses team match slots, independent of performance."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import sofascore_rating_odds_lineup_score as scoring
from sofascore_average_rating_score import load_category_ratings


class RatingRecencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "ratings.csv"
        self.matches = [{"match_id": i, "timestamp": i * 1000} for i in range(1, 6)]
        self.trail = [{"match_id": i, "rating": float(i + 4)} for i in range(1, 6)]
        self.patcher = patch.object(scoring, "SOFASCORE_TEAM_FORM_DIR", self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def write_inputs(self):
        average = round(sum(r["rating"] for r in self.trail) / len(self.trail), 2)
        player = dict(player_id=10, player_name="Player", rating_count=len(self.trail), average_rating=average, ratings=self.trail)
        self.document = dict(source_file="form.json", teams={"1": {"overall": {"players": [player]}}})
        self.path.with_suffix(".json").write_text(json.dumps(self.document), encoding="utf-8")
        (self.root / "form.json").write_text(json.dumps({"snapshot": {"1": {"overall_matches": self.matches}}}), encoding="utf-8")
        pd.DataFrame([dict(team_id=1, category=category, **{k: v for k, v in player.items() if k != "ratings"}) for category in ("overall", "bundesliga")]).to_csv(self.path, index=False)

    def value(self):
        return scoring.load_score_ratings(self.path, "overall").iloc[0]["average_rating"]

    def test_chronology_and_symmetric_performance(self):
        self.matches.reverse()
        self.trail.reverse()
        self.write_inputs()
        self.assertEqual(self.value(), 7.4)
        for record in self.trail:
            record["rating"] = 14 - record["rating"]
        self.write_inputs()
        self.assertEqual(self.value(), 6.6)

    def test_missing_matches_keep_slots(self):
        self.trail = [{"match_id": 1, "rating": 5}, {"match_id": 4, "rating": 9}]
        self.write_inputs()
        self.assertEqual(self.value(), 7.67)  # (5*12 + 9*24) / 36

    def test_short_window_single_rating_and_constant_ratings(self):
        self.matches = self.matches[:2]
        self.trail = [{"match_id": 1, "rating": 5}, {"match_id": 2, "rating": 9}]
        self.write_inputs()
        self.assertEqual(self.value(), 7.15)
        self.trail = self.trail[:1]
        self.write_inputs()
        self.assertEqual(self.value(), 5)
        self.trail = [{"match_id": i, "rating": 7.125} for i in (1, 2)]
        self.write_inputs()
        self.assertEqual(self.value(), 7.13)

    def test_date_fallback_and_match_id_tiebreak(self):
        self.matches = [{"match_id": i, "date": "2026-09-01T00:00:00Z"} for i in range(1, 6)]
        self.write_inputs()
        self.assertEqual(self.value(), 7.4)

    def test_other_calculators_unchanged(self):
        self.write_inputs()
        self.assertEqual(load_category_ratings(self.path, "overall").iloc[0]["average_rating"], 7)
        self.path.with_suffix(".json").unlink()
        self.assertEqual(scoring.load_score_ratings(self.path, "bundesliga").iloc[0]["average_rating"], 7)

    def test_missing_sources(self):
        for missing in ("ratings.json", "form.json"):
            with self.subTest(missing=missing):
                self.write_inputs()
                (self.root / missing).unlink()
                with self.assertRaisesRegex(ValueError, "Cannot apply overall recency"):
                    self.value()

    def test_inconsistent_trails_and_chronology(self):
        for issue in ("duplicate", "unknown", "invalid", "count", "csv", "date"):
            with self.subTest(issue=issue):
                self.write_inputs()
                player = self.document["teams"]["1"]["overall"]["players"][0]
                if issue == "duplicate":
                    player["ratings"][1]["match_id"] = 1
                elif issue == "unknown":
                    player["ratings"][1]["match_id"] = 99
                elif issue == "invalid":
                    player["ratings"][1]["rating"] = "bad"
                elif issue == "count":
                    player["rating_count"] = 99
                elif issue == "csv":
                    player["average_rating"] = 1
                else:
                    (self.root / "form.json").write_text(json.dumps({"1": {"overall_matches": [{"match_id": 1}]}}))
                self.path.with_suffix(".json").write_text(json.dumps(self.document))
                with self.assertRaisesRegex(ValueError, "Cannot apply overall recency"):
                    self.value()
                self.trail = [{"match_id": i, "rating": float(i + 4)} for i in range(1, 6)]


if __name__ == "__main__":
    unittest.main()
