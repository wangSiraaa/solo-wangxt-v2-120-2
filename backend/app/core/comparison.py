"""两个已保存候选解（LocationRun）的只读对照计算。

设计原则
--------
* **只读历史、绝不重算**：所有量都直接取自两条 run 保存时的坐标与残差
  （residuals / input_snapshot / excludes），即使其中一条已因当前拾取被
  修订而"过期"，对照呈现的仍是当时保存的结果。
* **同案例、同震相才可比**：由路由层先行校验（P 与 S、不同案例物理上不
  是同一反演问题），本模块假定两边可比。
* **不可定位不产生假坐标差**：任一边 locatable=false 时，水平距离、深度/
  发震时刻/RMS 差一律为 null，并附上各自保存的 reason；只有逐台站输入
  （排除与否、到时）与残差表仍可对照，供讨论"为什么没解出来"。

P、S 不会出现在同一对照中，因此残差按 pick_id（同一案例同一台站同一震相
的拾取主键）匹配，避免台站同名而震相不同的误配。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from .geo import project_km


def _round(v: Optional[float], ndigits: int = 3) -> Optional[float]:
    return None if v is None else round(float(v), ndigits)


def horizontal_distance_km(
    lon1: float, lat1: float, lon2: float, lat2: float,
) -> float:
    """两点水平距离：局部切平面投影（与定位求解同一投影，量级一致）。
    教学区域约 0.5° 见方，与大圆距离差异远小于速度模型误差（见 geo.py）。"""
    dx, dy = project_km(lon2, lat2, lon1, lat1)
    return math.hypot(dx, dy)


def _used_pick_ids(snapshot: Sequence[dict], excludes: Sequence[int]) -> set[int]:
    excl = set(excludes or [])
    return {
        int(s["pick_id"]) for s in (snapshot or [])
        if s.get("effective_time_epoch") is not None and not s.get("excluded")
        and int(s.get("pick_id", -1)) not in excl
    }


def _snapshot_index(snapshot: Sequence[dict]) -> Dict[int, dict]:
    return {int(s["pick_id"]): s for s in (snapshot or []) if s.get("pick_id") is not None}


def _residual_index(residuals: Sequence[dict]) -> Dict[int, dict]:
    return {int(r["pick_id"]): r for r in (residuals or []) if r.get("pick_id") is not None}


def _signed_delta(a: Optional[float], b: Optional[float],
                  ndigits: int = 3) -> Optional[float]:
    """a − b（结果 a 相对基准 b 的变化量）；任一缺测则不可比较。"""
    if a is None or b is None:
        return None
    return round(float(a) - float(b), ndigits)


def build_station_comparison(
    snapshot_a: Sequence[dict],
    residual_a: Sequence[dict],
    snapshot_b: Sequence[dict],
    residual_b: Sequence[dict],
    excludes_a: Sequence[int],
    excludes_b: Sequence[int],
) -> List[dict]:
    """逐台站对照表，按 pick_id 并集构造。

    每行给出两边保存的观测到时（取自**保存的快照**，不查当前拾取）、
    残差（取自**保存的残差表**）、到时来源(raw/manual)以及使用/排除/缺测
    状态，并计算 残差A−残差B、观测到时A−B。
    """
    snap_a = _snapshot_index(snapshot_a)
    snap_b = _snapshot_index(snapshot_b)
    res_a = _residual_index(residual_a)
    res_b = _residual_index(residual_b)
    excl_a, excl_b = set(excludes_a or []), set(excludes_b or [])
    used_a_all = {
        i for i, s in snap_a.items()
        if s.get("effective_time_epoch") is not None and not s.get("excluded")
    } - excl_a
    used_b_all = {
        i for i, s in snap_b.items()
        if s.get("effective_time_epoch") is not None and not s.get("excluded")
    } - excl_b

    all_ids = sorted(set(snap_a) | set(snap_b))
    rows: List[dict] = []
    for pid in all_ids:
        sa, sb = snap_a.get(pid), snap_b.get(pid)
        ra, rb = res_a.get(pid), res_b.get(pid)
        # 同一案例同一 pick_id 即同一台站同一震相；理论上 sa/sb 的台站码一致，
        # 取任一存在者即可，差异时以前者为准并保留两边信息。
        code = (sa or sb).get("station_code")
        phase = (sa or sb).get("phase")

        obs_a = sa.get("effective_time_epoch") if sa else None
        obs_b = sb.get("effective_time_epoch") if sb else None
        src_a = sa.get("time_source") if sa else None
        src_b = sb.get("time_source") if sb else None
        raw_status_a = sa.get("raw_status") if sa else None
        raw_status_b = sb.get("raw_status") if sb else None

        used_a = pid in used_a_all
        used_b = pid in used_b_all

        # 快照里 excluded 已含用户排除标记；excludes 列表再兜底一次
        excluded_a = bool((sa or {}).get("excluded")) or pid in excl_a
        excluded_b = bool((sb or {}).get("excluded")) or pid in excl_b
        missing_a = obs_a is None
        missing_b = obs_b is None

        def _status(missing: bool, excluded: bool) -> str:
            if excluded:
                return "excluded"
            if missing:
                return "missing"
            return "used"

        rv_a = ra.get("residual_s") if ra else None
        rv_b = rb.get("residual_s") if rb else None

        rows.append({
            "pick_id": pid,
            "station_code": code,
            "phase": phase,
            "time_source_a": src_a,
            "time_source_b": src_b,
            "raw_status_a": raw_status_a,
            "raw_status_b": raw_status_b,
            "observed_epoch_a": obs_a,
            "observed_epoch_b": obs_b,
            "observed_delta_s": _signed_delta(obs_a, obs_b),
            "residual_s_a": rv_a,
            "residual_s_b": rv_b,
            "residual_delta_s": _signed_delta(rv_a, rv_b),
            "flag_a": (ra.get("flag") if ra else None),
            "flag_b": (rb.get("flag") if rb else None),
            "status_a": _status(missing_a, excluded_a),
            "status_b": _status(missing_b, excluded_b),
            "used_a": used_a,
            "used_b": used_b,
        })
    # 残差变化幅度大者排前，都没有残差的排后
    rows.sort(key=lambda r: (
        -(abs(r["residual_delta_s"]) if r["residual_delta_s"] is not None else -1.0),
        r["station_code"] or "",
    ))
    return rows


def compare_runs(run_a: Any, run_b: Any) -> dict:
    """构造两条 LocationRun（ORM 对象或等价属性对象）的对照结果。

    调用方负责保证 run_a / run_b 非空、同案例、同震相。
    """
    loc_a, loc_b = bool(run_a.locatable), bool(run_b.locatable)
    both = loc_a and loc_b

    not_loc_reasons: List[str] = []
    if not loc_a and run_a.reason:
        not_loc_reasons.append(f"候选 A（#{run_a.id}）不可定位：{run_a.reason}")
    if not loc_b and run_b.reason:
        not_loc_reasons.append(f"候选 B（#{run_b.id}）不可定位：{run_b.reason}")

    if both:
        horiz_km = _round(horizontal_distance_km(
            run_a.lon, run_a.lat, run_b.lon, run_b.lat))
        # 分解到东西/南北分量（B→A 的偏移，基准为 B）
        dx, dy = project_km(run_a.lon, run_a.lat, run_b.lon, run_b.lat)
        dx_km, dy_km = _round(dx), _round(dy)
        # 方位角：A 相对 B 的方向（自正北顺时针）
        bearing = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0 if (dx or dy) else None
        depth_delta = _signed_delta(run_a.depth_km, run_b.depth_km)
        origin_delta = _signed_delta(run_a.origin_time_epoch, run_b.origin_time_epoch)
        rms_delta = _signed_delta(run_a.rms_s, run_b.rms_s)
        max_abs_delta = _signed_delta(run_a.max_abs_residual_s, run_b.max_abs_residual_s)
        not_comparable_reason: Optional[str] = None
    else:
        horiz_km = dx_km = dy_km = bearing = None
        depth_delta = origin_delta = rms_delta = max_abs_delta = None
        not_comparable_reason = (
            "至少一个候选解不可定位，未保存坐标/拟合量，"
            "水平位置、深度、发震时刻与 RMS 的数值差不可比较；"
            "下方保留各自的不可定位原因，并仍可对照所用拾取与排除情况。"
        )

    used_a = _used_pick_ids(run_a.input_snapshot, run_a.excludes)
    used_b = _used_pick_ids(run_b.input_snapshot, run_b.excludes)

    station_rows = build_station_comparison(
        run_a.input_snapshot, run_a.residuals,
        run_b.input_snapshot, run_b.residuals,
        run_a.excludes, run_b.excludes,
    )

    model_differs = run_a.model_id != run_b.model_id

    return {
        "run_a": _side_meta(run_a),
        "run_b": _side_meta(run_b),
        "same_model": not model_differs,
        "model_differs": model_differs,
        "model_note": (
            f"两个候选解采用不同速度模型：A={run_a.model_id}，B={run_b.model_id}；"
            "位置/时刻差异中包含模型差异的贡献，不能全部归因于拾取变化。"
            if model_differs else
            "两个候选解采用同一速度模型，差异主要来自拾取内容、排除台站或拟合方式。"
        ),
        "both_locatable": both,
        "not_locatable_reasons": not_loc_reasons,
        "not_comparable_reason": not_comparable_reason,
        "metrics": {
            "horizontal_distance_km": horiz_km,
            "horizontal_dx_km": dx_km,   # 东西分量（A 相对 B，向东为正）
            "horizontal_dy_km": dy_km,   # 南北分量（向北为正）
            "bearing_deg": _round(bearing, 1),
            "depth_delta_km": depth_delta,       # A − B
            "origin_time_delta_s": origin_delta,
            "rms_delta_s": rms_delta,
            "max_abs_residual_delta_s": max_abs_delta,
        },
        "inputs": {
            "n_used_a": len(used_a),
            "n_used_b": len(used_b),
            "used_only_a": sorted(used_a - used_b),
            "used_only_b": sorted(used_b - used_a),
            "used_both": sorted(used_a & used_b),
            "pick_data_version_a": run_a.pick_data_version,
            "pick_data_version_b": run_b.pick_data_version,
            "pick_versions_differ": run_a.pick_data_version != run_b.pick_data_version,
            "robust_a": bool(run_a.robust),
            "robust_b": bool(run_b.robust),
        },
        "station_comparison": station_rows,
    }


def _side_meta(run: Any) -> dict:
    return {
        "id": run.id,
        "label": run.label,
        "phase": run.phase,
        "model_id": run.model_id,
        "robust": bool(run.robust),
        "locatable": bool(run.locatable),
        "status": run.status,
        "reason": run.reason,
        "lon": run.lon,
        "lat": run.lat,
        "depth_km": run.depth_km,
        "origin_time_epoch": run.origin_time_epoch,
        "rms_s": run.rms_s,
        "max_abs_residual_s": run.max_abs_residual_s,
        "uncertainty": run.uncertainty,
        "pick_data_version": run.pick_data_version,
        "data_version": run.data_version,
        "excludes": list(run.excludes or []),
        "created_at": run.created_at,
    }
