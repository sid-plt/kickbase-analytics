import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sofascore_metric_consistency import (
    Settings, analyze, classify, evidence, flatten_appearances, form_at_cutoff,
    match_metadata, metric_registry, select_form, qualification_audit,
)


@pytest.fixture
def history():
    # Deliberately reverse numeric IDs relative to kickoff ordering.
    matches = [dict(match_id=100-i, date=f'2026-09-{i+1:02}T12:00:00+00:00',
                    home_team_id=1, away_team_id=2, home_team='One', away_team='Two',
                    competition='League') for i in range(5)]
    players = []
    for player_id in range(1, 7):
        calculations = []
        for match in matches:
            awards = [dict(metric_id='minutes_bonus', points=20, confidence='direct', source='lineups'),
                      dict(metric_id='foul', points=-5, confidence='direct', source='lineups')]
            calculations.append(dict(match_id=match['match_id'], minutes_played=90,
                calculated_kickbase_points=15, awards=awards))
        players.append(dict(player_id=player_id, player_name=f'Player {player_id}', position='MID',
                            match_calculations=calculations))
    payload = dict(teams={'1': dict(team='One', overall=dict(players=players))}, failed_matches=[],
                   eligibility=dict(bundesliga_matchday=5))
    snapshot = {'1': dict(team='One', overall_matches=list(reversed(matches)))}
    catalog = json.loads((Path(__file__).parents[1] / 'data/reference/kickbase/kickbase_metrics.json').read_text(encoding='utf-8'))
    return payload, snapshot, catalog


def small_settings(**changes):
    return Settings(**dict(minimum_players=2, minimum_evaluations=3, **changes))


def test_aggregation_negative_zero_and_absence(history):
    payload, snapshot, catalog = history
    player = payload['teams']['1']['overall']['players'][0]
    player['match_calculations'].pop(1)  # Absent: no synthetic appearance.
    first = player['match_calculations'][0]
    first['awards'].append(dict(metric_id='foul', points=-5, confidence='proxy', source='other'))
    first['calculated_kickbase_points'] -= 5
    appearances, metrics, ledger, _ = flatten_appearances(payload, match_metadata(snapshot), metric_registry(catalog))
    assert len(appearances) == 29
    assert metrics.query('player_id == 1 and match_id == 100 and metric_id == "foul"').metric_points.iloc[0] == -10
    assert metrics.query('metric_id == "goal"').metric_points.eq(0).all()
    assert metrics.query('player_id == 1 and match_id == 99').empty
    assert set(ledger.query('metric_id == "foul"').confidence) == {'direct', 'proxy'}


def test_reconciliation_duplicates_and_failed_matches(history):
    p, s, c = history
    players = p['teams']['1']['overall']['players']
    players[0]['match_calculations'][0]['calculated_kickbase_points'] = 123
    with pytest.raises(ValueError, match='reconciliation'):
        flatten_appearances(p, match_metadata(s), metric_registry(c))
    players[0]['match_calculations'][0]['calculated_kickbase_points'] = 15
    p['failed_matches'] = [dict(team_id=1, match_id=100)]
    with pytest.raises(ValueError, match='failed match'):
        flatten_appearances(p, match_metadata(s), metric_registry(c))
    p['failed_matches'] = []
    players[0]['match_calculations'].append(copy.deepcopy(players[0]['match_calculations'][0]))
    with pytest.raises(ValueError, match='Duplicate appearance'):
        flatten_appearances(p, match_metadata(s), metric_registry(c))


def test_predictable_negative_metrics_and_chronology(history):
    r = analyze(*history, settings=small_settings())
    assert r['metadata'].match_id.tolist() == [100, 99, 98, 97, 96]
    scored = r['by_position'].query('metric_id in ["minutes_bonus", "foul"] and position == "MID"')
    assert scored.automatic_category.eq(1).all()
    assert scored.all_wape.eq(0).all()
    assert r['evaluations'].latest_history_kickoff.lt(r['evaluations'].kickoff).all()
    assert set(r['evaluations'].slot) == {4, 5}


