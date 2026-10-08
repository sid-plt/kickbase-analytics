import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import sofascore_kickbase_percentile_ratings as ratings
import sofascore_rating_odds_lineup_score as shared


def test_goalkeeper_estimate_changes_percentile_input_only_for_keepers():
    def player(identifier, position, base, estimate):
        return dict(player_id=identifier, player_name=str(identifier), position=position,
                    match_calculations=[dict(match_id=1, minutes_played=90,
                        calculated_kickbase_points=base, goalkeeper_residual_estimate=estimate)])
    data = {'teams': {'1': {'team': 'Team', 'overall': {'players': [
        player(1, 'GK', 95, dict(status='estimated', estimated_total=129)),
        player(2, 'MID', 110, dict(status='estimated', estimated_total=999)),
        player(3, 'GK', 100, dict(status='outside_training_range', estimated_total=None)),
    ]}}}}
    frame, _, _ = ratings.derive_ratings(data)
    assert frame.points.tolist() == [129, 110, 100]
    assert frame.percentile.tolist() == [100, 50, 0]


def payload(records):
    return dict(generated_at='2026-09-16T12:00:00Z', source_file='form.json',
                teams={'1': {'team': 'Team', 'overall': {'players': [
                    dict(player_id=1, player_name='Player', position='M', match_calculations=records)]}}})


def record(identifier, minutes, points):
    return dict(match_id=identifier, minutes_played=minutes, calculated_kickbase_points=points)


def test_groups_exclusions_ties_and_rounding():
    source = payload([record(i, minutes, points) for i, (minutes, points) in enumerate([
        (10, -10), (24, -10), (20, 0), (20, 10), (25, 0), (50, 0), (75, -5),
        (90, 5), (120, 15), (9, 10), (None, 1), (20, float('inf'))])])
    with pytest.warns(UserWarning, match='RATING FALLBACK'):
        frame, counts, flags = ratings.derive_ratings(source)
    assert frame.group.tolist() == [ratings.GROUPS[0]] * 4 + ratings.GROUPS[1:3] + [ratings.GROUPS[3]] * 3
    assert frame.rating.tolist() == [3.5, 3.5, 7.4, 10, 6.8, 6.8, 3.5, 6.8, 10]
    assert counts == dict(source=12, invalid_points_or_minutes=2, below_10_minutes=1, included=9)
    assert len(flags) == 2
    assert ratings.rounded(6.75) == 6.8
    for _, group in frame.groupby('group'):
        assert group.sort_values('points').rating.is_monotonic_increasing
    with pytest.raises(ValueError, match='Duplicate'):
        ratings.derive_ratings(payload([record(1, 90, 10)] * 2))


def test_export_flags_weighting_and_latest(tmp_path):
    source = tmp_path / 'points.json'
    source.write_text(json.dumps(payload([record(1, 90, 10), record(3, 90, 10)])))
    (tmp_path / 'form.json').write_text(json.dumps({'1': {'overall_matches': [
        dict(match_id=1, timestamp=399, home_team_id=1, away_team_id=2, home_team='Team', away_team='Away opponent'),
        dict(match_id=3, timestamp=397, home_team_id=3, away_team_id=1, home_team='Home opponent', away_team='Team')]}}))
    with pytest.warns(UserWarning, match='all_tied'):
        result = ratings.export_ratings(source, tmp_path / 'derived', tmp_path)
    document = result['document']
    assert document['fallback_flags'][0]['fallback_rating'] == 6.8
    assert pd.read_csv(result['csv_path']).average_rating.tolist() == [6.8]
    trail = document['teams']['1']['overall']['players'][0]['ratings']
    assert [match['opponent'] for match in trail] == ['Away opponent', 'Home opponent']
    trail[0]['rating'], trail[1]['rating'] = 10, 3.5
    result['json_path'].write_text(json.dumps(document))
    (tmp_path / 'form.json').write_text(json.dumps({'1': {'overall_matches': [
        dict(match_id=i, timestamp=400-i) for i in range(1, 6)]}}))
    with pytest.warns(UserWarning, match='all_tied'):
        weighted = ratings.load_weighted_ratings(result['json_path'], tmp_path)
    assert weighted.average_rating.tolist() == [7.3]  # (10*28 + 3.5*20)/48, no slot shifting
    assert ratings.latest_json(tmp_path / 'derived', '*.json') == result['json_path']
    older = tmp_path / 'derived' / 'zzz.json'
    older.write_text(json.dumps({'generated_at': '2000-01-01T00:00:00Z'}))
    assert ratings.latest_json(tmp_path / 'derived', '*.json') == result['json_path']


