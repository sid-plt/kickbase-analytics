"""Explicit, supplemental goalkeeper residual estimates; never synthetic events.

Features come from the existing award ledger, so old snapshots remain usable.
The model estimates the net KBStats residual, not counts of unobserved saves.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from math import isfinite
from pathlib import Path


MODEL_PATH = Path(__file__).resolve().parent / "data/reference/kickbase/goalkeeper_residual_model.json"
FEATURES = ("minutes_90", "credited_saves", "high_claims", "punches")


def points_for_averages(record: dict, position: str | None):
    """Use a usable GK estimate; preserve event points for everyone else."""
    estimate = record.get("goalkeeper_residual_estimate")
    if position in {"GK", "G"} and isinstance(estimate, dict) and estimate.get("status") == "estimated":
        total = estimate.get("estimated_total")
        if isinstance(total, (int, float)) and not isinstance(total, bool) and isfinite(total):
            return total
    return record.get("calculated_kickbase_points")


def ledger_features(player: dict) -> dict[str, float]:
    counts = {}
    for award in player["awards"]:
        key = award["metric_id"]
        counts[key] = counts.get(key, 0) + award["count"]
    return {
        "minutes_90": min(90, max(0, player["minutes_played"])) / 90,
        "credited_saves": counts.get("box_shot_saved", 0) + counts.get("distance_shot_saved", 0),
        "high_claims": counts.get("cross_intercepted", 0),
        "punches": counts.get("punched_ball", 0),
    }


def policy_fingerprint(policy: dict) -> str:
    # Calibration metadata does not change the underlying event scoring rules.
    base = {k: v for k, v in policy.items() if k != "goalkeeper_residual_estimate"}
    return hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest()


def load_model(path: Path = MODEL_PATH) -> dict | None:
    if not path.exists():
        return None
    model = json.loads(path.read_text(encoding="utf-8"))
    coefficients = model.get("coefficients", {})
    if (model.get("schema_version") != 1 or model.get("accepted") is not True or not coefficients
            or not set(coefficients).issubset(FEATURES)
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not isfinite(v) or v < 0 for v in coefficients.values())):
        raise ValueError("Invalid goalkeeper residual model")
    return model


def predict_residual(features: dict, model: dict) -> int:
    value = sum(features[k] * v for k, v in model["coefficients"].items())
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def estimate_for_match(player: dict, match: dict, policy: dict, model: dict) -> dict:
    """Fail closed outside the validated time/competition/policy scope.

    Known newly mapped awards consume the old residual allowance instead of
    stacking on it. Other policy changes require refitting.
    """
    result = {"status": "not_applicable", "model_id": model["model_id"],
              "points": None, "estimated_total": None, "confidence": "proxy"}
    if player.get("position") != "GK":
        return result
    if policy_fingerprint(policy) != model["scoring_policy_sha256"]:
        result["status"] = "scoring_policy_changed"
        return result
    if match.get("unique_tournament_id") != model["unique_tournament_id"]:
        result["status"] = "outside_competition"
        return result
    date = match.get("date")
    if not date:
        result["status"] = "missing_match_date"
        return result
    played_at = datetime.fromisoformat(date.replace("Z", "+00:00"))
    lower = datetime.fromisoformat(model["training_through"])
    upper = datetime.fromisoformat(model["valid_before"])
    if played_at.tzinfo is None or not lower < played_at < upper:
        result["status"] = "outside_validation_period"
        return result
    features = ledger_features(player)
    if any(not isfinite(v) or v < 0 for v in features.values()):
        result["status"] = "invalid_features"
        return result
    for key, value in features.items():
        if key in model["coefficients"] and not model["feature_ranges"][key][0] <= value <= model["feature_ranges"][key][1]:
            result["status"] = "outside_training_range"
            return result
    allowance = predict_residual(features, model)
    already_mapped = sum(a['points'] for a in player['awards']
                         if a['metric_id'] in model.get('subtract_mapped_metrics', []))
    points = max(0, allowance - already_mapped)
    result.update(status="estimated", points=points, features=features,
                  estimated_total=player["calculated_kickbase_points"] + points,
                  legacy_residual_allowance=allowance, already_mapped_points=already_mapped,
                  interpretation="Net residual estimate, not an observed Kickbase action")
    return result
