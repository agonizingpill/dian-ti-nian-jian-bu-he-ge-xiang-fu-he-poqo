import json
import os
import sys
from datetime import date, datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.db import connection, init_schema
from src.auth import hash_password
from src.algorithm import MODEL, FEATURE_NAMES

USERS = [
    ("operator@jingcheng.com", "李倩", "operator"),
    ("supervisor@jingcheng.com", "周岚", "supervisor"),
    ("viewer@jingcheng.com", "顾言", "viewer"),
]
LIFTS = [
    ("NJ-YT-021", "云台花园 2 栋", "南京市秦淮区建邺路 88 号", "迅达", "S5500", 1000, 2019, date(2026,12,8)),
    ("NJ-XH-118", "新河商务中心", "南京市鼓楼区中山北路 169 号", "奥的斯", "Gen3", 800, 2018, date(2026,11,28)),
    ("NJ-JS-307", "金盛广场 A 座", "南京市建邺区江东中路 399 号", "日立", "HGP", 1350, 2021, date(2026,12,18)),
    ("NJ-LH-044", "龙湖天街 1 号梯", "南京市栖霞区学津路 9 号", "三菱", "NEXIEZ", 1000, 2020, date(2026,12,21)),
]
ITEMS = {
    "NJ-YT-021": [
        ("SAFETY_CIRCUIT", "安全回路联锁", "safety", True, 42, "fail", "门锁回路在 2 层短接测试未断开", "IMG-YT-021-01.jpg"),
        ("BRAKE_TEST", "制动器静态保持", "safety", True, 55, "fail", "制动距离 112mm，超过 100mm 限值", "IMG-YT-021-02.jpg"),
        ("DOOR_FORCE", "层门闭合力", "mechanical", False, 86, "pass", "闭合力 145N", "IMG-YT-021-03.jpg"),
        ("BUFFER_CLEAR", "缓冲器距离", "mechanical", False, 92, "pass", "底坑净距满足要求", "IMG-YT-021-04.jpg"),
        ("LOGBOOK", "维保记录完整性", "documentation", False, 88, "pass", "近三月记录齐全", "IMG-YT-021-05.jpg"),
    ],
    "NJ-XH-118": [
        ("SAFETY_CIRCUIT", "安全回路联锁", "safety", True, 94, "pass", "回路逐点测试通过", "IMG-XH-118-01.jpg"),
        ("BRAKE_TEST", "制动器静态保持", "safety", True, 93, "pass", "制动距离 76mm", "IMG-XH-118-02.jpg"),
        ("DOOR_FORCE", "层门闭合力", "mechanical", False, 90, "pass", "闭合力 132N", "IMG-XH-118-03.jpg"),
        ("BUFFER_CLEAR", "缓冲器距离", "mechanical", False, 87, "pass", "净距合格", "IMG-XH-118-04.jpg"),
        ("LOGBOOK", "维保记录完整性", "documentation", False, 96, "pass", "记录和签章齐全", "IMG-XH-118-05.jpg"),
    ],
    "NJ-JS-307": [
        ("SAFETY_CIRCUIT", "安全回路联锁", "safety", True, 91, "pass", "测试通过", "IMG-JS-307-01.jpg"),
        ("BRAKE_TEST", "制动器静态保持", "safety", True, 89, "pass", "制动距离 88mm", "IMG-JS-307-02.jpg"),
        ("DOOR_FORCE", "层门闭合力", "mechanical", False, 74, "fail", "西侧门闭合力 208N", "IMG-JS-307-03.jpg"),
        ("BUFFER_CLEAR", "缓冲器距离", "mechanical", False, 90, "pass", "净距合格", "IMG-JS-307-04.jpg"),
        ("LOGBOOK", "维保记录完整性", "documentation", False, 84, "pass", "记录齐全", "IMG-JS-307-05.jpg"),
    ],
    "NJ-LH-044": [
        ("SAFETY_CIRCUIT", "安全回路联锁", "safety", True, 95, "pass", "回路逐点测试通过", "IMG-LH-044-01.jpg"),
        ("BRAKE_TEST", "制动器静态保持", "safety", True, 94, "pass", "制动距离 79mm", "IMG-LH-044-02.jpg"),
        ("DOOR_FORCE", "层门闭合力", "mechanical", False, 89, "pass", "闭合力 149N", "IMG-LH-044-03.jpg"),
        ("BUFFER_CLEAR", "缓冲器距离", "mechanical", False, 93, "pass", "净距合格", "IMG-LH-044-04.jpg"),
        ("LOGBOOK", "维保记录完整性", "documentation", False, 90, "pass", "记录齐全", "IMG-LH-044-05.jpg"),
    ],
}