def test_export_uses_chronology_and_preserves_missing_slots(tmp_path):
    source = tmp_path / 'points.json'
    # Input order is deliberately oldest first, with the second-newest slot absent.
    source.write_text(json.dumps(payload([record(3, 90, 0), record(1, 90, 100)])))
    (tmp_path / 'form.json').write_text(json.dumps({'1': {'overall_matches': [
        dict(match_id=i, timestamp=400-i, home_team_id=1, away_team_id=2,
             home_team='Team', away_team='Opponent') for i in [3, 1, 2]]}}))
    result = ratings.export_ratings(source, tmp_path / 'derived', tmp_path)
    player = result['document']['teams']['1']['overall']['players'][0]
    # (3.5 * 20 + 10 * 28) / 48 = 7.2917, rather than unweighted 6.8.
    assert player['average_rating'] == 7.3
    assert pd.read_csv(result['csv_path']).average_rating.tolist() == [7.3]
    assert ratings.load_weighted_ratings(result['json_path'], tmp_path).average_rating.tolist() == [7.3]
    assert result['document']['averaging_policy']['newest_first_weights'] == [28, 24, 20, 16, 12]


@pytest.mark.parametrize('position', [1, 2])
def test_shared_score_formula_and_adapter(tmp_path, monkeypatch, position):
    players = pd.DataFrame([dict(id=1, name='Player', teamId=2, position=position)])
    values = pd.DataFrame([dict(player_id=1, player_name='Player', average_rating=7.3)])
    monkeypatch.setattr(ratings, 'latest_json', lambda *args: Path('derived.json'))
    monkeypatch.setattr(ratings, 'load_weighted_ratings', lambda path: values)
    replacements = dict(
        request_matchday=lambda: 4,
        select_latest_kbstats_csv=lambda: SimpleNamespace(path=Path('players.csv'), timestamp_text='test'),
        load_kbstats_players=lambda path: players,
        load_expected_match_points=lambda day: ({'bayern': 2.5}, pd.DataFrame()),
        load_lineup_source=lambda source, *args, **kwargs: (Path(source.key + '.json'), {'bayern': {
            shared.normalize_name('Player'): dict(name='Player', id=1, chance=0.8)}}),
        _load_lineup_overrides=lambda: pd.DataFrame(),
        _load_name_only_lineup_overrides=lambda: pd.DataFrame(),
        load_rating_overrides=lambda: pd.DataFrame(),
        display=lambda value: None,
        prune_timestamped_outputs=lambda: None,
    )
    for name, value in replacements.items():
        monkeypatch.setattr(shared, name, value)
    monkeypatch.setattr(shared, 'EXPECTED_POINTS_DIR', tmp_path)
    monkeypatch.setattr('builtins.input', lambda prompt: 'y')
    result = ratings.run_score_creation()
    exported = pd.read_csv(result['output_path'])
    assert exported.kickbase_percentile_rating.tolist() == [7.3]
    match_points = 1.1 + 2.5 * (0.6 / 3) if position == 1 else 2.5
    assert exported.expected_match_points.iloc[0] == pytest.approx(match_points)
    assert exported.score.iloc[0] == pytest.approx(round(10.0062 * 7.3 * match_points * 0.8, 6))
    assert ratings.OUTPUT_LABEL in result['output_path'].name
    assert 'sofascore_average_rating' not in exported


@pytest.mark.parametrize('raw,expected', [(0, 1.1), (1.5, 1.4), (3, 1.7)])
def test_goalkeeper_expected_match_points_scale(raw, expected):
    assert shared.player_expected_match_points(raw, True) == pytest.approx(expected)
    assert shared.player_expected_match_points(raw, False) == raw
