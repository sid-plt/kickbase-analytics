"""Rebuild the reflection notebook source; execution is a separate step."""
from pathlib import Path
import textwrap
import sys
import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
cells = []


def markdown(source):
    cells.append(nbf.v4.new_markdown_cell(textwrap.dedent(source).strip()))


def code(source):
    cells.append(nbf.v4.new_code_cell(textwrap.dedent(source).strip()))


markdown('''
    # SofaScore-derived Kickbase metric consistency

    Which point contributions repeat across each team's **last five matches across
    competitions**, and which should inform a next-match prediction?

    **1 — Generally consistent**; **2 — Consistent for in-form players**;
    **3 — Volatile: exclude from this prediction approach**.
    Grey cells mean **unclassified**, not proven volatility. These are exploratory
    classifications within a short window, conditional on players already included
    by the source export's eligibility rules. They do not change any prediction model.

    Form uses the existing minute-group Kickbase percentile ratings, goalkeeper
    calibration where available, and recency weights **28/24/20/16/12**. Top 20% is
    selected **within each position**, including cutoff ties. Current form tables are
    descriptive. Predictive classifications use form recomputed **strictly before
    each target kickoff**, including the percentile comparison population.
''')
code('''
    import sys
    import json
    from pathlib import Path
    from dataclasses import asdict
    import numpy as np
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go
    import plotly.io as pio
    from plotly.subplots import make_subplots
    from IPython.display import display, HTML, Markdown

    PROJECT_ROOT = next((p for p in (Path.cwd(), *Path.cwd().parents)
                         if (p / 'project_paths.py').is_file()), None)
    if PROJECT_ROOT is None:
        raise FileNotFoundError('Run this notebook from within the project directory.')
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from sofascore_metric_consistency import Settings, LABELS, load_inputs, analyze

    pio.templates.default = 'plotly_white'
    _plotly_loaded = False
    def show_figure(fig):
        # Save both native Plotly MIME and HTML with the JS library embedded once.
        # All plots and dropdowns work without a CDN or widget kernel connection.
        global _plotly_loaded
        html = pio.to_html(fig, include_plotlyjs=not _plotly_loaded,
                           full_html=False, config={'displaylogo': False, 'responsive': True})
        _plotly_loaded = True
        display({'text/html': html, 'application/vnd.plotly.v1+json': json.loads(fig.to_json())}, raw=True)

    pd.set_option('display.max_colwidth', None)
    pd.set_option('display.max_rows', None)
''')
markdown('''
    ## Editable configuration

    Leave `SOURCE_FILE` as `None` to use the latest points export. An explicit path
    pins a run. Adjust thresholds and rerun all cells. `MANUAL_OVERRIDES` maps
    `(metric_id, position)` to category `1`, `2` or `3`; automatic decisions and
    evidence status stay visible. Overrides express judgement, not additional evidence.
''')
code('''
    SOURCE_FILE = None
    BUNDESLIGA_MATCHDAY = None  # None: use the source export's matchday; override with 1–34.
    FORM_TOP_PERCENT = 20
    MINIMUM_MINUTES = 45
    MINIMUM_HISTORY = 2
    MINIMUM_PLAYERS = 20
    MINIMUM_EVALUATIONS = 30
    MINIMUM_NONZERO = 0.20
    MINIMUM_RECURRENCE = 0.60
    MAXIMUM_WAPE = 0.75
    MANUAL_OVERRIDES = {}  # Example: {('goal', 'FWD'): 3}
    DETAIL_PLAYERS = 8

    settings = Settings(bundesliga_matchday=BUNDESLIGA_MATCHDAY,
        form_top_percent=FORM_TOP_PERCENT, minimum_minutes=MINIMUM_MINUTES,
        minimum_history=MINIMUM_HISTORY, minimum_players=MINIMUM_PLAYERS,
        minimum_evaluations=MINIMUM_EVALUATIONS, minimum_nonzero=MINIMUM_NONZERO,
        minimum_recurrence=MINIMUM_RECURRENCE, maximum_wape=MAXIMUM_WAPE)
    payload, snapshot, catalog, provenance = load_inputs(SOURCE_FILE)
    result = analyze(payload, snapshot, catalog, settings, MANUAL_OVERRIDES)
    appearances = result['appearances']
    metrics = result['metrics']
    evaluations = result['evaluations']
    positions = result['by_position']
    overall = result['overall']
    current_form = result['current_form']
    metadata = result['metadata']
    display(pd.Series({k: v for k, v in provenance.items()
                       if k not in ('scoring_policy', 'failed_matches', 'eligibility')}, name='Source'))
    display(pd.Series(asdict(settings), name='Applied configuration'))
    display(pd.Series(result['coverage'], name='Coverage'))
    display(Markdown('**Source eligibility:** `' + json.dumps(provenance['eligibility']) + '`'))
    if provenance['failed_matches']:
        display(Markdown('**Failed source entries — excluded, never filled with zeros:**'))
        display(pd.DataFrame(provenance['failed_matches']))
''')
markdown('''
    ## Minimum matchday qualification

    This notebook also applies the shared player qualification rules used by the
    derived Kickbase export:

    | Bundesliga matchday | Minimum appearances | Alternative qualification |
    |---|---:|---|
    | 1 | 1 | — |
    | 2–3 | 2 | An appearance in the latest available team match |
    | 4–34 | 3 | Appearances in both latest available team matches, or 45+ minutes in the latest one |
    | Goalkeepers, any matchday | 1 | One recorded appearance in the sampled history |

    Qualification counts recorded appearances **before** applying the separate
    10-minute rating or configurable consistency-minute filters. A player meeting
    an exception can qualify with fewer than the standard minimum appearances.

    `BUNDESLIGA_MATCHDAY = None` reads the source export's matchday. The selected
    matchday regime is applied at each pre-match cutoff using **only earlier matches**;
    mixed-competition team slots do not reveal historical Bundesliga round numbers.
    This is a consistent qualification policy, not a reconstruction of past rounds.
    Minimum forecast history remains an additional requirement. The source has already
    removed some players, so lowering qualification here cannot recover those players.
''')
code('''
    qualification = result['qualification']
    display(pd.Series(result['qualification_policy'], name='Applied matchday qualification'))
    display(qualification.groupby(['position', 'qualified', 'qualification_route']).size()
        .rename('Players').to_frame())
    display(qualification[['player_name', 'team', 'position', 'recorded_appearances',
        'minimum_appearances', 'latest_match_minutes', 'qualified', 'qualification_route']])
    if not evaluations.empty:
        assert evaluations.matchday_qualified.all()
        display(evaluations[['team_id', 'player_id', 'match_id', 'kickoff', 'position',
            'history_count', 'matchday_qualified']].drop_duplicates()
            .groupby('position').size().rename('Qualified pre-match checks').to_frame())
''')
markdown('''
    ## Match window and reconciliation

    Slots 1–5 mean oldest to newest in **each team's own history**, not shared league
    rounds. The forecast checks use slots 4 and 5; a team with fewer than four slots
    has no target check. A missing appearance stays missing. A missing metric award
    becomes zero only within a valid, recorded appearance for an applicable position.

    Metric awards must sum to raw event-derived match points. Goalkeeper calibration
    changes form-rating totals, but its adjustment is kept separate from metric awards.
''')
code('''
    window = metadata.copy()
    window['date_Berlin'] = window.kickoff.dt.tz_convert('Europe/Berlin').dt.strftime('%Y-%m-%d %H:%M')
    display(window[['team', 'slot', 'date_Berlin', 'opponent', 'competition', 'match_id']])
    assert np.allclose(appearances.award_total, appearances.raw_points)
    display(appearances.groupby('position').agg(appearances=('match_id', 'size'),
        raw_points=('raw_points', 'sum'), award_points=('award_total', 'sum'),
        calibration_adjustment=('calibration_adjustment', 'sum')))
    gk_adjustments = appearances.loc[appearances.position == 'GK',
        ['player_name', 'kickoff', 'opponent', 'raw_points', 'rating_points', 'calibration_adjustment']]
    display(gk_adjustments)
''')
markdown('''
    ## Current in-form players

    The full-window, recency-weighted percentile rating is ranked within position
    after the minimum matchday qualification rules above.
    `ceil(position population × FORM_TOP_PERCENT / 100)` determines the cutoff;
    ties can increase the selected proportion. Players need at least one valid
    appearance of 10+ minutes for this descriptive table; pre-match form checks
    require both pre-match matchday qualification and at least `MINIMUM_HISTORY`
    earlier appearances of 10+ minutes.
''')
code('''
    form_sizes = current_form.groupby('position').agg(eligible_players=('player_id', 'size'),
        selected=('in_form', 'sum'), rating_cutoff=('form_cutoff', 'first'))
    form_sizes['selected_percent'] = 100 * form_sizes.selected / form_sizes.eligible_players
    display(form_sizes)
    for position in ['GK', 'DEF', 'MID', 'FWD']:
        display(Markdown(f'### {position}'))
        display(current_form.loc[(current_form.position == position) & current_form.in_form,
            ['player_name', 'team', 'rating_count', 'average_rating']]
            .sort_values('average_rating', ascending=False).reset_index(drop=True))
''')
markdown('''
    ## Metric-by-metric examination

    Each check forecasts **points per 90** from the same player's earlier qualifying
    appearances, weighted by team match slots. Weights are renormalised over available
    appearances without moving absent slots. Form ranking excludes all matches at or
    after the target kickoff, including other teams' matches.

    **WAPE** = sum of absolute forecast errors / sum of absolute observed points.
    A zero denominator gives no evidence of consistency. **Recurrence** is the share
    of nonzero target contributions among checks where the player had any earlier
    nonzero contribution. Negative points retain their sign in forecasts.

    A cohort passes only if it meets **all** configured sample, nonzero-frequency,
    recurrence and WAPE thresholds. Category 1 takes precedence over category 2.
    Category 3 requires adequate evidence in both cohorts and neither passing.
    Small cohorts stay unclassified; the default 20-player/30-check rule can make
    position-specific form cohorts too small in a five-match window.

    Overall category 1 requires every applicable position to pass for all players;
    overall category 2 requires every applicable position's form cohort to pass.
    Applicability follows catalog rules and the scorer's implementation. Catalog-only
    metrics remain unsupported. Spatial alternatives are reported through their emitted
    proxy family, avoiding double counting. Statistical stability of a proxy does not
    establish its accuracy against official Kickbase points.
''')
code('''
    display(Markdown('### Overall classification'))
    display(overall[['metric_id', 'classification', 'evidence_status', 'position_details', 'confidence']])
    display(Markdown('### Position-specific decisions and evidence'))
    decision_columns = ['metric_id', 'position', 'automatic_category', 'category', 'overridden',
        'classification', 'evidence_status', 'all_players', 'all_evaluations',
        'all_nonzero_frequency', 'all_recurrence', 'all_wape', 'form_players',
        'form_evaluations', 'form_nonzero_frequency', 'form_recurrence', 'form_wape', 'reason']
    display(positions.loc[positions.supported, decision_columns].round(3))
    display(Markdown('### Descriptive contribution and within-player variation'))
    descriptive_columns = ['metric_id', 'position', 'appearances', 'players', 'nonzero_frequency',
        'mean_points', 'median_points', 'std_points', 'mean_per_90', 'median_per_90',
        'iqr_per_90', 'median_within_player_cv', 'within_player_samples', 'confidence']
    display(positions.loc[positions.supported, descriptive_columns].round(3))
    display(Markdown('Within-player CV = population standard deviation / mean absolute points per 90; '
        'only players with 3+ appearances and 2+ nonzero contributions contribute. Zero-only players '
        'cannot make this diagnostic look stable. It is descriptive, not an extra classification threshold.'))
    display(Markdown('### Catalog metrics not independently emitted'))
    display(positions.loc[~positions.supported, ['metric_id', 'implementation']].drop_duplicates())
''')
code('''
    heat = positions.loc[positions.supported].copy()
    metric_order = sorted(heat.metric_id.unique())
    order = ['GK', 'DEF', 'MID', 'FWD']
    values = heat.pivot(index='metric_id', columns='position', values='category').reindex(index=metric_order, columns=order)
    reasons = heat.pivot(index='metric_id', columns='position', values='reason').reindex(index=metric_order, columns=order)
    statuses = heat.pivot(index='metric_id', columns='position', values='evidence_status').reindex(index=metric_order, columns=order)
    text = values.copy().astype(object)
    for metric in metric_order:
        for position in order:
            value = values.loc[metric, position]
            text.loc[metric, position] = 'N/A' if pd.isna(statuses.loc[metric, position]) else ('?' if pd.isna(value) else str(int(value)))
    fig = go.Figure(go.Heatmap(x=order, y=metric_order, z=values.fillna(0).values,
        text=text.values, texttemplate='%{text}', customdata=reasons.fillna('Not applicable').values,
        hovertemplate='%{y} / %{x}<br>%{customdata}<extra></extra>', zmin=0, zmax=3,
        colorscale=[[0, '#e2e8f0'], [.1666, '#e2e8f0'], [.1667, '#16a34a'], [.4999, '#16a34a'],
                    [.5, '#f59e0b'], [.8332, '#f59e0b'], [.8333, '#ef4444'], [1, '#ef4444']],
        colorbar=dict(tickvals=[0, 1, 2, 3], ticktext=['Unclassified / N/A', '1: General', '2: In form', '3: Volatile'])))
    fig.update_layout(title='Metric consistency by position — ? means insufficient evidence',
        height=max(900, len(metric_order)*24), margin=dict(l=240))
    show_figure(fig)
''')
markdown('''
    ## Contributions, distributions and match-slot trends

    These charts compare the **current** full-window form cohort with all available
    players. They describe the window; the classification above uses separate pre-match
    form cohorts. Hover to see metric, position and contribution details.
''')
code('''
    descriptive = metrics.loc[metrics.minutes_played >= MINIMUM_MINUTES].merge(
        current_form[['team_id', 'player_id', 'in_form']], on=['team_id', 'player_id'],
        how='left', validate='many_to_one')
    all_rows = descriptive.assign(cohort='All players')
    form_rows = descriptive.loc[descriptive.in_form.fillna(False)].assign(cohort='Current in form')
    comparison = pd.concat([all_rows, form_rows], ignore_index=True)
    contribution_order = descriptive.groupby('metric_id').metric_points.apply(lambda s: s.abs().sum()).sort_values(ascending=False).index.tolist()
    fig = px.box(comparison, x='points_per_90', y='metric_id', color='cohort',
        category_orders={'metric_id': contribution_order}, points=False,
        labels={'points_per_90': 'Metric points per 90', 'metric_id': 'Metric'},
        title='Distribution of metric points: all players vs current in-form players')
    fig.update_layout(height=max(1000, len(contribution_order)*27), margin=dict(l=220))
    show_figure(fig)

    means = comparison.groupby(['metric_id', 'slot', 'cohort'], as_index=False).agg(
        mean_points=('metric_points', 'mean'), mean_per_90=('points_per_90', 'mean'), appearances=('player_id', 'size'))
    top_metrics = contribution_order[:12]
    fig = px.line(means.loc[means.metric_id.isin(top_metrics)], x='slot', y='mean_per_90',
        color='cohort', facet_col='metric_id', facet_col_wrap=3, markers=True,
        hover_data=['mean_points', 'appearances'], title='Largest contribution metrics across team match slots',
        labels={'slot': 'Team match slot (oldest → newest)', 'mean_per_90': 'Mean points per 90'})
    fig.update_yaxes(matches=None)
    fig.update_xaxes(dtick=1)
    fig.update_layout(height=1000)
    show_figure(fig)
''')
markdown('''
    ## Select a metric: player trajectories and next-match results

    Use the dropdown inside the chart. Left: up to `DETAIL_PLAYERS` players with the
    largest absolute contribution to the chosen metric, coloured by position. Right:
    every evaluated next-match forecast, coloured by **pre-match** form status. The
    diagonal is a perfect forecast. Player trajectories use actual points; prediction
    comparisons use points per 90. Hover includes dates, competition and opponent.
''')
code('''
    detail = make_subplots(rows=1, cols=2, subplot_titles=['Actual player contributions', 'Forecast vs observed points per 90'])
    colors = {'GK': '#7c3aed', 'DEF': '#2563eb', 'MID': '#059669', 'FWD': '#d97706'}
    ranges, buttons = [], []
    for metric_index, metric in enumerate(contribution_order):
        start = len(detail.data)
        subset = descriptive.loc[descriptive.metric_id == metric]
        leaders = subset.groupby(['team_id', 'player_id']).metric_points.apply(lambda s: s.abs().sum()).nlargest(DETAIL_PLAYERS).index
        for team_id, player_id in leaders:
            player = subset.loc[(subset.team_id == team_id) & (subset.player_id == player_id)].sort_values('slot')
            first = player.iloc[0]
            # Reindex to all team slots, retaining absence gaps in the line.
            slots = metadata.loc[metadata.team_id == team_id].slot.tolist()
            player = player.set_index('slot').reindex(slots).reset_index()
            hover = [f"{first.player_name} ({first.position})<br>{r.kickoff}<br>{r.opponent} / {r.competition}"
                     if pd.notna(r.kickoff) else f'{first.player_name}: missing appearance'
                     for r in player.itertuples()]
            detail.add_trace(go.Scatter(x=player.slot, y=player.metric_points, mode='lines+markers',
                connectgaps=False, name=first.player_name, line=dict(color=colors[first.position]),
                text=hover, hovertemplate='%{text}<br>Slot %{x}: %{y} points<extra></extra>', visible=metric_index == 0), row=1, col=1)
        tested = evaluations.loc[evaluations.metric_id == metric]
        for in_form, name, color in [(False, 'Outside pre-match form', '#94a3b8'), (True, 'Pre-match in form', '#e11d48')]:
            points = tested.loc[tested.in_form == in_form]
            hover = [f'{r.player_name} ({r.position})<br>{r.kickoff}<br>{r.opponent} / {r.competition}<br>Earlier appearances: {r.history_count}' for r in points.itertuples()]
            detail.add_trace(go.Scatter(x=points.predicted_per_90, y=points.points_per_90,
                mode='markers', name=name, marker=dict(color=color, opacity=.65), text=hover,
                hovertemplate='%{text}<br>Forecast %{x:.1f}<br>Actual %{y:.1f}<extra></extra>', visible=metric_index == 0), row=1, col=2)
        bound = max(1, tested.points_per_90.abs().max() if len(tested) else 1,
                    tested.predicted_per_90.abs().max() if len(tested) else 1)
        detail.add_trace(go.Scatter(x=[-bound, bound], y=[-bound, bound], mode='lines',
            line=dict(color='#64748b', dash='dash'), showlegend=False, hoverinfo='skip', visible=metric_index == 0), row=1, col=2)
        ranges.append((start, len(detail.data), metric))
    for start, end, metric in ranges:
        buttons.append(dict(label=metric, method='update', args=[
            {'visible': [start <= i < end for i in range(len(detail.data))]},
            {'title': f'Metric detail: {metric}', 'xaxis2.autorange': True, 'yaxis2.autorange': True,
             'yaxis.autorange': True}]))
    detail.update_layout(title=f'Metric detail: {contribution_order[0]}', height=650,
        updatemenus=[dict(buttons=buttons, x=0, y=1.2, xanchor='left', yanchor='top')],
        margin=dict(t=140), legend=dict(orientation='h', y=-.2))
    detail.update_xaxes(title_text='Team match slot', dtick=1, row=1, col=1)
    detail.update_yaxes(title_text='Actual metric points', row=1, col=1)
    detail.update_xaxes(title_text='Forecast points per 90', row=1, col=2)
    detail.update_yaxes(title_text='Observed points per 90', row=1, col=2)
    show_figure(detail)
''')
markdown('''
    ## Reading the result

    Use position-specific green metrics as candidates for repeatable contributions.
    Amber requires demonstrated repeatability in the pre-match form cohort. Red means
    the metric failed this configured prediction approach with adequate evidence;
    it is not a claim that the metric can never be predicted by another model.
    Grey calls for more evidence rather than forced inclusion or exclusion.

    This window mixes competitions and opponents and includes only source-eligible
    players. Source failures, short appearances, small form cohorts and proxy awards
    limit the interpretation. No opponent adjustment or longer-term validation is
    added. Save the notebook after rerunning to retain updated tables and charts.
''')
code('''
    display(positions.groupby(['evidence_status', 'classification']).size().rename('Position/metric groups').to_frame())
    display(Markdown('**All position-specific metrics, including unclassified and unsupported entries:**'))
    display(positions[['metric_id', 'position', 'classification', 'evidence_status',
        'all_wape', 'all_recurrence', 'form_wape', 'form_recurrence']].round(3))
    assert evaluations.empty or evaluations.latest_history_kickoff.lt(evaluations.kickoff).all()
    print('Award reconciliation and strict pre-kickoff history checks passed.')
''')