def seed():
    init_schema()
    with connection() as conn:
        with conn.cursor() as cur:
            for email,name,role in USERS:
                cur.execute("INSERT INTO users(email,name,password_hash,role) VALUES(%s,%s,%s,%s) ON DUPLICATE KEY UPDATE name=VALUES(name),role=VALUES(role),password_hash=VALUES(password_hash)", (email,name,hash_password("Demo@1066"),role))
            cur.execute("SELECT id,email FROM users")
            user_ids = {x["email"]: x["id"] for x in cur.fetchall()}
            lift_ids = {}
            for asset,building,address,mfr,model,load,year,due in LIFTS:
                cur.execute("INSERT INTO lifts(asset_code,building,address,manufacturer,model,rated_load,installed_year,inspection_due,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'active') ON DUPLICATE KEY UPDATE building=VALUES(building),address=VALUES(address),inspection_due=VALUES(inspection_due)", (asset,building,address,mfr,model,load,year,due))
                cur.execute("SELECT id FROM lifts WHERE asset_code=%s", (asset,))
                lift_id = cur.fetchone()["id"]
                lift_ids[asset] = lift_id
                for code,title,category,critical,score,result,notes,photo in ITEMS[asset]:
                    cur.execute("INSERT INTO inspection_items(lift_id,code,title,category,critical,score,result,notes,photo_ref,inspected_at,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open') ON DUPLICATE KEY UPDATE score=VALUES(score),result=VALUES(result),notes=VALUES(notes),photo_ref=VALUES(photo_ref)", (lift_id,code,title,category,critical,score,result,notes,photo,datetime(2026,11,20,9,30)))
                cur.execute("SELECT id FROM inspection_items WHERE lift_id=%s AND code IN ('SAFETY_CIRCUIT','BRAKE_TEST') AND result='fail' LIMIT 1", (lift_id,))
                bad = cur.fetchone()
                if bad:
                    cur.execute("SELECT id FROM rectification_notices WHERE lift_id=%s AND inspection_item_id=%s", (lift_id,bad["id"]))
                    if not cur.fetchone():
                        cur.execute("INSERT INTO rectification_notices(lift_id,inspection_item_id,issue_summary,severity,deadline,status,evidence_required,created_by) VALUES(%s,%s,%s,'critical',%s,'open','回路测试视频+接线端子照片',%s)", (lift_id,bad["id"],"关键安全项不合格，需整改后复检",date(2026,11,25),user_ids["operator@jingcheng.com"]))
            # A deliberately mismatched historical recheck shows the rejection branch in the UI without creating a valid duplicate.
            cur.execute("SELECT id FROM rectification_notices WHERE lift_id=(SELECT id FROM lifts WHERE asset_code='NJ-YT-021') LIMIT 1")
            notice = cur.fetchone()
            cur.execute("SELECT id FROM rechecks WHERE notice_id=%s AND status='evidence_rejected'", (notice["id"],))
            if notice and not cur.fetchone():
                cur.execute("INSERT INTO rechecks(notice_id,scheduled_at,inspector,status,photo_ref,photo_item_code,remarks,created_by) VALUES(%s,%s,'王工','evidence_rejected','IMG-YT-021-03.jpg','DOOR_FORCE','历史照片与安全回路项不匹配，已退回补证',%s)", (notice["id"],datetime(2026,11,23,14,0),user_ids["operator@jingcheng.com"]))
            seed_weekly_history(cur, lift_ids, user_ids)
    print("seed_demo complete: users=3 lifts=4 inspection_items=20")


