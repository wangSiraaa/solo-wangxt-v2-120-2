"""候选解对照的单元测试（纯函数层，不依赖数据库/HTTP）。

运行：cd backend && python3 -m pytest tests/test_comparison.py
（无 pytest 时也可直接 python tests/test_comparison.py）
"""
from __future__ import annotations

import math
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.comparison import (  # noqa: E402
    build_station_comparison,
    compare_runs,
    horizontal_distance_km,
)


def _snap(pid, code, phase="P", eff=100.0, source="raw", excluded=False, status="ok"):
    return {
        "pick_id": pid, "station_code": code, "phase": phase,
        "effective_time_epoch": eff, "time_source": source,
        "raw_status": status, "excluded": excluded,
    }


def _res(pid, code, rv, phase="P", flag="ok"):
    return {"pick_id": pid, "station_code": code, "phase": phase,
            "residual_s": rv, "flag": flag}


def _run(
    id=1, locatable=True, phase="P", model_id="m-v1",
    lon=103.8, lat=30.05, depth=10.0, origin=1000.0, rms=0.2,
    max_abs=0.3, residuals=None, snapshot=None, excludes=None,
    pick_data_version="hash1", robust=False, reason=None,
):
    return SimpleNamespace(
        id=id, label=f"run{id}", phase=phase, model_id=model_id,
        robust=robust, locatable=locatable,
        status="located" if locatable else "insufficient_data",
        reason=reason, lon=lon, lat=lat, depth_km=depth,
        origin_time_epoch=origin, rms_s=rms, max_abs_residual_s=max_abs,
        residuals=residuals or [], uncertainty=None,
        input_snapshot=snapshot or [], excludes=excludes or [],
        data_version="d1", pick_data_version=pick_data_version,
        created_at=None,
    )


# —— 几何 ——

def test_horizontal_distance_known_offset():
    # 1° 纬度 ≈ 111.19 km
    d = horizontal_distance_km(103.8, 30.0, 103.8, 31.0)
    assert abs(d - 111.19) < 0.2


def test_distance_components_and_bearing():
    a = _run(id=1, lon=103.9, lat=30.1)   # A 在 B 的东北方向
    b = _run(id=2, lon=103.8, lat=30.0)
    out = compare_runs(a, b)
    m = out["metrics"]
    assert m["horizontal_distance_km"] > 10
    assert m["horizontal_dx_km"] > 0 and m["horizontal_dy_km"] > 0
    assert 0 < m["bearing_deg"] < 90  # A 相对 B 的方位为 NE


# —— 不可定位 ——

def test_both_not_locatable_all_metrics_null_and_reasons_kept():
    a = _run(id=1, locatable=False, lon=None, lat=None, depth=None,
             origin=None, rms=None, max_abs=None,
             reason="仅 3 个有效 P 到时，至少需要 4 个。")
    b = _run(id=2, locatable=False, lon=None, lat=None, depth=None,
             origin=None, rms=None, max_abs=None,
             reason="仅 3 个有效 P 到时，至少需要 4 个。")
    out = compare_runs(a, b)
    assert out["both_locatable"] is False
    assert all(v is None for v in out["metrics"].values())
    assert len(out["not_locatable_reasons"]) == 2
    assert out["not_comparable_reason"] is not None
    # 快照仍可对照
    assert out["station_comparison"] == []


def test_one_not_locatable_metrics_null():
    a = _run(id=1)
    b = _run(id=2, locatable=False, lon=None, lat=None, depth=None,
             origin=None, rms=None, max_abs=None, reason="台站不足")
    out = compare_runs(a, b)
    assert out["both_locatable"] is False
    assert out["metrics"]["horizontal_distance_km"] is None
    assert out["metrics"]["depth_delta_km"] is None
    assert len(out["not_locatable_reasons"]) == 1
    assert "B" in out["not_locatable_reasons"][0]


# —— 逐台站 ——

def test_station_residual_delta_and_manual_revision():
    snap_a = [_snap(1, "S1", eff=100.0, source="manual"),
              _snap(2, "S2", eff=200.0)]
    snap_b = [_snap(1, "S1", eff=102.5, source="raw"),
              _snap(2, "S2", eff=200.0)]
    res_a = [_res(1, "S1", -0.05), _res(2, "S2", 0.10)]
    res_b = [_res(1, "S1", 2.45, flag="suspect"), _res(2, "S2", 0.10)]
    a = _run(id=1, residuals=res_a, snapshot=snap_a, pick_data_version="h2")
    b = _run(id=2, residuals=res_b, snapshot=snap_b, pick_data_version="h1")
    out = compare_runs(a, b)
    rows = {r["pick_id"]: r for r in out["station_comparison"]}
    r1 = rows[1]
    assert r1["time_source_a"] == "manual"
    assert r1["time_source_b"] == "raw"
    assert abs(r1["observed_delta_s"] - (-2.5)) < 1e-9
    assert abs(r1["residual_delta_s"] - (-2.5)) < 1e-9
    assert r1["flag_b"] == "suspect" and r1["flag_a"] == "ok"
    assert out["inputs"]["pick_versions_differ"] is True


def test_excluded_and_missing_station_status():
    rows = build_station_comparison(
        snapshot_a=[_snap(1, "S1"), _snap(2, "S2", eff=None, source="missing")],
        residual_a=[_res(1, "S1", 0.1)],
        snapshot_b=[_snap(1, "S1"), _snap(2, "S2", excluded=True, eff=200.0)],
        residual_b=[_res(1, "S1", 0.2)],
        excludes_a=[], excludes_b=[2],
    )
    by = {r["pick_id"]: r for r in rows}
    assert by[1]["status_a"] == "used" and by[1]["status_b"] == "used"
    assert by[2]["status_a"] == "missing"
    assert by[2]["status_b"] == "excluded"
    assert by[2]["residual_s_a"] is None and by[2]["residual_s_b"] is None


def test_used_only_lists():
    snap_a = [_snap(1, "S1"), _snap(2, "S2")]
    snap_b = [_snap(1, "S1"), _snap(2, "S2", excluded=True, eff=200.0)]
    a = _run(id=1, residuals=[_res(1, "S1", 0.1), _res(2, "S2", 0.2)],
             snapshot=snap_a)
    b = _run(id=2, residuals=[_res(1, "S1", 0.3)], snapshot=snap_b, excludes=[2])
    out = compare_runs(a, b)
    assert out["inputs"]["used_only_a"] == [2]
    assert out["inputs"]["used_only_b"] == []
    assert out["inputs"]["n_used_a"] == 2 and out["inputs"]["n_used_b"] == 1


# —— 模型差异 ——

def test_different_model_flagged():
    a = _run(id=1, model_id="homog-crust-6.0-3.46-v1")
    b = _run(id=2, model_id="homog-crust-5.5-3.18-v1")
    out = compare_runs(a, b)
    assert out["model_differs"] is True and out["same_model"] is False
    assert "不同速度模型" in out["model_note"]


def test_signed_deltas():
    a = _run(id=1, depth=12.0, origin=1001.0, rms=0.1)
    b = _run(id=2, depth=10.0, origin=1000.0, rms=0.3)
    m = compare_runs(a, b)["metrics"]
    assert m["depth_delta_km"] == 2.0
    assert m["origin_time_delta_s"] == 1.0
    assert m["rms_delta_s"] == -0.2


def _run_all_tests():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == "__main__":
    _run_all_tests()
