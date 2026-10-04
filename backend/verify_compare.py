"""端到端验证候选解对照接口（验收场景）。

用法：cd backend && python3 verify_compare.py
（TestClient 以 context manager 方式启动，触发与真实 uvicorn 相同的启动播种；
脚本幂等：直接在开发库上追加候选解，不删除已有数据。）
"""
from fastapi.testclient import TestClient

from app.main import app


def run_tests():
    with TestClient(app) as c:
        def post(path, body):
            r = c.post(path, json=body)
            if r.status_code >= 400:
                raise AssertionError(f"{path} -> {r.status_code} {r.text}")
            return r.json()

        # 1) nominal：先保存一个 P 解
        r1 = post("/api/scenarios/locate", {
            "scenario_key": "nominal", "phase": "P",
            "model_id": "homog-crust-6.0-3.46-v1", "label": "A 原始P",
        })
        print("run1:", r1["id"], r1["locatable"], r1["lon"], r1["lat"], "rms", r1["rms_s"])

        # 找到一个残差最大的台站做人工修订
        target = max(r1["residuals"], key=lambda x: abs(x["residual_s"]))
        print("修订 pick", target["pick_id"], target["station_code"],
              "当前残差", target["residual_s"], "向理论到时方向修订 0.4s")
        new_t = target["observed_epoch"] - (0.4 if target["residual_s"] > 0 else -0.4)
        rr = c.patch(f"/api/scenarios/picks/{target['pick_id']}",
                     json={"manual_time_epoch": round(new_t, 3),
                           "note": "test", "author": "tester"})
        assert rr.status_code == 200, rr.text

        # 修订后再保存 P 解
        r2 = post("/api/scenarios/locate", {
            "scenario_key": "nominal", "phase": "P",
            "model_id": "homog-crust-6.0-3.46-v1", "label": "B 修订P",
        })
        print("run2:", r2["id"], r2["locatable"], r2["lon"], r2["lat"], "rms", r2["rms_s"])

        cmp_ = post("/api/scenarios/runs/compare",
                    {"run_a_id": r1["id"], "run_b_id": r2["id"]})
        print("\n== 人工修订前后 P 解对照 ==")
        print("pick_version_differs:", cmp_["pick_version_differs"],
              "model_differs:", cmp_["model_differs"])
        print("水平距离 km:", cmp_["horizontal_distance_km"])
        print("深度差:", cmp_["depth_delta_km"], "时刻差:",
              cmp_["origin_time_delta_s"], "RMS差:", cmp_["rms_delta_s"])
        chg = next(x for x in cmp_["station_changes"]
                   if x["station_code"] == target["station_code"])
        print("修订台站 Δ观测到时:", chg["observed_delta_s"],
              "Δ残差:", chg["residual_delta_s"])
        print("notes:")
        for n in cmp_["notes"]:
            print("  -", n)
        assert cmp_["pick_version_differs"] is True
        assert cmp_["model_differs"] is False
        assert cmp_["horizontal_distance_km"] is not None
        assert abs(chg["observed_delta_s"]
                   - round(new_t - target["observed_epoch"], 3)) < 1e-6
        assert chg["status_a"] == "located" and chg["status_b"] == "located"

        # 2) 不同模型的 P 解
        r3 = post("/api/scenarios/locate", {
            "scenario_key": "nominal", "phase": "P",
            "model_id": "homog-crust-5.5-3.18-v1", "label": "B 慢速模型P",
        })
        cmpm = post("/api/scenarios/runs/compare",
                    {"run_a_id": r2["id"], "run_b_id": r3["id"]})
        print("\n== 不同模型 P 解 ==")
        print("model_differs:", cmpm["model_differs"], "| notes 含模型不同:",
              any("不同速度模型" in n for n in cmpm["notes"]))
        assert cmpm["model_differs"] is True
        assert any("不同速度模型" in n for n in cmpm["notes"])
        assert cmpm["side_b"]["model_id"] == "homog-crust-5.5-3.18-v1"

        # 3) P 与 S 不能混为一次对照
        s1 = post("/api/scenarios/locate", {
            "scenario_key": "nominal", "phase": "S",
            "model_id": "homog-crust-6.0-3.46-v1", "label": "S解",
        })
        r = c.post("/api/scenarios/runs/compare",
                   json={"run_a_id": r1["id"], "run_b_id": s1["id"]})
        print("\nP vs S ->", r.status_code, r.json()["detail"][:60])
        assert r.status_code == 400 and "震相" in r.json()["detail"]

        # 4) 不同案例不能对照
        o1 = post("/api/scenarios/locate", {
            "scenario_key": "outlier", "phase": "P",
            "model_id": "homog-crust-6.0-3.46-v1",
        })
        r = c.post("/api/scenarios/runs/compare",
                   json={"run_a_id": r1["id"], "run_b_id": o1["id"]})
        print("nominal vs outlier ->", r.status_code, r.json()["detail"][:60])
        assert r.status_code == 400 and "案例" in r.json()["detail"]

        # 5) sparse：不可定位结果参与对照，坐标差为 null，原因保留
        sp = post("/api/scenarios/locate", {
            "scenario_key": "sparse", "phase": "P",
            "model_id": "homog-crust-6.0-3.46-v1",
        })
        assert sp["locatable"] is False
        sp2 = post("/api/scenarios/locate", {
            "scenario_key": "sparse", "phase": "P",
            "model_id": "homog-crust-5.5-3.18-v1",
        })
        cmps = post("/api/scenarios/runs/compare",
                    {"run_a_id": sp["id"], "run_b_id": sp2["id"]})
        print("\n== 不可定位对照 ==")
        print("reason A:", cmps["side_a"]["reason"][:50])
        print("horiz/depth/t0/rms:", cmps["horizontal_distance_km"],
              cmps["depth_delta_km"], cmps["origin_time_delta_s"],
              cmps["rms_delta_s"])
        print("note:", cmps["notes"][0][:60])
        assert cmps["horizontal_distance_km"] is None
        assert cmps["depth_delta_km"] is None
        assert cmps["origin_time_delta_s"] is None
        assert cmps["rms_delta_s"] is None
        assert cmps["side_a"]["reason"] and "不可定位" in cmps["notes"][0]

        # 6) 同一条记录不能与自己对照
        r = c.post("/api/scenarios/runs/compare",
                   json={"run_a_id": r1["id"], "run_b_id": r1["id"]})
        assert r.status_code == 400
        print("\nself compare ->", r.status_code)

        # 7) 排除台站场景：outlier 排除一个台站前后
        exc0 = post("/api/scenarios/locate", {
            "scenario_key": "outlier", "phase": "P",
            "model_id": "homog-crust-6.0-3.46-v1", "label": "outlier全台",
        })
        pick_ids = [s["pick_id"] for s in exc0["input_snapshot"]
                    if not s["excluded"]]
        exc1 = post("/api/scenarios/locate", {
            "scenario_key": "outlier", "phase": "P",
            "model_id": "homog-crust-6.0-3.46-v1", "label": "outlier排除",
            "exclude_pick_ids": pick_ids[:1],
        })
        cmpe = post("/api/scenarios/runs/compare",
                    {"run_a_id": exc0["id"], "run_b_id": exc1["id"]})
        exrow = next(x for x in cmpe["station_changes"]
                     if x["status_b"] == "excluded")
        print("\n排除台站行:", exrow["station_code"],
              exrow["status_a"], exrow["status_b"],
              "resA:", exrow["residual_a_s"], "resB:", exrow["residual_b_s"])
        assert exrow["status_a"] == "located" and exrow["residual_b_s"] is None
        assert cmpe["side_b"]["excluded_station_codes"] == [exrow["station_code"]]

        print("\n全部验收断言通过 ✔")


if __name__ == "__main__":
    run_tests()
