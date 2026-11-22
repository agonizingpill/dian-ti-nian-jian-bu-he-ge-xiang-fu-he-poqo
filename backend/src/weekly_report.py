"""Weekly leaf-node distribution for completed triage reviews.

Business rules implemented here:

* A review belongs to the week of its *acceptance* time (``accepted_at``,
  falling back to ``created_at`` for jobs accepted before the column existed).
  Completion may happen later; the record still returns to its original week.
* Retried jobs are one task. ``retry_of`` links a retry to the root job; all
  attempts share the root acceptance and are counted at most once.
* Per lift and week only the latest accepted completed review counts. When a
  newer order replaces an older one, the lift leaves the old leaf and enters
  the new one, so both leaf counts move together.
* Old jobs whose stored features can no longer be mapped to a leaf are listed
  as the explicit ``unknown`` leaf.
"""

import json
from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from .algorithm import FEATURE_NAMES, leaf_catalog, leaf_for_features
from .db import connection
from .operations_evidence import actor_field

UNKNOWN_KEY = "unknown"
WEEK_FORMAT = "%Y-%m-%d"


def _fetch_all(sql, params=()):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def _fetch_one(sql, params=()):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return dict(row) if (row := cur.fetchone()) else None


def _parse_week(value):
    if value is None or value == "":
        return None
    try:
        parsed = datetime.strptime(str(value), WEEK_FORMAT).date()
    except ValueError:
        raise HTTPException(422, "周起始日期格式应为 YYYY-MM-DD")
    return parsed - timedelta(days=parsed.weekday())


def _week_meta(start):
    end = start + timedelta(days=6)
    iso_year, iso_week, _ = start.isocalendar()
    return {
        "start": start.strftime(WEEK_FORMAT),
        "end": end.strftime(WEEK_FORMAT),
        "iso": f"{iso_year}-W{iso_week:02d}",
        "label": f"{iso_year}-W{iso_week:02d}（{start:%m-%d} ~ {end:%m-%d}）",
    }


def _accept_time(job):
    return job.get("accepted_at") or job.get("created_at")


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _root_of(job, jobs_by_id):
    root = job["id"]
    current = job
    seen = set()
    while True:
        parent_id = _as_int(current.get("retry_of"))
        if parent_id is None or parent_id in seen or parent_id not in jobs_by_id:
            return root
        seen.add(parent_id)
        root = parent_id
        current = jobs_by_id[parent_id]


def _leaf_payload(leaf):
    return {
        "key": leaf["key"],
        "label": leaf["label"],
        "prediction": leaf["prediction"],
        "conditions": leaf.get("conditions", []),
        "known": leaf["key"] != UNKNOWN_KEY,
    }


def _load_chains():
    """Group analysis jobs into task chains rooted at the original order."""
    jobs = _fetch_all(
        """
        SELECT j.id,j.lift_id,j.status,j.features_json,j.retry_of,
               j.accepted_at,j.created_at,j.completed_at,
               l.asset_code,l.building
        FROM analysis_jobs j JOIN lifts l ON l.id=j.lift_id
        ORDER BY j.id
        """
    )
    jobs_by_id = {int(job["id"]): job for job in jobs}
    grouped = defaultdict(list)
    for job in jobs:
        grouped[_root_of(job, jobs_by_id)].append(job)

    chains = []
    for root_id, attempts in grouped.items():
        completed = [job for job in attempts if job["status"] == "completed"]
        if not completed:
            continue
        chosen = max(completed, key=lambda job: (_accept_time(job), job["id"]))
        effective = min(_accept_time(job) for job in attempts)
        week_start = effective.date() - timedelta(days=effective.date().weekday())
        chains.append({
            "root_id": root_id,
            "lift_id": int(chosen["lift_id"]),
            "asset_code": chosen["asset_code"],
            "building": chosen["building"],
            "effective_accept": effective,
            "week_start": week_start,
            "chosen": chosen,
            "completed": completed,
            "attempts": attempts,
            "leaf": leaf_for_features(chosen["features_json"]),
        })
    return chains


