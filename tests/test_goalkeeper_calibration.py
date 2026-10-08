import copy
from collections import Counter
import json
from pathlib import Path

from goalkeeper_kickbase_calibration import estimate_for_match, load_model, policy_fingerprint, points_for_averages
from sofascore_kickbase_points import MetricCatalog, score_from_match, scoring_policy, evaluate_overall_team

ROOT = Path(__file__).resolve().parents[1]


def keeper_fixture():
    # Reduced from user-supplied match 16434037 responses (Noll, MD3).
    stats = dict(minutesPlayed=90, savedShotsFromInsideTheBox=4, saves=5,
                 punches=3, totalKeeperSweeper=2, accurateKeeperSweeper=2)
    lineups = {'home': {'players': []}, 'away': {'players': [
        dict(player=dict(id=1048651, name='Nahuel Noll'), teamId=2561, position='G', substitute=False, statistics=stats)]}}
    shots = [dict(shotType='save', goalkeeper=dict(id=1048651),
                  playerCoordinates=dict(x=x, y=y), xg=xg)
             for x, y, xg in [(12.2, 38.2, .4316), (10.2, 58.1, .2927),
                              (9.4, 60.7, .1634), (7, 49.5, .1393), (18.2, 61.3, .0490)]]
    match = dict(match_id=16434037, home_team_id=2673, away_team_id=2561,
                 unique_tournament_id=35, date='2026-09-12T13:30:00+00:00')
    return match, lineups, shots


def run_keeper(lineups=None, shots=None):
    match, default_lineups, default_shots = keeper_fixture()
    catalog = MetricCatalog.from_document(json.loads((ROOT / 'data/reference/kickbase/kickbase_metrics.json').read_text(encoding='utf-8')))
    return score_from_match(match, lineups or default_lineups, {'incidents': []},
                            {'shotmap': default_shots if shots is None else shots}, catalog)['players'][0]


def points(player, metric):
    return sum(a['points'] for a in player['awards'] if a['metric_id'] == metric)


def test_real_noll_counts_and_no_inferred_save_technique():
    player = run_keeper()
    assert points(player, 'keeper_sweeper') == 20
    assert points(player, 'box_shot_saved') == 40
    assert points(player, 'distance_shot_saved') == 5
    assert points(player, 'punched_ball') == 15
    assert points(player, 'big_chance_saved') == 0  # high xG isn't a label
    assert not {'dive_save', 'dive_catch', 'standing_saved'} & {a['metric_id'] for a in player['awards']}
    assert player['goalkeeper_statistics']['accurateKeeperSweeper'] == 2
    assert sum(a['points'] for a in player['awards']) == player['calculated_kickbase_points']


def test_sweeper_successes_only_missing_zero_and_outfield():
    _, lineups, _ = keeper_fixture()
    stats = lineups['away']['players'][0]['statistics']
    stats['totalKeeperSweeper'] = 9
    stats['accurateKeeperSweeper'] = 1
    assert points(run_keeper(lineups), 'keeper_sweeper') == 10
    stats['accurateKeeperSweeper'] = 0
    assert points(run_keeper(lineups), 'keeper_sweeper') == 0
    del stats['accurateKeeperSweeper']
    assert points(run_keeper(lineups), 'keeper_sweeper') == 0
    stats['accurateKeeperSweeper'] = 2
    lineups['away']['players'][0]['position'] = 'D'
    assert points(run_keeper(lineups), 'keeper_sweeper') == 0


def test_save_aggregate_overrides_shotmap_and_big_chance_deduplicates():
    _, lineups, shots = keeper_fixture()
    stats = lineups['away']['players'][0]['statistics']
    stats.update(savedShotsFromOutsideTheBox=0, bigChanceSaved=1)
    for shot in shots:
        shot['bigChance'] = True
    player = run_keeper(lineups, shots)
    assert points(player, 'box_shot_saved') == 40
    assert points(player, 'distance_shot_saved') == 0
    assert points(player, 'big_chance_saved') == 15


