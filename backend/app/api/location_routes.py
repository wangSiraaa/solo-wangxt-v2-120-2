"""定位：运行、列出候选解、读取详情、绑定版本与输入快照。"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.comparison import compare_runs
from ..core.config import APP_VERSION, DATA_VERSION, PICK_SCHEMA_VERSION
from ..core.location import Arrival, locate
from ..core.velocity import get_model
from ..database import get_db
from ..models.tables import LocationRun, Pick, Scenario
from ..schemas.dto import LocateRequest, RunComparison, RunDetail, RunSummary
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


@router.get("/runs/compare", response_model=RunComparison)
def compare_two_runs(
    a: int = Query(..., description="候选解 A 的 run id"),
    b: int = Query(..., description="候选解 B 的 run id"),
    db: Session = Depends(get_db),
):
    """候选解对照（只读历史记录，**不按当前拾取重算**）。

    仅允许同一案例、同一震相的两个已保存结果互相对照；P 与 S、不同案例
    属于不同反演问题，一律 400 拒绝。不可定位的结果保留原因，坐标类差值
    返回 null（不可比较），逐台站到时/残差/排除情况仍可对照。
    """
    if a == b:
        raise HTTPException(400, "请选择两个不同的候选解进行对照（A、B 不能相同）。")
    run_a = db.get(LocationRun, a)
    run_b = db.get(LocationRun, b)
    if run_a is None:
        raise HTTPException(404, f"候选解 #{a} 不存在")
    if run_b is None:
        raise HTTPException(404, f"候选解 #{b} 不存在")
    if run_a.scenario_id != run_b.scenario_id:
        raise HTTPException(
            400,
            f"两个候选解不属于同一案例（#{a} 属案例 {run_a.scenario_id}，"
            f"#{b} 属案例 {run_b.scenario_id}），不能混为一次对照。",
        )
    if run_a.phase != run_b.phase:
        raise HTTPException(
            400,
            f"震相不同：候选 #{a} 为 {run_a.phase} 波，候选 #{b} 为 {run_b.phase} 波。"
            "P、S 波速度与走时方程不同，严禁混为一次对照。",
        )
    return compare_runs(run_a, run_b)


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