def _order_view(chain, counted, replaced_by):
    chosen = chain["chosen"]
    attempts = chain["attempts"]
    return {
        "job_id": int(chosen["id"]),
        "attempt_ids": sorted(int(job["id"]) for job in attempts),
        "retry_count": len(attempts) - 1,
        "accepted_at": chain["effective_accept"].isoformat(sep=" "),
        "completed_at": chosen["completed_at"].isoformat(sep=" ") if chosen["completed_at"] else None,
        "leaf": _leaf_payload(chain["leaf"]),
        "counted": counted,
        "replaced_by_job_id": replaced_by,
    }


def _share(count, total):
    return round(count * 100 / total, 2) if total else 0.0


def _report_for_week(week_start, chains=None):
    if chains is None:
        chains = _load_chains()
    # Retries collapse into one chain already; now pick one chain per lift/week.
    slots = defaultdict(list)
    for chain in chains:
        slots[(chain["week_start"], chain["lift_id"])].append(chain)

    week_chains = [chain for chain in chains if chain["week_start"] == week_start]
    selected = {}
    for lift_id in {chain["lift_id"] for chain in week_chains}:
        counted = max(
            slots[(week_start, lift_id)],
            key=lambda chain: (chain["effective_accept"], int(chain["chosen"]["id"])),
        )
        selected[lift_id] = counted

    # Replacements: older chains for the same lift in this week are superseded.
    lifts = []
    leaf_counts = defaultdict(int)
    unknown_count = 0
    for lift_id in sorted(selected, key=lambda ident: (selected[ident]["asset_code"], ident)):
        counted = selected[lift_id]
        older = sorted(
            (chain for chain in slots[(week_start, lift_id)] if chain is not counted),
            key=lambda chain: (chain["effective_accept"], int(chain["chosen"]["id"])),
            reverse=True,
        )
        orders = [_order_view(counted, True, None)]
        for index, chain in enumerate(older):
            replaced_by = int(counted["chosen"]["id"]) if index == 0 else int(older[index - 1]["chosen"]["id"])
            orders.append(_order_view(chain, False, replaced_by))
        leaf = counted["leaf"]
        if leaf["key"] == UNKNOWN_KEY:
            unknown_count += 1
        else:
            leaf_counts[leaf["key"]] += 1
        lifts.append({
            "lift_id": lift_id,
            "asset_code": counted["asset_code"],
            "building": counted["building"],
            "leaf": _leaf_payload(leaf),
            "task_id": counted["root_id"],
            "job_id": int(counted["chosen"]["id"]),
            "accepted_at": counted["effective_accept"].isoformat(sep=" "),
            "completed_at": counted["chosen"]["completed_at"].isoformat(sep=" ") if counted["chosen"]["completed_at"] else None,
            "orders": orders,
            "replaced_count": len(older),
        })

    total = len(lifts)
    leaves = []
    for row in leaf_catalog():
        count = leaf_counts.get(row["key"], 0)
        leaves.append({
            "key": row["key"],
            "label": row["label"],
            "prediction": row["prediction"],
            "conditions": row["conditions"],
            "training_count": row["training_count"],
            "training_share": row["training_share"],
            "lift_count": count,
            "share": _share(count, total),
        })
    unknown = {
        "key": UNKNOWN_KEY,
        "label": "未知",
        "prediction": None,
        "conditions": [],
        "training_count": None,
        "training_share": None,
        "lift_count": unknown_count,
        "share": _share(unknown_count, total),
    }

    all_weeks = sorted({chain["week_start"] for chain in chains})
    weeks = []
    for start in all_weeks:
        week_lifts = {
            chain["lift_id"]
            for chain in chains
            if chain["week_start"] == start
        }
        weeks.append({**_week_meta(start), "lift_count": len(week_lifts)})

    return {
        "week": _week_meta(week_start),
        "weeks": weeks,
        "total_lifts": total,
        "known_lifts": total - unknown_count,
        "leaves": leaves,
        "unknown": unknown,
        "lifts": lifts,
        "can_freeze": total > 0,
    }