# Historical triage orders. Each row is
#   (asset_code, accepted_at, completed_at, status, attempts)
# where attempts is a list of (status, features) for the task chain, features
# being None for a legacy row that can no longer be mapped to a leaf.
# A later order accepted in the same lift/week supersedes the earlier one.
HISTORY = [
    ("NJ-YT-021", datetime(2026, 10, 13, 10, 0), datetime(2026, 10, 13, 10, 2), "completed",
     [("completed", {"critical_fail_count": 0, "average_score": 96, "failed_item_count": 0, "documentation_gap": 0})]),
    ("NJ-XH-118", datetime(2026, 10, 14, 9, 20), datetime(2026, 10, 14, 9, 22), "completed",
     [("completed", {"critical_fail_count": 0, "average_score": 84, "failed_item_count": 1, "documentation_gap": 0})]),
    ("NJ-JS-307", datetime(2026, 10, 15, 15, 0), datetime(2026, 10, 15, 15, 2), "completed",
     [("completed", {"critical_fail_count": 0, "average_score": 78, "failed_item_count": 2, "documentation_gap": 0})]),
    ("NJ-LH-044", datetime(2026, 10, 16, 11, 30), datetime(2026, 10, 16, 11, 32), "completed",
     [("completed", {"critical_fail_count": 1, "average_score": 91, "failed_item_count": 1, "documentation_gap": 1})]),
    # Week of 10-19: first attempt failed, the retry completed; counted once.
    ("NJ-XH-118", datetime(2026, 10, 20, 9, 0), datetime(2026, 10, 20, 9, 6), "completed",
     [("failed", {"critical_fail_count": 0, "average_score": 92, "failed_item_count": 0, "documentation_gap": 0}),
      ("completed", {"critical_fail_count": 0, "average_score": 92, "failed_item_count": 0, "documentation_gap": 0})]),
    # Week of 11-02: a newer order supersedes the earlier one for the same lift.
    ("NJ-YT-021", datetime(2026, 11, 3, 10, 0), datetime(2026, 11, 3, 10, 2), "completed",
     [("completed", {"critical_fail_count": 0, "average_score": 71, "failed_item_count": 2, "documentation_gap": 1})]),
    ("NJ-YT-021", datetime(2026, 11, 5, 16, 0), datetime(2026, 11, 5, 16, 2), "completed",
     [("completed", {"critical_fail_count": 0, "average_score": 99, "failed_item_count": 0, "documentation_gap": 0})]),
    # Week of 11-09: one legacy row predating features_json, listed as unknown.
    ("NJ-LH-044", datetime(2026, 11, 10, 8, 45), datetime(2026, 11, 10, 8, 47), "completed",
     [("completed", None)]),
    ("NJ-JS-307", datetime(2026, 11, 11, 13, 15), datetime(2026, 11, 11, 13, 17), "completed",
     [("completed", {"critical_fail_count": 0, "average_score": 84, "failed_item_count": 1, "documentation_gap": 0})]),
    # Accepted 11-13 but completed 11-16: the record returns to the week of acceptance.
    ("NJ-XH-118", datetime(2026, 11, 13, 17, 20), datetime(2026, 11, 16, 9, 5), "completed",
     [("completed", {"critical_fail_count": 0, "average_score": 78, "failed_item_count": 2, "documentation_gap": 0})]),
]


def _leaf_result(features):
    vector = [[features[name] for name in FEATURE_NAMES]]
    prediction = MODEL.predict(vector)[0]
    return prediction, float(max(MODEL.predict_proba(vector)[0]))


def seed_weekly_history(cur, lift_ids, user_ids):
    cur.execute("SELECT COUNT(*) AS n FROM analysis_jobs WHERE accepted_at IS NOT NULL")
    if cur.fetchone()["n"]:
        return
    for asset, accepted, completed_at, _status, attempts in HISTORY:
        root_id = None
        for index, (attempt_status, features) in enumerate(attempts):
            stored = features if features is not None else {"legacy_without_features": True}
            retry_of = root_id if index else None
            attempt_count = index
            if attempt_status == "completed" and features is not None:
                prediction, probability = _leaf_result(features)
            else:
                prediction, probability = None, None
            finished = completed_at if attempt_status == "completed" else accepted + timedelta(minutes=3)
            cur.execute(
                """INSERT INTO analysis_jobs(lift_id,status,features_json,prediction,probability,accepted_at,retry_of,attempt_count,error,completed_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (lift_ids[asset], attempt_status, json.dumps(stored, ensure_ascii=False), prediction, probability,
                 accepted, retry_of, attempt_count, None if attempt_status == "completed" else "worker timeout",
                 finished),
            )
            if root_id is None:
                root_id = cur.lastrowid


if __name__ == "__main__":
    seed()
