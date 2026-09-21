from datetime import date
from typing import Any
from fastapi import APIRouter, Query
from pydantic import BaseModel
from app.core.config import RUNNING_EVALUATIONS_DIR, CONFIG_FILE
from app.core.storage import read_json, write_json, list_date_files

router = APIRouter(prefix="/api", tags=["running-evaluations"])


def _parse_time(value: str | float | int) -> float | None:
    """Parse 'h:mm:ss', 'mm:ss', or numeric into a float (seconds for time, raw for distance)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    if ":" in s:
        parts = s.split(":")
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return None
        if len(nums) == 2:
            return nums[0] * 60 + nums[1]
        if len(nums) == 3:
            return nums[0] * 3600 + nums[1] * 60 + nums[2]
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _standards_as_numbers(metric: dict) -> list[tuple[int, float]]:
    """Return sorted list of (level_int, numeric_threshold) from metric config."""
    raw = metric.get("level_standards", {}) or {}
    out: list[tuple[int, float]] = []
    for lv_str, thr in raw.items():
        try:
            lv = int(lv_str)
        except (TypeError, ValueError):
            continue
        num = _parse_time(thr)
        if num is None:
            continue
        out.append((lv, num))
    out.sort(key=lambda x: x[0])
    return out


def _compute_level(metric: dict, value: float) -> float:
    """Given a metric config and raw value, compute a 1.0~5.0 level (snapped to 0.5)."""
    entries = _standards_as_numbers(metric)
    if not entries or value is None:
        return 0.0
    direction = metric.get("direction", "lower")

    # Build ordered pairs (threshold, level) ordered by worst -> best so we can interpolate.
    if direction == "lower":
        # lower threshold is better -> sort by threshold descending (worst first)
        ordered = sorted(entries, key=lambda x: -x[1])
        is_better = lambda a, b: a <= b  # noqa: E731
    else:
        # higher threshold is better -> sort by threshold ascending (worst first)
        ordered = sorted(entries, key=lambda x: x[1])
        is_better = lambda a, b: a >= b  # noqa: E731

    # Below the worst threshold -> Lv 1
    worst_lv, worst_thr = ordered[0]
    if not is_better(value, worst_thr):
        return float(worst_lv)
    # Above/beyond the best threshold -> Lv 5
    best_lv, best_thr = ordered[-1]
    if is_better(value, best_thr):
        return float(best_lv)

    # Otherwise interpolate linearly between adjacent brackets
    for i in range(len(ordered) - 1):
        lv_a, thr_a = ordered[i]
        lv_b, thr_b = ordered[i + 1]
        # value is between thr_a (worse) and thr_b (better) inclusive
        lo, hi = min(thr_a, thr_b), max(thr_a, thr_b)
        if lo <= value <= hi:
            span = thr_b - thr_a
            if span == 0:
                level = float(lv_b)
            else:
                frac = (value - thr_a) / span
                level = lv_a + frac * (lv_b - lv_a)
            return round(level * 2) / 2

    return float(worst_lv)


def _load_running_metrics() -> list[dict]:
    cfg = read_json(CONFIG_FILE)
    if not cfg:
        return []
    return cfg.get("running_metrics", []) or []


class FlatRunningEvaluation(BaseModel):
    date: str
    metric_id: str
    level: float  # 1.0 ~ 5.0, 0.5 step — subjective/explicit level
    value: float | None = None  # optional raw PR (seconds or km)


@router.get("/running-evaluations")
def get_running_evaluations(
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    metric: str | None = Query(None),
):
    fd = date.fromisoformat(from_date) if from_date else None
    td = date.fromisoformat(to_date) if to_date else None
    files = list_date_files(RUNNING_EVALUATIONS_DIR, fd, td)

    results = []
    for f in files:
        data = read_json(f)
        if data is None:
            continue
        eval_date = data.get("date", f.stem)
        for metric_id, entry in data.get("metrics", {}).items():
            if metric and metric_id != metric:
                continue
            results.append({
                "date": eval_date,
                "metric_id": metric_id,
                "level": entry.get("level", 0) or 0,
                "value": entry.get("value"),
            })
    return results


@router.post("/running-evaluations")
def create_running_evaluation(body: list[FlatRunningEvaluation]):
    """Accept array of flat running evaluations, group by date and save.

    Level is the primary signal (always stored). Value is an optional raw PR
    (time in seconds or distance in km) that the user can enter alongside.
    """
    by_date: dict[str, dict[str, Any]] = {}

    for item in body:
        if item.date not in by_date:
            by_date[item.date] = {"date": item.date, "metrics": {}}
        entry: dict[str, Any] = {"level": item.level}
        if item.value is not None:
            entry["value"] = item.value
        by_date[item.date]["metrics"][item.metric_id] = entry

    results = []
    for eval_date, data in by_date.items():
        file_path = RUNNING_EVALUATIONS_DIR / f"{eval_date}.json"
        existing = read_json(file_path)
        if existing:
            existing_metrics = existing.get("metrics", {})
            existing_metrics.update(data["metrics"])
            existing["metrics"] = existing_metrics
            write_json(file_path, existing)
            results.append(existing)
        else:
            write_json(file_path, data)
            results.append(data)

    return results
