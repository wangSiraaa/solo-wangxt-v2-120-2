"""定位：运行、列出候选解、读取详情、绑定版本与输入快照。"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import APP_VERSION, DATA_VERSION, PICK_SCHEMA_VERSION
from ..core.geo import haversine_km
from ..core.location import Arrival, locate
from ..core.velocity import get_model
from ..database import get_db
from ..models.tables import LocationRun, Pick, Scenario
from ..schemas.dto import (
    CompareRequest, CompareSide, LocateRequest, RunComparison, RunDetail,
    RunSummary, StationResidualChange,
)
from .waveforms import picks_version

router = APIRouter(prefix="/api/scenarios", tags=["location"])


def _effective_pick(p: Pick):
    if p.manual_time_epoch is not None:
        return p.manual_time_epoch, "manual"
    if p.raw_time_epoch is not None:
        return p.raw_time_epoch, "raw"
    return None, "missing"


@router.post("/locate", response_model=RunDetail)
def run_locate(req: LocateRequest, db: Session = Depends(get_db)):
    sc = db.scalar(select(Scenario).where(Scenario.key == req.scenario_key))
    if sc is None:
        raise HTTPException(404, f"案例 {req.scenario_key!r} 不存在")
    phase = req.phase.upper()
    try:
        model = get_model(req.model_id)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # —— 严格单一震相：只查询该震相的拾取，P/S 物理上不可能混入 ——
    rows = list(db.scalars(select(Pick).where(
        Pick.scenario_id == sc.id, Pick.phase == phase)))

    arrivals: List[Arrival] = []
    snapshot = []
    excluded = list(req.exclude_pick_ids)
    rejected_mix: list[str] = []  # 该震相表本就不会含别的震相；这里保留显式校验
    for p in rows:
        eff, source = _effective_pick(p)
        if p.phase != phase:
            rejected_mix.append(p.station.code)
            continue
        rec = {
            "pick_id": p.id, "station_code": p.station.code, "phase": p.phase,
            "effective_time_epoch": eff, "time_source": source,
            "raw_status": p.raw_status, "excluded": p.id in excluded,
        }
        snapshot.append(rec)
        if eff is None or p.id in excluded:
            continue
        arrivals.append(Arrival(
            station_code=p.station.code, lon=p.station.lon, lat=p.station.lat,
            time_epoch=eff, pick_id=p.id, time_source=source,
        ))

    if rejected_mix:
        raise HTTPException(400, f"检测到异震相拾取混入，已拒绝：{rejected_mix}")

    result = locate(
        arrivals, phase=phase, model=model, robust=req.robust,
        truth={
            "lon": sc.true_lon, "lat": sc.true_lat, "depth_km": sc.true_depth_km,
            "origin_epoch": sc.true_origin_epoch,
        },
    )
    pv = picks_version(req.scenario_key, db)

    run = LocationRun(
        scenario_id=sc.id,
        label=req.label or f"{phase} {'稳健' if req.robust else 'OLS'} {model.model_id.split('-v')[0]}",
        phase=phase, model_id=model.model_id, robust=req.robust,
        locatable=result.locatable, status=result.status, reason=result.reason,
        lon=result.lon, lat=result.lat, depth_km=result.depth_km,
        origin_time_epoch=result.origin_time_epoch,
        rms_s=result.rms_s, max_abs_residual_s=result.max_abs_residual_s,
        residuals=result.residuals, uncertainty=result.uncertainty,
        geometry=result.geometry, truth=result.truth, warnings=result.warnings,
        data_version=DATA_VERSION, pick_schema_version=PICK_SCHEMA_VERSION,
        app_version=APP_VERSION, pick_data_version=pv.pick_data_version,
        input_snapshot=snapshot, excludes=excluded,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return _detail(run)


@router.get("/{key}/runs", response_model=List[RunSummary])
def list_runs(key: str, db: Session = Depends(get_db)):
    sc = db.scalar(select(Scenario).where(Scenario.key == key))
    if sc is None:
        raise HTTPException(404, f"案例 {key!r} 不存在")
    rows = db.scalars(
        select(LocationRun).where(LocationRun.scenario_id == sc.id)
        .order_by(LocationRun.id.desc())).all()
    return [_summary(r) for r in rows]


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(LocationRun, run_id)
    if run is None:
        raise HTTPException(404, "定位记录不存在")
    return _detail(run)


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(LocationRun, run_id)
    if run is None:
        raise HTTPException(404, "定位记录不存在")
    db.delete(run)
    db.commit()
    return {"deleted": run_id}


@router.post("/runs/compare", response_model=RunComparison)
def compare_runs(req: CompareRequest, db: Session = Depends(get_db)):
    """两个已保存候选解的只读对照。

    * 只允许同一案例、同一震相：P 与 S、或不同案例不能组成一次对照（400）。
    * 所有量都取自两次 run **保存时**的快照与残差，不读取当前拾取、不重算。
    * 任一侧不可定位时保留其 reason，坐标/深度/时刻/RMS 差返回 null（不可比较）。
    """
    if req.run_a_id == req.run_b_id:
        raise HTTPException(400, "请选择两个不同的候选解进行对照。")
    run_a = db.get(LocationRun, req.run_a_id)
    run_b = db.get(LocationRun, req.run_b_id)
    if run_a is None or run_b is None:
        missing = req.run_a_id if run_a is None else req.run_b_id
        raise HTTPException(404, f"定位记录 {missing} 不存在")

    sc_a = run_a.scenario
    sc_b = run_b.scenario
    if sc_a.id != sc_b.id:
        raise HTTPException(
            400,
            f"不能跨案例对照：候选解 #{run_a.id} 属于案例「{sc_a.title}」，"
            f"候选解 #{run_b.id} 属于案例「{sc_b.title}」。"
            "一次对照必须选择同一案例的两个结果。",
        )
    if run_a.phase != run_b.phase:
        raise HTTPException(
            400,
            f"不能跨震相对照：候选解 #{run_a.id} 是 {run_a.phase} 震相，"
            f"候选解 #{run_b.id} 是 {run_b.phase} 震相。"
            "P、S 速度与残差含义不同，严禁混为一次对照。",
        )

    notes: List[str] = []
    if not run_a.locatable or not run_b.locatable:
        bad = [f"#{r.id}（{r.reason}）" for r in (run_a, run_b) if not r.locatable]
        notes.append(
            "存在不可定位的结果：" + "；".join(bad)
            + "。其原因予以保留，但坐标/深度/发震时刻/RMS 差无意义，显示为「不可比较」。"
        )
    model_differs = run_a.model_id != run_b.model_id
    if model_differs:
        notes.append(
            f"两个解采用不同速度模型（A: {run_a.model_id}，B: {run_b.model_id}），"
            "位置差异可能全部来自模型不同，不能归因于拾取修订。"
        )
    pick_version_differs = run_a.pick_data_version != run_b.pick_data_version
    if pick_version_differs:
        notes.append(
            "两个解保存于不同的拾取数据版本（输入拾取被人工修订/排除发生过变化），"
            "差异可结合各台站残差变化与观测到时变化解释。"
        )
    robust_differs = run_a.robust != run_b.robust
    if robust_differs:
        notes.append(
            f"拟合方式不同（A: {'稳健 soft_l1' if run_a.robust else '普通 OLS'}，"
            f"B: {'稳健 soft_l1' if run_b.robust else '普通 OLS'}），"
            "RMS 与各台站权重含义不完全相同。"
        )
    notes.append("对照为只读历史比对：直接读取两次保存的结果、快照与残差，不按当前拾取重算。")

    both_located = run_a.locatable and run_b.locatable
    if both_located:
        horiz = round(haversine_km(run_a.lon, run_a.lat, run_b.lon, run_b.lat), 3)
        depth_delta = round(run_b.depth_km - run_a.depth_km, 3)
        origin_delta = round(run_b.origin_time_epoch - run_a.origin_time_epoch, 3)
    else:
        horiz = depth_delta = origin_delta = None
    rms_delta = (round(run_b.rms_s - run_a.rms_s, 3)
                 if both_located and run_a.rms_s is not None and run_b.rms_s is not None
                 else None)

    station_changes = _station_changes(run_a, run_b)

    return RunComparison(
        comparable=True,
        notes=notes,
        model_differs=model_differs,
        pick_version_differs=pick_version_differs,
        robust_differs=robust_differs,
        scenario_key=sc_a.key,
        scenario_title=sc_a.title,
        phase=run_a.phase,
        side_a=_compare_side(run_a),
        side_b=_compare_side(run_b),
        horizontal_distance_km=horiz,
        depth_delta_km=depth_delta,
        origin_time_delta_s=origin_delta,
        rms_delta_s=rms_delta,
        station_changes=station_changes,
    )


def _compare_side(run: LocationRun) -> CompareSide:
    n_used = sum(1 for s in run.input_snapshot
                 if s.get("effective_time_epoch") is not None and not s.get("excluded"))
    excluded_codes = [s.get("station_code") for s in run.input_snapshot if s.get("excluded")]
    return CompareSide(
        id=run.id, label=run.label, phase=run.phase, model_id=run.model_id,
        robust=run.robust, locatable=run.locatable, status=run.status, reason=run.reason,
        lon=run.lon, lat=run.lat, depth_km=run.depth_km,
        origin_time_epoch=run.origin_time_epoch, rms_s=run.rms_s, n_used=n_used,
        pick_data_version=run.pick_data_version, excludes=list(run.excludes or []),
        excluded_station_codes=[c for c in excluded_codes if c],
        uncertainty=run.uncertainty, created_at=run.created_at,
    )


def _station_changes(run_a: LocationRun, run_b: LocationRun) -> List[StationResidualChange]:
    """逐台站残差变化。以两侧保存的 input_snapshot 取并集（pick_id → 台站），
    残差/观测到时都来自保存记录，不做任何重新计算。"""
    def snapshot_index(run: LocationRun) -> dict:
        out: dict = {}
        for s in run.input_snapshot or []:
            pid = s.get("pick_id")
            if pid is not None:
                out[pid] = s
        return out

    def residual_index(run: LocationRun) -> dict:
        return {r.get("pick_id"): r for r in (run.residuals or []) if r.get("pick_id") is not None}

    snap_a, snap_b = snapshot_index(run_a), snapshot_index(run_b)
    res_a, res_b = residual_index(run_a), residual_index(run_b)

    rows: List[StationResidualChange] = []
    for pid in sorted(set(snap_a) | set(snap_b)):
        sa, sb = snap_a.get(pid), snap_b.get(pid)
        code = (sa or sb).get("station_code")
        ra, rb = res_a.get(pid), res_b.get(pid)

        def status(snap, res, run):
            if not run.locatable:
                return "not_locatable"
            if res is not None:
                return "located"
            if snap is not None and snap.get("excluded"):
                return "excluded"
            return "missing"

        st_a = status(sa, ra, run_a)
        st_b = status(sb, rb, run_b)
        rv_a = ra.get("residual_s") if ra else None
        rv_b = rb.get("residual_s") if rb else None
        ob_a = sa.get("effective_time_epoch") if sa else None
        ob_b = sb.get("effective_time_epoch") if sb else None
        rows.append(StationResidualChange(
            station_code=code,
            status_a=st_a, status_b=st_b,
            residual_a_s=rv_a, residual_b_s=rv_b,
            residual_delta_s=(round(rv_b - rv_a, 3)
                              if rv_a is not None and rv_b is not None else None),
            observed_delta_s=(round(ob_b - ob_a, 3)
                              if ob_a is not None and ob_b is not None else None),
            used_a=st_a == "located", used_b=st_b == "located",
        ))

    def sort_key(row: StationResidualChange):
        # 有残差变化的行在前（按 |Δ| 降序）；任一侧未参与（排除/缺测/不可定位）
        # 因而无 Δ 可比的行沉到后面，最后按台站代码稳定排序。
        if row.residual_delta_s is None:
            return (1, 0.0, row.station_code or "")
        return (0, -abs(row.residual_delta_s), row.station_code or "")

    return sorted(rows, key=sort_key)


def _summary(run: LocationRun) -> RunSummary:
    n_used = sum(1 for s in run.input_snapshot
                 if s.get("effective_time_epoch") is not None and not s.get("excluded"))
    return RunSummary(
        id=run.id, label=run.label, phase=run.phase, model_id=run.model_id,
        robust=run.robust, locatable=run.locatable, status=run.status, reason=run.reason,
        n_used=n_used, dof=max(n_used - 4, 0),
        lon=run.lon, lat=run.lat, depth_km=run.depth_km,
        origin_time_epoch=run.origin_time_epoch, rms_s=run.rms_s,
        max_abs_residual_s=run.max_abs_residual_s,
        data_version=run.data_version, pick_data_version=run.pick_data_version,
        created_at=run.created_at,
    )


def _detail(run: LocationRun) -> RunDetail:
    kwargs = _summary(run).model_dump()
    kwargs.update(
        residuals=run.residuals, uncertainty=run.uncertainty,
        geometry=run.geometry, truth=run.truth, warnings=run.warnings,
        pick_schema_version=run.pick_schema_version, app_version=run.app_version,
        input_snapshot=run.input_snapshot, excludes=run.excludes,
    )
    return RunDetail(**kwargs)