def test_target_and_future_do_not_change_earlier_form_or_forecast(history):
    p, s, c = history
    before = analyze(p, s, c, small_settings())
    altered = copy.deepcopy(p)
    for player in altered['teams']['1']['overall']['players']:
        for match in player['match_calculations'][3:]:
            amount = player['player_id'] * 1000
            match['awards'].append(dict(metric_id='goal', points=amount, confidence='direct', source='incidents'))
            match['calculated_kickbase_points'] += amount
    after = analyze(altered, s, c, small_settings())
    keys = ['player_id', 'metric_id']
    left = before['evaluations'].query('slot == 4').sort_values(keys)
    right = after['evaluations'].query('slot == 4').sort_values(keys)
    for column in ['predicted_per_90', 'average_rating', 'in_form']:
        pd.testing.assert_series_equal(left[column].reset_index(drop=True), right[column].reset_index(drop=True))
    cutoff = before['metadata'].kickoff.iloc[3]
    pd.testing.assert_frame_equal(form_at_cutoff(p, before['metadata'], cutoff),
                                 form_at_cutoff(altered, before['metadata'], cutoff))


def test_rating_weights_preserve_absent_team_slot(history):
    p, s, _ = history
    p['teams']['1']['overall']['players'][0]['match_calculations'].pop(3)
    # Mock rating derivation to isolate recency averaging from percentile ties.
    from unittest.mock import patch
    ratings = pd.DataFrame([dict(team_id='1', team='One', player_id=1, player_name='A',
        position='MID', match_id=96, rating=10), dict(team_id='1', team='One', player_id=1,
        player_name='A', position='MID', match_id=98, rating=4)])
    with patch('sofascore_metric_consistency.derive_ratings', return_value=(ratings, {}, [])):
        result = form_at_cutoff(p, match_metadata(s))
    assert result.average_rating.iloc[0] == 7.5  # (28*10 + 20*4) / 48, not 28/24.


def test_cutoff_ties_and_position_selection():
    players = pd.DataFrame({'position': ['MID']*5 + ['GK']*2,
                            'average_rating': [10, 10, 8, 7, 6, 8, 6]})
    result = select_form(players, 20)
    assert result.in_form.tolist() == [True, True, False, False, False, True, False]
    assert select_form(players, 100).in_form.all()
    with pytest.raises(ValueError):
        select_form(players, 0)


def test_forecast_weights_preserve_absent_slots_and_short_form_history(history):
    p, s, c = history
    player = p['teams']['1']['overall']['players'][0]
    player['match_calculations'].pop(1)
    for match, points in zip(player['match_calculations'][:2], [10, 30]):
        match['awards'][0]['points'] = points
        match['calculated_kickbase_points'] = points - 5
    r = analyze(p, s, c, small_settings())
    forecast = r['evaluations'].query('player_id == 1 and slot == 4 and metric_id == "minutes_bonus"')
    assert forecast.predicted_per_90.iloc[0] == pytest.approx((28*30+20*10)/48)
    # Short appearances remain eligible for form but cannot supply forecast history.
    player['match_calculations'][0]['minutes_played'] = 15
    r = analyze(p, s, c, small_settings())
    assert r['current_form'].query('player_id == 1').rating_count.iloc[0] == 4
    assert r['evaluations'].query('player_id == 1 and slot == 4').empty
    assert not r['evaluations'].query('player_id == 1 and slot == 5').empty


def cases(actual, predicted, active=True):
    return pd.DataFrame(dict(team_id=['1']*len(actual), player_id=list(range(len(actual))),
        points_per_90=actual, metric_points=actual, absolute_error=np.abs(np.array(predicted)-actual),
        previously_active=[active]*len(actual)))


def test_volatile_zero_sparse_and_boundary_rules():
    settings = small_settings()
    stable = evidence(cases([20]*4, [20]*4), settings)
    volatile = evidence(cases([10, 100, 10, 100], [100, 10, 100, 10]), settings)
    zero = evidence(cases([0]*4, [0]*4, False), settings)
    sparse = evidence(cases([20], [20]), settings)
    assert classify(stable, stable)[0] == 1
    assert classify(volatile, stable)[0] == 2
    assert classify(volatile, volatile)[0] == 3
    assert classify(zero, zero)[0] == 3
    assert np.isnan(zero['wape']) and not zero['passed']
    assert classify(volatile, sparse)[:2] == (None, 'insufficient evidence')
    boundary = evidence(cases([20]*3, [5]*3), settings)
    assert boundary['wape'] == .75 and boundary['passed']


def test_overrides_supported_status_and_goalkeeper_calibration(history):
    p, s, c = history
    first = p['teams']['1']['overall']['players'][0]
    first['position'] = 'GK'
    for match in first['match_calculations']:
        match['goalkeeper_residual_estimate'] = dict(status='estimated', estimated_total=50)
    r = analyze(p, s, c, small_settings(), {('goal', 'MID'): 2})
    assert r['appearances'].query('position == "GK"').calibration_adjustment.eq(35).all()
    assert r['by_position'].query('metric_id == "goal" and position == "MID"').category.iloc[0] == 2
    assert r['by_position'].query('metric_id == "goal" and position == "GK"').evidence_status.iloc[0] == 'insufficient evidence'
    assert r['by_position'].query('metric_id == "secondary_assist"').evidence_status.eq('unsupported').all()
    with pytest.raises(ValueError, match='override'):
        analyze(p, s, c, small_settings(), {('box_shot_saved', 'MID'): 1})


