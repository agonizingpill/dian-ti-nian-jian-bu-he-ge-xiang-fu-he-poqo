"""Deterministic triage tree and stable leaf-node identity.

The same training set/random seed is used by the worker. Leaf identity is
derived from the fitted tree structure (feature/threshold path), never from
array positions, so old completed jobs can be replayed against the model.
"""

import json
import math
from collections import Counter

from sklearn.tree import DecisionTreeClassifier, export_text

FEATURE_NAMES = ["critical_fail_count", "average_score", "failed_item_count", "documentation_gap"]

FEATURE_LABELS = {
    "critical_fail_count": "关键项不合格",
    "average_score": "平均分",
    "failed_item_count": "不合格项数",
    "documentation_gap": "资料缺失项",
}

MODEL_DESCRIPTION = "DecisionTreeClassifier(random_state=1066,max_depth=3)"

# Reproducible training set mirrors the regulator's triage labels for a compact rule extractor.
TRAINING_FEATURES = [
    [0, 96, 0, 0], [0, 84, 1, 0], [0, 78, 2, 0],
    [0, 72, 2, 1], [1, 96, 1, 0], [1, 68, 3, 1],
    [0, 91, 0, 1], [0, 66, 3, 1], [2, 88, 2, 0],
]
TRAINING_LABELS = ["ready", "ready", "review", "hold", "hold", "hold", "review", "hold", "hold"]

UNKNOWN_LEAF = {
    "key": "unknown",
    "label": "未知",
    "prediction": None,
    "conditions": [],
    "training_count": None,
    "training_share": None,
}

MODEL = DecisionTreeClassifier(max_depth=3, random_state=1066)
MODEL.fit(TRAINING_FEATURES, TRAINING_LABELS)


def _format_threshold(value):
    number = float(value)
    return str(int(number)) if number.is_integer() else format(number, "g")


def _format_condition(condition):
    return f"{FEATURE_LABELS[condition['feature']]}{condition['op']}{condition['value']}"


def _collect_leaves(node, conditions, catalog):
    tree = MODEL.tree_
    left = int(tree.children_left[node])
    right = int(tree.children_right[node])
    if left == -1:
        key = "&".join(
            f"{condition['feature']}{condition['op']}{condition['value']}" for condition in conditions
        )
        prediction = str(MODEL.classes_[int(tree.value[node][0].argmax())])
        catalog.append((node, {
            "key": key,
            "label": " · ".join(_format_condition(condition) for condition in conditions),
            "prediction": prediction,
            "conditions": [dict(condition) for condition in conditions],
            "training_count": 0,
            "training_share": 0.0,
        }))
        return
    feature = FEATURE_NAMES[int(tree.feature[node])]
    threshold = _format_threshold(tree.threshold[node])
    _collect_leaves(left, conditions + [{"feature": feature, "op": "<=", "value": threshold}], catalog)
    _collect_leaves(right, conditions + [{"feature": feature, "op": ">", "value": threshold}], catalog)


_CATALOG = []
_COLLECTED = []
_collect_leaves(0, [], _COLLECTED)
_TRAINING_COUNTS = Counter(int(node) for node in MODEL.apply(TRAINING_FEATURES))
_TRAINING_TOTAL = len(TRAINING_FEATURES)
_BY_NODE = {}
for _node, _leaf in _COLLECTED:
    _leaf["training_count"] = int(_TRAINING_COUNTS[_node])
    _leaf["training_share"] = round(_leaf["training_count"] * 100 / _TRAINING_TOTAL, 2)
    _BY_NODE[_node] = _leaf
    _CATALOG.append(_leaf)


def leaf_catalog():
    """Leaves in tree order with training-sample counts/shares."""
    return [
        {**leaf, "conditions": [dict(condition) for condition in leaf["conditions"]]}
        for leaf in _CATALOG
    ]


def _coerce(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _unknown():
    return {**UNKNOWN_LEAF, "conditions": []}


def leaf_for_features(payload):
    """Map a stored features payload to a leaf, or the explicit unknown leaf."""
    features = payload
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "strict")
    if isinstance(payload, str):
        try:
            features = json.loads(payload)
        except (TypeError, ValueError):
            return _unknown()
    if not isinstance(features, dict):
        return _unknown()
    vector = []
    for name in FEATURE_NAMES:
        number = _coerce(features.get(name))
        if number is None:
            return _unknown()
        vector.append(number)
    try:
        node = int(MODEL.apply([vector])[0])
    except Exception:
        return _unknown()
    leaf = _BY_NODE.get(node)
    if leaf is None:
        return _unknown()
    return {**leaf, "conditions": [dict(condition) for condition in leaf["conditions"]]}


def classify(features: dict):
    vector = [[features[n] for n in FEATURE_NAMES]]
    prediction = MODEL.predict(vector)[0]
    probability = float(max(MODEL.predict_proba(vector)[0]))
    rules = export_text(MODEL, feature_names=FEATURE_NAMES)
    return {
        "prediction": prediction,
        "probability": probability,
        "path_rules": rules,
        "features": features,
        "model": MODEL_DESCRIPTION,
    }


def build_features(items):
    failed = [x for x in items if x["result"] == "fail"]
    scores = [float(x["score"]) for x in items if x["result"] != "na"]
    return {
        "critical_fail_count": sum(1 for x in failed if x["critical"]),
        "average_score": round(sum(scores) / len(scores), 2) if scores else 0,
        "failed_item_count": len(failed),
        "documentation_gap": sum(1 for x in items if x["category"] == "documentation" and x["result"] == "fail"),
    }