notebook = nbf.v4.new_notebook(cells=cells, metadata={
    'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
    'language_info': {'name': 'python'},
})
target = ROOT / 'notebooks/09_reflection/05_sofascore_kickbase_metric_consistency.ipynb'
nbf.write(notebook, target)
if '--execute-in-process' in sys.argv:
    # Execute through IPython's real display machinery without spawning a kernel.
    # Useful in environments where local Jupyter sockets are restricted.
    from IPython.core.interactiveshell import InteractiveShell
    from IPython.utils.capture import capture_output
    shell = InteractiveShell.instance()
    for index, cell in enumerate(notebook.cells):
        if cell.cell_type != 'code':
            continue
        print(f'Executing cell {index + 1}', flush=True)
        with capture_output() as captured:
            executed = shell.run_cell(cell.source, store_history=True)
        executed.raise_error()
        cell.execution_count = executed.execution_count
        cell.outputs = []
        if captured.stdout:
            cell.outputs.append(nbf.v4.new_output('stream', name='stdout', text=captured.stdout))
        if captured.stderr:
            cell.outputs.append(nbf.v4.new_output('stream', name='stderr', text=captured.stderr))
        for output in captured.outputs:
            cell.outputs.append(nbf.v4.new_output('display_data', data=output.data, metadata=output.metadata))
    notebook.metadata['execution_method'] = 'IPython cell execution with captured rich displays'
    nbf.write(notebook, target)
elif '--execute' in sys.argv:
    from jupyter_client import KernelManager
    from nbclient import NotebookClient
    # Use the actual interpreter rather than an ambiguous Windows python alias.
    manager = KernelManager(kernel_name='python3')
    manager.kernel_spec.argv[0] = sys.executable
    NotebookClient(notebook, km=manager, timeout=180, startup_timeout=60,
                   resources={'metadata': {'path': str(ROOT)}}).execute()
    nbf.write(notebook, target)
print(target)