def test_late_other_team_cannot_change_form(history):
    p, s, c = history
    meta = match_metadata(s)
    cutoff = meta.kickoff.iloc[3]
    old = form_at_cutoff(p, meta, cutoff)
    p = copy.deepcopy(p)
    s = copy.deepcopy(s)
    future = copy.deepcopy(p['teams']['1'])
    for player in future['overall']['players']:
        player['player_id'] += 100
        player['match_calculations'] = player['match_calculations'][4:]
        player['match_calculations'][0]['calculated_kickbase_points'] = 100000
    p['teams']['3'] = future
    s['3'] = copy.deepcopy(s['1'])
    pd.testing.assert_frame_equal(old, form_at_cutoff(p, match_metadata(s), cutoff))


def test_configuration_validation():
    for options in [dict(form_top_percent=0), dict(minimum_minutes=9),
                    dict(minimum_players=0), dict(minimum_nonzero=1.1), dict(maximum_wape=float('nan'))]:
        with pytest.raises(ValueError):
            Settings(**options)


@pytest.mark.parametrize('matchday,indices,minutes,position,expected', [
    (1, [0], 10, 'MID', True),
    (2, [0], 90, 'MID', False),
    (2, [4], 10, 'MID', True),
    (3, [0, 1], 10, 'MID', True),
    (4, [0, 1], 90, 'MID', False),
    (5, [0, 1, 2], 10, 'MID', True),
    (5, [3, 4], 10, 'MID', True),
    (5, [4], 45, 'MID', True),
    (5, [4], 44, 'MID', False),
    (5, [0], 90, 'GK', True),
    (34, [4], 0, 'GK', True),
])
def test_shared_matchday_qualification_routes(history, matchday, indices, minutes, position, expected):
    p, s, _ = history
    player = p['teams']['1']['overall']['players'][0]
    player['match_calculations'] = [player['match_calculations'][i] for i in indices]
    player['position'] = position
    for match in player['match_calculations']:
        match['minutes_played'] = minutes
    audit = qualification_audit(p, match_metadata(s), matchday)
    row = audit.query('player_id == 1').iloc[0]
    assert bool(row.qualified) is expected
    assert row.recorded_appearances == len(indices)


def test_future_qualification_cannot_admit_a_pre_match_forecast(history):
    p, s, c = history
    player = p['teams']['1']['overall']['players'][0]
    player['match_calculations'] = [player['match_calculations'][i] for i in [0, 1, 4]]
    result = analyze(p, s, c, small_settings())
    assert result['qualification'].query('player_id == 1').qualified.iloc[0]
    # Two older matches do not satisfy MD5 minimum or latest-match exceptions
    # before slot 5. The target appearance must not qualify the player retroactively.
    assert result['evaluations'].query('player_id == 1').empty
    cutoff = result['metadata'].kickoff.iloc[4]
    audit = qualification_audit(p, result['metadata'], cutoff=cutoff)
    assert not audit.query('player_id == 1').qualified.iloc[0]


def test_matchday_override_filters_current_population_and_validates_source(history):
    p, s, c = history
    player = p['teams']['1']['overall']['players'][0]
    player['match_calculations'] = player['match_calculations'][:2]
    result = analyze(p, s, c, small_settings())
    assert result['coverage']['players_excluded_by_matchday_qualification'] == 1
    assert result['appearances'].query('player_id == 1').empty
    earlier_regime = analyze(p, s, c, small_settings(bundesliga_matchday=3))
    assert not earlier_regime['appearances'].query('player_id == 1').empty
    del p['eligibility']
    with pytest.raises(ValueError, match='Source has no Bundesliga matchday'):
        analyze(p, s, c)
    for value in [0, 35, True, '5']:
        with pytest.raises(ValueError, match='Bundesliga matchday'):
            Settings(bundesliga_matchday=value)


def test_qualification_and_form_normalize_goalkeeper_position_alias(history):
    p, s, c = history
    p['teams']['1']['overall']['players'][0]['position'] = 'G'
    result = analyze(p, s, c, small_settings())
    assert result['qualification'].query('player_id == 1').position.iloc[0] == 'GK'
    assert result['current_form'].query('player_id == 1').position.iloc[0] == 'GK'