def test_supplemental_estimate_does_not_stack_sweeper_or_mutate_awards():
    model = load_model()
    match, _, _ = keeper_fixture()
    player = run_keeper()
    player['calculated_kickbase_points'] = 95  # full saved ledger + two sweeper awards
    before = copy.deepcopy(player)
    estimate = estimate_for_match(player, match, scoring_policy(), model)
    assert estimate['status'] == 'estimated'
    assert estimate['legacy_residual_allowance'] == 54
    assert estimate['already_mapped_points'] == 20
    assert estimate['points'] == 34
    assert estimate['estimated_total'] == 129
    assert player == before
    player['awards'].append(dict(metric_id='keeper_sweeper', count=4, points=40))
    assert estimate_for_match(player, match, scoring_policy(), model)['points'] == 0


def test_estimate_rejects_training_dates_other_leagues_partial_games_and_rule_changes():
    model = load_model()
    match, _, _ = keeper_fixture()
    player = run_keeper()
    for change in [dict(date=model['training_through']), dict(unique_tournament_id=7),
                   dict(date='2028-01-01T12:00:00+00:00')]:
        result = estimate_for_match(player, {**match, **change}, scoring_policy(), model)
        assert result['points'] is None
    player['minutes_played'] = 45
    assert estimate_for_match(player, match, scoring_policy(), model)['status'] == 'outside_training_range'
    changed_policy = {**scoring_policy(), 'new_award': 15}
    assert estimate_for_match(player, match, changed_policy, model)['status'] == 'scoring_policy_changed'


def test_model_policy_and_training_partition():
    model = load_model()
    assert model['scoring_policy_sha256'] == policy_fingerprint(scoring_policy())
    assert model['training_matchdays'] == [1, 2]
    assert model['validation_matchday'] == 3
    assert model['training_rows'] == 34
    assert model['validation']['corrected']['mae'] < model['validation']['training_mean_baseline']['mae']


def test_workflow_preserves_raw_stats_and_separate_estimate():
    match, lineups, shots = keeper_fixture()
    catalog = MetricCatalog.from_document(json.loads((ROOT / 'data/reference/kickbase/kickbase_metrics.json').read_text(encoding='utf-8')))
    cache = {match['match_id']: dict(ok=True, payloads=dict(lineups=lineups, incidents={'incidents': []}, shotmap={'shotmap': shots}))}
    failures = []
    players = evaluate_overall_team(None, 2561, 'SC Paderborn 07', [match], 1,
                                   catalog, cache, {}, Counter(), failures, goalkeeper_model=load_model())
    assert not failures
    calculation = players[0]['match_calculations'][0]
    assert calculation['goalkeeper_statistics']['accurateKeeperSweeper'] == 2
    assert calculation['goalkeeper_residual_estimate']['points'] == 34
    assert calculation['calculated_kickbase_points'] == sum(a['points'] for a in calculation['awards'])
    assert players[0]['average_calculated_kickbase_points'] == calculation['goalkeeper_residual_estimate']['estimated_total']


def test_average_points_only_uses_valid_goalkeeper_estimates():
    record = dict(calculated_kickbase_points=95,
                  goalkeeper_residual_estimate=dict(status='estimated', estimated_total=129))
    assert points_for_averages(record, 'GK') == 129
    for position in ['DEF', 'MID', 'FWD', 'D', 'M', 'F', None]:
        assert points_for_averages(record, position) == 95
    for total in [None, True, float('nan'), float('inf'), '129']:
        record['goalkeeper_residual_estimate']['estimated_total'] = total
        assert points_for_averages(record, 'GK') == 95
    record['goalkeeper_residual_estimate'] = dict(status='outside_training_range', estimated_total=129)
    assert points_for_averages(record, 'GK') == 95
    assert points_for_averages({'calculated_kickbase_points': 95}, 'GK') == 95
