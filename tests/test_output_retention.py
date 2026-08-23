from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from project_paths import prune_timestamped_outputs


def _compact_timestamp(index: int) -> str:
    return (datetime(2026, 8, 1, tzinfo=timezone.utc) + timedelta(seconds=index)).strftime(
        "%Y%m%d_%H%M%S_+0000"
    )


def _write(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("fixture\n", encoding="utf-8")
    return path


class TimestampedOutputRetentionTests(unittest.TestCase):
    def test_does_nothing_for_an_empty_output_tree(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            self.assertEqual(prune_timestamped_outputs(Path(temporary_directory)), [])

    def test_does_not_remove_a_family_with_ten_or_fewer_files(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory) / "kbstats" / "players"
            files = [_write(directory, f"kbstats_players_{_compact_timestamp(index)}.csv") for index in range(10)]

            self.assertEqual(prune_timestamped_outputs(Path(temporary_directory)), [])
            self.assertTrue(all(path.exists() for path in files))

    def test_keeps_only_the_ten_newest_files_in_one_family(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory) / "expected_points"
            files = [
                _write(directory, f"expected_points_input_sofascore_overall_{_compact_timestamp(index)}.csv")
                for index in range(12)
            ]

            removed = prune_timestamped_outputs(Path(temporary_directory))

            self.assertEqual(removed, files[:2])
            self.assertEqual([path for path in files if path.exists()], files[2:])

    def test_uses_final_timestamp_and_preserves_datatypes_and_labels(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory) / "transfermarkt" / "squads"
            old_source_new_output = _write(
                directory,
                "squads_20260801_010101_+0000_p80_20260802_010101_+0000.csv",
            )
            newest_source_old_output = _write(
                directory,
                "squads_20260810_010101_+0000_p80_20260701_010101_+0000.csv",
            )
            _write(directory, "squads_20260801_010101_+0000_p90_20260802_010101_+0000.csv")
            _write(directory, "squads_20260801_010101_+0000_p80_20260802_010101_+0000.json")
            for index in range(10):
                _write(
                    directory,
                    f"squads_20260801_010101_+0000_p80_{_compact_timestamp(index + 20)}.csv",
                )

            removed = prune_timestamped_outputs(Path(temporary_directory))

            self.assertIn(newest_source_old_output, removed)
            self.assertTrue(old_source_new_output.exists())
            self.assertTrue(
                (directory / "squads_20260801_010101_+0000_p90_20260802_010101_+0000.csv").exists()
            )
            self.assertTrue(
                (directory / "squads_20260801_010101_+0000_p80_20260802_010101_+0000.json").exists()
            )

    def test_expected_points_share_one_family_across_methods(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory) / "expected_points"
            files = [
                _write(directory, f"expected_points_source_method_a_{_compact_timestamp(index)}.csv")
                for index in range(6)
            ] + [
                _write(directory, f"expected_points_source_method_b_{_compact_timestamp(index + 6)}.csv")
                for index in range(6)
            ]

            removed = prune_timestamped_outputs(Path(temporary_directory))

            self.assertEqual(removed, files[:2])
            self.assertEqual([path for path in files if path.exists()], files[2:])

    def test_optimized_squads_share_one_family_across_methods(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory) / "optimized_squad"
            files = [
                _write(directory, f"optimized_squad_method_a_input_{_compact_timestamp(index)}.csv")
                for index in range(6)
            ] + [
                _write(directory, f"optimized_squad_method_b_input_{_compact_timestamp(index + 6)}.csv")
                for index in range(6)
            ]

            removed = prune_timestamped_outputs(Path(temporary_directory))

            self.assertEqual(removed, files[:2])
            self.assertEqual([path for path in files if path.exists()], files[2:])

    def test_supports_dashed_and_utc_timestamps_and_ignores_plain_files(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory) / "sofascore" / "team_stats"
            dashed = _write(directory, "stats_md_1_2026-08-18_20-39-16_299781+0200.csv")
            utc = _write(directory, "stats_md_2_20260817T173804Z.csv")
            plain = _write(directory, "match_ids_1.json")

            self.assertEqual(prune_timestamped_outputs(Path(temporary_directory)), [])
            self.assertTrue(dashed.exists())
            self.assertTrue(utc.exists())
            self.assertTrue(plain.exists())


if __name__ == "__main__":
    unittest.main()
