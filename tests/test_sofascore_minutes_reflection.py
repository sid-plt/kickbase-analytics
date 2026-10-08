"""Exercise notebook transformations and execute its cells with local exports."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

NOTEBOOK = Path(__file__).resolve().parents[1] / 'notebooks/09_reflection/03_sofascore_kickbase_points_by_minutes.ipynb'


def definitions():
    cells = json.loads(NOTEBOOK.read_text(encoding='utf-8'))['cells']
    namespace = {}
    exec(''.join(next(c for c in cells if c['cell_type'] == 'code')['source']), namespace)
    return namespace


def test_boundaries_exclusions_and_percentiles():
    ns = definitions()
    frame = pd.DataFrame({'minutes': [9, 10, 25, 50, 75, 90, 120, None, np.inf, 20],
                          'points': [0, -10, 0, 20, 30, 40, 50, 60, 70, np.nan]})
    grouped, counts = ns['group_appearances'](frame)
    assert list(grouped['group'].astype(str)) == [*ns['GROUPS'], '75+ min', '75+ min']
    assert counts == {'source': 10, 'invalid points/minutes': 3, 'below 10 minutes': 1, 'included': 6}
    table = ns['percentile_table'](grouped)
    assert table.loc['P10', '75+ min'] == 32
    assert table.loc['P90', '75+ min'] == 48
    assert (table['10–25 min'] == -10).all()
    empty = ns['percentile_table'](grouped.iloc[:0])
    assert empty.shape == (11, 4) and empty.isna().all().all()


def test_metadata_fallback_missing_ratings_and_duplicates():
    ns = definitions()
    appearances = pd.DataFrame([dict(team_id='1', player_id=2, match_id=3, minutes=95, points=-5)])
    primary = pd.DataFrame([dict(team_id='1', match_id=3, fixture='Primary fixture', date=None)])
    fallback = pd.DataFrame([dict(team_id='1', match_id=3, fixture='Fallback fixture', date='2026-09-01')])
    ratings = pd.DataFrame(columns=ns['KEYS'] + ['rating'])
    merged = ns['attach_details'](appearances, ratings, primary, fallback)
    assert len(merged) == 1 and pd.isna(merged.iloc[0].rating)
    assert merged.iloc[0].fixture == 'Primary fixture'
    assert merged.iloc[0].date == '2026-09-01'
    payload = {'teams': {'1': {'overall': {'players': [{'player_id': 2, 'match_calculations': [{'match_id': 3}, {'match_id': 3}]}]}}}}
    with pytest.raises(ValueError, match='Duplicate'):
        ns['flatten'](payload)


def test_latest_uses_generated_at(tmp_path):
    ns = definitions()
    for name, stamp in [('z.json', '2026-09-01T10:00:00Z'), ('a.json', '2026-09-02T10:00:00Z')]:
        (tmp_path / name).write_text(json.dumps({'generated_at': stamp}), encoding='utf-8')
    assert ns['latest_recording'](tmp_path, '*.json')[0].name == 'a.json'


def test_execute_notebook_and_hover(monkeypatch):
    figures = []
    monkeypatch.setattr(go.Figure, 'show', lambda figure: figures.append(figure))
    namespace = {}
    for cell in json.loads(NOTEBOOK.read_text(encoding='utf-8'))['cells']:
        if cell['cell_type'] == 'code':
            exec(''.join(cell['source']), namespace)
    assert len(figures) == 7
    for trace in figures[-1].data:
        assert list(trace.x) == list(range(0, 101, 10))
        np.testing.assert_allclose(trace.y, namespace['percentiles'][trace.name], equal_nan=True)
    data = namespace['data']
    assert len(data) == namespace['exclusion_counts']['included']
    assert namespace['sample_counts'].sum() == len(data)
    assert namespace['percentiles'].shape == (11, 4)
    for figure in figures:
        assert '<html>' in figure.to_html(include_plotlyjs=True)
    for figure in figures[:2]:
        assert sum(len(trace.y) for trace in figure.data) == len(data)
        for trace in figure.data:
            assert 'SofaScore rating' in trace.hovertemplate
            if len(trace.y):
                hover = trace.customdata[0]
                source = data.loc[(data.match_id == hover[4]) & (data.player_name == hover[0])].iloc[0]
                assert hover[5] == source.rating_hover
                assert hover[2] == source.fixture
    for group, counts in namespace['hist_counts'].items():
        assert counts.sum() == namespace['sample_counts'][group]
