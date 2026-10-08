"""Reproduce the MD1/MD2 fit and MD3 goalkeeper residual validation offline."""
from __future__ import annotations

import ast
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
from itertools import combinations
import json
from pathlib import Path
import re
import sys
import unicodedata

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from goalkeeper_kickbase_calibration import FEATURES, ledger_features, policy_fingerprint, predict_residual
from sofascore_kickbase_points import scoring_policy


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normal(name):
    return re.sub("[^a-z0-9]", "", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower())


def dataset():
    sofa_path = ROOT / "outputs/sofascore/player_kickbase_point_averages/overall_player_kickbase_point_averages_2026-09-16_20-24-15_272946+0200.json"
    kb_path = ROOT / "outputs/kbstats/players/kbstats_players_20260915_134004_+0200.json"
    sofa, kb = read(sofa_path), read(kb_path)
    form_path = ROOT / "outputs/sofascore/team_form" / sofa["source_file"]
    forms = next(iter(read(form_path).values()))
    constants = {}
    for node in ast.parse((ROOT / "sofascore_rating_odds_lineup_score.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {"KB_TEAM_ID_TO_KEY", "TEAM_ALIASES"}:
            constants[node.targets[0].id] = ast.literal_eval(node.value)
    aliases = {normal(name): key for key, names in constants["TEAM_ALIASES"].items() for name in names}
    with (ROOT / "data/reference/player_name_cross_references.csv").open(encoding="utf-8-sig") as handle:
        references = list(csv.DictReader(handle))
    rows, missing = [], []
    for team_id, team in sofa["teams"].items():
        matches = sorted([m for m in forms[team_id]["bundesliga_matches"] if "2026-08-01" < m["date"] < "2026-09-14"], key=lambda m: m["date"])
        assert len(matches) == 3
        team_key = aliases[normal(team["team"])]
        keepers = [p for p in team["overall"]["players"] if p["position"] == "GK"]
        for k in kb:
            if k["position"] != 1 or constants["KB_TEAM_ID_TO_KEY"][int(k["teamId"])] != team_key:
                continue
            ids = {int(r["provider_player_id"]) for r in references if r["provider"] == "sofascore" and normal(r["kbstats_name"]) == normal(k["name"])}
            players = [p for p in keepers if normal(p["player_name"]) == normal(k["name"]) or p["player_id"] in ids]
            assert len(players) <= 1
            for md, match in enumerate(matches, 1):
                assert len(k["history"]) == 3
                history = k["history"][3 - md]
                if not history["hasPlayed"]:
                    continue
                calculations = [m for p in players for m in p["match_calculations"] if m["match_id"] == match["match_id"]]
                if not calculations:
                    missing.append(dict(player=k["name"], matchday=md, reason="No calculation in the filtered source snapshot"))
                    continue
                assert len(calculations) == 1
                calc = calculations[0]
                assert sum(a["points"] for a in calc["awards"]) == calc["calculated_kickbase_points"]
                rows.append(dict(player=k["name"], kb_id=k["id"], sofa_id=players[0]["player_id"], team=team["team"],
                                 matchday=md, match=match, base=calc["calculated_kickbase_points"], actual=history["points"],
                                 residual=history["points"] - calc["calculated_kickbase_points"],
                                 features=ledger_features(calc), calculation=calc))
    assert len({(r["kb_id"], r["matchday"]) for r in rows}) == len(rows)
    sources = [{"path": str(p.relative_to(ROOT)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in [sofa_path, kb_path, form_path]]
    return rows, missing, sofa["scoring_policy"], sources


def fit(rows, features, penalty):
    """Small nonnegative ridge regression, exhaustively solving active sets."""
    x = np.array([[r["features"][k] for k in features] for r in rows], dtype=float)
    y = np.array([r["residual"] for r in rows], dtype=float)
    best = (float(y @ y), np.zeros(len(features)))
    for size in range(1, len(features) + 1):
        for active in combinations(range(len(features)), size):
            xa = x[:, active]
            coefficients = np.linalg.lstsq(np.vstack([xa, np.sqrt(penalty) * np.eye(size)]), np.r_[y, np.zeros(size)], rcond=None)[0]
            if np.any(coefficients < 0):
                continue
            full = np.zeros(len(features))
            full[list(active)] = coefficients
            error = y - x @ full
            objective = float(error @ error + penalty * (full @ full))
            if objective < best[0]:
                best = objective, full
    return {"coefficients": dict(zip(features, best[1].tolist()))}


def metrics(rows, correction):
    differences = np.array([r["base"] + correction(r) - r["actual"] for r in rows])
    return dict(n=len(rows), mae=round(float(np.mean(abs(differences))), 3),
                bias=round(float(np.mean(differences)), 3), rmse=round(float(np.sqrt(np.mean(differences ** 2))), 3),
                within10=int(sum(abs(differences) <= 10)), within25=int(sum(abs(differences) <= 25)))


def main():
    rows, missing, policy, sources = dataset()
    # The frozen training ledgers predate exactly one new action mapping.
    # Do not silently bless any other scoring change with an old fitted model.
    current_policy = scoring_policy()
    expected = dict(policy)
    expected['ignored_metric_ids'] = [m for m in policy['ignored_metric_ids'] if m != 'keeper_sweeper']
    expected['goalkeeper_sweeper'] = 'accurateKeeperSweeper only; +10 per successful action; provider classification proxy; never totalKeeperSweeper.'
    if current_policy != expected:
        raise ValueError('Scoring rules changed beyond the audited sweeper mapping; rebuild training ledgers first.')
    md1, md2, md3 = ([r for r in rows if r["matchday"] == md] for md in (1, 2, 3))
    # Model specification and shrinkage are selected using MD2 only. MD3 is
    # excluded from fitting and selection, although inspected in the prior audit.
    feature_sets = [("credited_saves",), ("minutes_90", "credited_saves"),
                    ("minutes_90", "credited_saves", "high_claims"), FEATURES]
    candidates = []
    for features in feature_sets:
        for penalty in (0.0, 1.0, 10.0):
            model = fit(md1, features, penalty)
            validation = metrics(md2, lambda r: predict_residual(r["features"], model))
            candidates.append(dict(features=list(features), penalty=penalty, coefficients=model["coefficients"], validation=validation))
    selected = min(candidates, key=lambda c: (c["validation"]["mae"], len(c["features"]), -c["penalty"]))
    training = md1 + md2
    model = fit(training, selected["features"], selected["penalty"])
    base = metrics(md3, lambda r: 0)
    corrected = metrics(md3, lambda r: predict_residual(r["features"], model))
    flat_points = int(np.floor(np.mean([r["residual"] for r in training]) + 0.5))
    flat = metrics(md3, lambda r: flat_points)
    # A correction is published as experimental only when it beats both the
    # uncorrected score and a training-only constant baseline on the held-out MD.
    accepted = corrected["mae"] < min(base["mae"], flat["mae"])
    model.update(schema_version=1, model_id="gk_residual_md1_md2_2026_v1", experimental=True,
                 unique_tournament_id=35, training_matchdays=[1, 2], validation_matchday=3,
                 training_through=max(r["match"]["date"] for r in training), valid_before="2027-07-01T00:00:00+00:00",
                 feature_ranges={k: [min(r["features"][k] for r in training), max(r["features"][k] for r in training)] for k in model["coefficients"]},
                 training_scoring_policy_sha256=policy_fingerprint(policy),
                 scoring_policy_sha256=policy_fingerprint(scoring_policy()),
                 subtract_mapped_metrics=["keeper_sweeper"], sources=sources,
                 training_rows=len(training), validation_rows=len(md3), regularization=selected["penalty"],
                 validation=dict(base=base, corrected=corrected, training_mean_baseline=flat), accepted=accepted,
                 limitations=["Three matchdays only; filtered export misses some appearances.",
                              "MD3 was previously inspected, but its targets were excluded from fitting and selection.",
                              "Uses credited save/claim/punch counts, not a complete raw keeper action feed.",
                              "Net residual estimate; it does not establish which Kickbase actions were missing.",
                              "New keeper-sweeper points consume the old residual allowance; full post-mapping validation needs historical raw payloads."])
    output = ROOT / "outputs/analysis/gk_audit"
    output.mkdir(parents=True, exist_ok=True)
    for r in rows:
        r["estimated_correction"] = predict_residual(r["features"], model)
        r["estimated_total"] = r["base"] + r["estimated_correction"]
        r["evaluation_split"] = "held_out" if r["matchday"] == 3 else "training_in_sample"
    report = dict(model=model, selected_on_md2=selected, candidates=candidates,
                  raw_audit=dict(status="one_match_audited", match_id=16434037,
                                 source="User-supplied raw lineup and shotmap responses",
                                 noll=dict(saves=5, inside_saves=4, outside_saves=1, punches=3, accurate_keeper_sweeper=2, new_sweeper_points=20),
                                 unsupported=["save technique", "challenged/unchallenged collection", "accurate throws"]),
                  sources=sources, missing=missing, rows=rows)
    (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # The ordinary event-based score remains separate from this estimate.
    if accepted:
        path = ROOT / "data/reference/kickbase/goalkeeper_residual_model.json"
        path.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Goalkeeper points audit and residual validation", "",
             "Audited user-supplied lineup and shotmap JSON for match 16434037 (Dortmund–Paderborn). Noll has five saves (four inside, one outside), three punches and two accurateKeeperSweeper actions. Existing save/punch awards reconcile. Mapping the two successful sweeper actions adds 20 points, changing his event-derived score from 75 to 95 against KBStats 158.", "",
             "The supplied data has no save-technique, challenged/unchallenged collection or accurate-throw labels. Shot location, xG and xGOT do not prove these classifications. No synthetic action counts are added. Future scoring exports retain raw goalkeeper statistics for auditing.", "",
             "The official [Kickbase points table](https://kickbase.com/en-us/points-table) lists technique and location awards but does not explicitly resolve whether they stack. Only the explicitly described big-chance bonus remains additive. No inferred technique awards are stacked onto saves.", "",
             f"Fit MD1 ({len(md1)} rows), select features/regularization on MD2 ({len(md2)} rows), refit MD1+MD2; test MD3 ({len(md3)} rows). MD3 was previously inspected, but excluded from model fitting and selection. This is preliminary validation, not a pristine prospective test.", "",
             "The regression predicts KBStats minus the existing event-derived total. It uses nonnegative coefficients and no player/team identities. Separate residual metadata and estimated totals preserve the original award ledger.", "",
             "| MD3 method | Mean absolute error | Mean signed error | Within 10 |", "|---|---:|---:|---:|"]
    for name, result in [("Original", base), (f"Training-only flat +{flat_points}", flat), ("Activity-based estimate", corrected)]:
        lines.append(f"| {name} | {result['mae']:.2f} | {result['bias']:+.2f} | {result['within10']}/{result['n']} |")
    lines += ["", "Coefficients: `" + json.dumps(model["coefficients"]) + "`.", "",
              "Status: " + ("experimental model saved; the notebook retains raw event scores but uses valid calibrated GK totals for averages and percentile inputs, with event-score fallback" if accepted else "not accepted; no production correction enabled") + ".", "",
              "The table validates the correction against the legacy scoring baseline. New keeper-sweeper points consume this allowance: remaining correction = max(0, allowance - sweeper points). For Noll: event score 95 + remaining estimate 34 = 129, versus KBStats 158. His sweeper points are not added twice. Full validation after adding the sweeper mapping requires raw historical payloads for every keeper.", "",
              "The estimate is limited to Bundesliga matches after the training cutoff, this season, the declared scoring policy and the training feature range (full-match keepers, 0–10 credited saves). Other policy changes require refitting. Missing estimates remain null, not zero. Disable supplemental estimates with include_goalkeeper_estimates=False in run_notebook_workflow.", "",
              "## MD3 keepers", "", "| Player | Original | Correction | Estimated | KBStats | New difference |", "|---|---:|---:|---:|---:|---:|"]
    for r in sorted(md3, key=lambda r: abs(r["base"] - r["actual"]), reverse=True):
        lines.append(f"| {r['player']} | {r['base']} | +{r['estimated_correction']} | {r['estimated_total']} | {r['actual']} | {r['estimated_total']-r['actual']:+d} |")
    lines += ["", "## Missing appearances", ""] + [f"- MD{r['matchday']}: {r['player']} — {r['reason']}" for r in missing]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(dict(counts=dict(Counter(r['matchday'] for r in rows)), selected=selected, model=model), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