def build_report(week=None):
    chains = _load_chains()
    requested = _parse_week(week)
    if requested is None:
        available = sorted({chain["week_start"] for chain in chains})
        if available:
            requested = available[-1]
        else:
            today = date.today()
            requested = today - timedelta(days=today.weekday())
    report = _report_for_week(requested, chains)
    snapshot = get_snapshot(report["week"]["start"])
    report["snapshot"] = snapshot
    report["comparison"] = compare(report, snapshot) if snapshot else None
    report["can_freeze"] = snapshot is None and report["total_lifts"] > 0
    return report


def _assignment_map(report):
    return {
        str(item["lift_id"]): {
            "lift_id": item["lift_id"],
            "asset_code": item["asset_code"],
            "leaf_key": item["leaf"]["key"],
            "leaf_label": item["leaf"]["label"],
            "task_id": item["task_id"],
            "job_id": item["job_id"],
        }
        for item in report["lifts"]
    }


def _freeze_payload(report):
    return {
        "week": report["week"],
        "total_lifts": report["total_lifts"],
        "known_lifts": report["known_lifts"],
        "leaves": [
            {
                "key": leaf["key"],
                "label": leaf["label"],
                "prediction": leaf["prediction"],
                "training_count": leaf["training_count"],
                "training_share": leaf["training_share"],
                "lift_count": leaf["lift_count"],
                "share": leaf["share"],
            }
            for leaf in report["leaves"]
        ],
        "unknown": {
            "key": UNKNOWN_KEY,
            "label": "未知",
            "lift_count": report["unknown"]["lift_count"],
            "share": report["unknown"]["share"],
        },
        "assignments": list(_assignment_map(report).values()),
    }


def freeze_week(week, user):
    requested = _parse_week(week)
    if requested is None:
        raise HTTPException(422, "请选择要封存的周")
    report = _report_for_week(requested, _load_chains())
    if report["total_lifts"] == 0:
        raise HTTPException(409, "该周没有已完成的复核记录，无法封存")
    signer = next(
        str(value)
        for field in ("username", "email", "name", "id", "sub")
        if (value := actor_field(user, field)) is not None
    )
    payload = _freeze_payload(report)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT week_start FROM weekly_leaf_snapshots WHERE week_start=%s",
                (requested,),
            )
            existing = cur.fetchone()
            if existing:
                raise HTTPException(409, f"{report['week']['label']} 周报已封存，封存值不可覆盖")
            cur.execute(
                "INSERT INTO weekly_leaf_snapshots(week_start,payload,frozen_by) VALUES(%s,%s,%s)",
                (requested, json.dumps(payload, ensure_ascii=False, default=str), signer),
            )
    snapshot = get_snapshot(report["week"]["start"])
    return {"frozen": True, "week": report["week"], "signer": signer, "snapshot": snapshot}


def _decode(payload):
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "strict")
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except (TypeError, ValueError):
            return None
    return payload if isinstance(payload, dict) else None


def get_snapshot(week_start):
    row = _fetch_one(
        "SELECT week_start,payload,frozen_by,frozen_at FROM weekly_leaf_snapshots WHERE week_start=%s",
        (week_start,),
    )
    if not row:
        return None
    payload = _decode(row["payload"])
    if payload is None:
        return None
    payload = dict(payload)
    payload["signer"] = row["frozen_by"]
    payload["frozen_at"] = row["frozen_at"].isoformat(sep=" ") if row["frozen_at"] else None
    return payload


