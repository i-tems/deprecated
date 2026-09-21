from fastapi import APIRouter
from app.core.config import (
    EVALUATIONS_DIR,
    SKILL_EVALUATIONS_DIR,
    RUNNING_EVALUATIONS_DIR,
    CONFIG_FILE,
)
from app.core.storage import read_json, list_date_files

router = APIRouter(prefix="/api", tags=["overview"])

ATTRIBUTES = ["strength", "development", "mmc"]


def _load_config():
    data = read_json(CONFIG_FILE)
    if data is None:
        return {"body_parts": [], "skills": []}
    return data


@router.get("/overview")
def get_overview():
    config = _load_config()
    part_map = {p["id"]: p["name"] for p in config.get("body_parts", [])}
    skill_map = {s["id"]: s["name"] for s in config.get("skills", [])}
    running_metrics = config.get("running_metrics", []) or []
    metric_map = {m["id"]: m for m in running_metrics}
    all_part_ids = [p["id"] for p in config.get("body_parts", [])]
    all_skill_ids = [s["id"] for s in config.get("skills", [])]
    all_metric_ids = [m["id"] for m in running_metrics]

    eval_files = list_date_files(EVALUATIONS_DIR)
    skill_files = list_date_files(SKILL_EVALUATIONS_DIR)
    running_files = list_date_files(RUNNING_EVALUATIONS_DIR)

    # --- Latest body part evaluations ---
    latest_parts: dict[str, dict] = {}
    latest_parts_date: dict[str, str] = {}
    for f in reversed(eval_files):
        data = read_json(f)
        if data is None:
            continue
        eval_date = data.get("date", f.stem)
        for part_id, part_data in data.get("parts", {}).items():
            if part_id not in latest_parts:
                latest_parts[part_id] = part_data
                latest_parts_date[part_id] = eval_date

    # --- Second-latest for change detection ---
    second_latest_parts: dict[str, dict] = {}
    for f in reversed(eval_files):
        data = read_json(f)
        if data is None:
            continue
        for part_id, part_data in data.get("parts", {}).items():
            if part_id in latest_parts_date:
                eval_date = data.get("date", f.stem)
                if eval_date < latest_parts_date[part_id] and part_id not in second_latest_parts:
                    second_latest_parts[part_id] = part_data

    # --- Latest skill evaluations ---
    latest_skills: dict[str, dict] = {}
    for f in reversed(skill_files):
        data = read_json(f)
        if data is None:
            continue
        for skill_id, skill_data in data.get("skills", {}).items():
            if skill_id not in latest_skills:
                latest_skills[skill_id] = skill_data

    # --- Running: latest explicit level + best PR value (separately tracked) ---
    # - latest_level = most recently saved level for each metric (slider-driven)
    # - best_running = best actual PR value across all entries (only entries
    #   with a value field contribute; a slower recent PR should not lower this)
    latest_running_level: dict[str, dict] = {}
    best_running: dict[str, dict] = {}
    latest_running_date: str | None = None
    for f in running_files:
        data = read_json(f)
        if data is None:
            continue
        eval_date = data.get("date", f.stem)
        if latest_running_date is None or eval_date > latest_running_date:
            latest_running_date = eval_date
        for metric_id, entry in data.get("metrics", {}).items():
            m = metric_map.get(metric_id)
            if m is None:
                continue
            level = entry.get("level")
            if level is not None:
                current_latest = latest_running_level.get(metric_id)
                if current_latest is None or eval_date >= current_latest["date"]:
                    latest_running_level[metric_id] = {
                        "level": float(level),
                        "date": eval_date,
                    }
            value = entry.get("value")
            if value is None:
                continue
            current_best = best_running.get(metric_id)
            if current_best is None:
                best_running[metric_id] = {"value": float(value), "date": eval_date}
                continue
            direction = m.get("direction", "lower")
            is_better = (
                float(value) < current_best["value"]
                if direction == "lower"
                else float(value) > current_best["value"]
            )
            if is_better:
                best_running[metric_id] = {"value": float(value), "date": eval_date}

    # --- Build part_scores ---
    part_scores = []
    for pid in all_part_ids:
        pdata = latest_parts.get(pid, {})
        s = pdata.get("strength", 0) or 0
        d = pdata.get("development", 0) or 0
        m = pdata.get("mmc", 0) or 0
        part_scores.append({
            "part_id": pid,
            "part_name": part_map.get(pid, pid),
            "strength": s,
            "development": d,
            "mmc": m,
            "best_5rm": pdata.get("best_5rm"),
            "total": round(s + d + m, 2),
        })

    # --- Build skill_scores ---
    skill_scores = []
    for sid in all_skill_ids:
        sdata = latest_skills.get(sid, {})
        score = sdata.get("level", 0) or 0
        skill_scores.append({
            "skill_id": sid,
            "skill_name": skill_map.get(sid, sid),
            "score": score,
        })

    # --- Build running_scores ---
    # level = latest explicit level (slider-driven)
    # value/last_date = best actual PR (only if user entered raw time/distance)
    running_scores = []
    for mid in all_metric_ids:
        m = metric_map.get(mid, {})
        latest = latest_running_level.get(mid)
        best = best_running.get(mid)
        running_scores.append({
            "metric_id": mid,
            "metric_name": m.get("name", mid),
            "unit": m.get("unit", "time"),
            "direction": m.get("direction", "lower"),
            "level": latest["level"] if latest else 0,
            "value": best["value"] if best else None,
            "last_date": best["date"] if best else None,
        })

    # --- Total score ---
    total_score = (
        sum(p["total"] for p in part_scores)
        + sum(s["score"] for s in skill_scores)
        + sum(r["level"] for r in running_scores)
    )

    # --- Recent changes ---
    recent_changes = []
    for pid, pdata in latest_parts.items():
        old = second_latest_parts.get(pid, {})
        for attr in ATTRIBUTES:
            new_val = pdata.get(attr, 0) or 0
            old_val = old.get(attr, 0) or 0
            if new_val != old_val:
                recent_changes.append({
                    "part_id": pid,
                    "part_name": part_map.get(pid, pid),
                    "attribute": attr,
                    "old_value": old_val,
                    "new_value": new_val,
                    "change": round(new_val - old_val, 2),
                })

    # --- Weakest (lowest 3 non-zero attributes) ---
    all_attrs = []
    for ps in part_scores:
        for attr in ATTRIBUTES:
            val = ps.get(attr, 0)
            if val > 0:
                all_attrs.append({
                    "part_id": ps["part_id"],
                    "part_name": ps["part_name"],
                    "attribute": attr,
                    "value": val,
                })
    all_attrs.sort(key=lambda x: x["value"])
    weakest = all_attrs[:3]

    # --- Last evaluation date ---
    last_date = None
    if eval_files:
        last_date = eval_files[-1].stem

    return {
        "total_score": round(total_score, 2),
        "part_scores": part_scores,
        "skill_scores": skill_scores,
        "running_scores": running_scores,
        "recent_changes": recent_changes,
        "weakest": weakest,
        "last_evaluation_date": last_date,
        "last_running_date": latest_running_date,
    }
