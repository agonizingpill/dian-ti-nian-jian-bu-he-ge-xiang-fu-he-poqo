import json

from sklearn.tree import DecisionTreeClassifier, export_text

FEATURE_NAMES = ["critical_fail_count", "average_score", "failed_item_count", "documentation_gap"]
MODEL_DESCRIPTION = "DecisionTreeClassifier(random_state=1066,max_depth=3)"

# Must stay byte-for-byte identical to backend/src/algorithm.py: the weekly leaf
# report replays stored features against the same fitted tree.
TRAINING_FEATURES = [
    [0, 96, 0, 0], [0, 84, 1, 0], [0, 78, 2, 0],
    [0, 72, 2, 1], [1, 96, 1, 0], [1, 68, 3, 1],
    [0, 91, 0, 1], [0, 66, 3, 1], [2, 88, 2, 0],
]
TRAINING_LABELS = ["ready", "ready", "review", "hold", "hold", "hold", "review", "hold", "hold"]

MODEL = DecisionTreeClassifier(max_depth=3, random_state=1066)
MODEL.fit(TRAINING_FEATURES, TRAINING_LABELS)


def classify(features):
    vector = [[features[n] for n in FEATURE_NAMES]]
    return {
        "prediction": MODEL.predict(vector)[0],
        "probability": float(max(MODEL.predict_proba(vector)[0])),
        "path_rules": export_text(MODEL, feature_names=FEATURE_NAMES),
        "model": MODEL_DESCRIPTION,
    }