def compare(report, snapshot):
    """Frozen distribution versus the corrected, currently recomputed one."""
    frozen_leaves = {leaf["key"]: leaf for leaf in snapshot.get("leaves", [])}
    current_leaves = {leaf["key"]: leaf for leaf in report["leaves"]}
    ordered_keys = [leaf["key"] for leaf in report["leaves"]]
    for key in frozen_leaves:
        if key not in current_leaves:
            ordered_keys.append(key)

    rows = []
    for key in ordered_keys:
        frozen = frozen_leaves.get(key, {})
        current = current_leaves.get(key, {})
        frozen_count = int(frozen.get("lift_count", 0))
        current_count = int(current.get("lift_count", 0))
        frozen_share = float(frozen.get("share", 0.0))
        current_share = float(current.get("share", 0.0))
        rows.append({
            "key": key,
            "label": current.get("label") or frozen.get("label") or key,
            "prediction": current.get("prediction") or frozen.get("prediction"),
            "training_share": current.get("training_share", frozen.get("training_share")),
            "frozen_count": frozen_count,
            "current_count": current_count,
            "delta_count": current_count - frozen_count,
            "frozen_share": frozen_share,
            "current_share": current_share,
            "delta_share": round(current_share - frozen_share, 2),
        })

    frozen_unknown = snapshot.get("unknown", {}) or {}
    frozen_unknown_count = int(frozen_unknown.get("lift_count", 0))
    current_unknown_count = int(report["unknown"]["lift_count"])
    frozen_unknown_share = float(frozen_unknown.get("share", 0.0))
    current_unknown_share = float(report["unknown"]["share"])
    rows.append({
        "key": UNKNOWN_KEY,
        "label": "未知",
        "prediction": None,
        "training_share": None,
        "frozen_count": frozen_unknown_count,
        "current_count": current_unknown_count,
        "delta_count": current_unknown_count - frozen_unknown_count,
        "frozen_share": frozen_unknown_share,
        "current_share": current_unknown_share,
        "delta_share": round(current_unknown_share - frozen_unknown_share, 2),
    })

    frozen_map = {str(item["lift_id"]): item for item in snapshot.get("assignments", [])}
    current_map = _assignment_map(report)
    changes = []
    for lift_id in sorted(set(frozen_map) | set(current_map), key=lambda value: int(value)):
        before = frozen_map.get(lift_id)
        after = current_map.get(lift_id)
        before_key = before["leaf_key"] if before else None
        after_key = after["leaf_key"] if after else None
        if before_key == after_key and (before or {}).get("task_id") == (after or {}).get("task_id"):
            continue
        changes.append({
            "lift_id": int(lift_id),
            "asset_code": (after or before).get("asset_code"),
            "frozen_leaf_key": before_key,
            "frozen_leaf_label": before["leaf_label"] if before else None,
            "current_leaf_key": after_key,
            "current_leaf_label": after["leaf_label"] if after else None,
            "frozen_task_id": before.get("task_id") if before else None,
            "current_task_id": after.get("task_id") if after else None,
            "frozen_job_id": before["job_id"] if before else None,
            "current_job_id": after["job_id"] if after else None,
            "kind": (
                "added" if before is None
                else "removed" if after is None
                else "moved" if before_key != after_key
                else "rerun"
            ),
        })

    return {
        "frozen_at": snapshot.get("frozen_at"),
        "signer": snapshot.get("signer"),
        "frozen_total_lifts": snapshot.get("total_lifts", 0),
        "current_total_lifts": report["total_lifts"],
        "delta_total_lifts": report["total_lifts"] - snapshot.get("total_lifts", 0),
        "leaves": rows,
        "changes": changes,
        "distribution_changed": any(
            row["delta_count"] != 0 for row in rows
        ),
    }


def model_catalog():
    return {
        "features": list(FEATURE_NAMES),
        "training_total": sum(leaf["training_count"] for leaf in leaf_catalog()),
        "leaves": leaf_catalog(),
    }


def list_snapshots():
    """All sealed weeks, newest first, as light references for the selector."""
    rows = _fetch_all(
        "SELECT week_start,frozen_by,frozen_at FROM weekly_leaf_snapshots ORDER BY week_start DESC"
    )
    return [
        {
            "week": _week_meta(row["week_start"]),
            "signer": row["frozen_by"],
            "frozen_at": row["frozen_at"].isoformat(sep=" ") if row["frozen_at"] else None,
        }
        for row in rows
    ]
