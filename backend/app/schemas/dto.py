"""Pydantic API 模式。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class StationOut(BaseModel):
    id: int
    code: str
    name: str
    lon: float
    lat: float
    elevation_m: float
    network: str

    class Config:
        from_attributes = True


class ScenarioOut(BaseModel):
    id: int
    key: str
    title: str
    description: str
    teaching_note: str
    true_lon: float
    true_lat: float
    true_depth_km: float
    true_origin_epoch: float
    data_version: str

    class Config:
        from_attributes = True


class PickOut(BaseModel):
    id: int
    station_code: str
    station_lon: float
    station_lat: float
    phase: str
    raw_time_epoch: Optional[float]
    raw_status: str
    true_time_epoch: float
    manual_time_epoch: Optional[float]
    manual_note: str
    manual_author: str
    manual_updated_at: Optional[datetime]

    # 供波形/表格使用的派生字段
    effective_time_epoch: Optional[float]  # COALESCE(manual, raw)
    effective_source: str                  # manual | raw | missing
    raw_minus_true_s: Optional[float]
    manual_minus_true_s: Optional[float]


class ManualPickIn(BaseModel):
    manual_time_epoch: Optional[float] = Field(
        default=None, description="人工修订到时；传 null 清除修订（不删除原始拾取）"
    )
    note: str = ""
    author: str = "student"


class LocateRequest(BaseModel):
    scenario_key: str
    phase: str = Field(pattern="^[PpSs]$", description="单次定位只允许单一震相")
    model_id: str
    robust: bool = False
    label: str = ""
    exclude_pick_ids: List[int] = Field(default_factory=list)


class RunSummary(BaseModel):
    id: int
    label: str
    phase: str
    model_id: str
    robust: bool
    locatable: bool
    status: str
    reason: Optional[str]
    n_used: int
    dof: int
    lon: Optional[float]
    lat: Optional[float]
    depth_km: Optional[float]
    origin_time_epoch: Optional[float]
    rms_s: Optional[float]
    max_abs_residual_s: Optional[float]
    data_version: str
    pick_data_version: str
    created_at: datetime

    class Config:
        from_attributes = True


class RunDetail(RunSummary):
    residuals: List[dict]
    uncertainty: Optional[dict]
    geometry: Optional[dict]
    truth: Optional[dict]
    warnings: List[str]
    pick_schema_version: str
    app_version: str
    input_snapshot: List[dict]
    excludes: List[int]


# —— 候选解对照（只读历史，不重算）——

class CompareSide(BaseModel):
    id: int
    label: str
    phase: str
    model_id: str
    robust: bool
    locatable: bool
    status: str
    reason: Optional[str]
    lon: Optional[float]
    lat: Optional[float]
    depth_km: Optional[float]
    origin_time_epoch: Optional[float]
    rms_s: Optional[float]
    max_abs_residual_s: Optional[float]
    uncertainty: Optional[dict]
    pick_data_version: str
    data_version: str
    excludes: List[int]
    created_at: datetime


class CompareMetrics(BaseModel):
    # A 相对 B 的差异；任一边不可定位时全部为 null（不可比较）
    horizontal_distance_km: Optional[float]
    horizontal_dx_km: Optional[float]
    horizontal_dy_km: Optional[float]
    bearing_deg: Optional[float]
    depth_delta_km: Optional[float]
    origin_time_delta_s: Optional[float]
    rms_delta_s: Optional[float]
    max_abs_residual_delta_s: Optional[float]


class CompareInputs(BaseModel):
    n_used_a: int
    n_used_b: int
    used_only_a: List[int]
    used_only_b: List[int]
    used_both: List[int]
    pick_data_version_a: str
    pick_data_version_b: str
    pick_versions_differ: bool
    robust_a: bool
    robust_b: bool


class StationComparisonRow(BaseModel):
    pick_id: int
    station_code: Optional[str]
    phase: Optional[str]
    time_source_a: Optional[str]
    time_source_b: Optional[str]
    raw_status_a: Optional[str]
    raw_status_b: Optional[str]
    observed_epoch_a: Optional[float]
    observed_epoch_b: Optional[float]
    observed_delta_s: Optional[float]
    residual_s_a: Optional[float]
    residual_s_b: Optional[float]
    residual_delta_s: Optional[float]
    flag_a: Optional[str]
    flag_b: Optional[str]
    status_a: str            # used | excluded | missing
    status_b: str
    used_a: bool
    used_b: bool


class RunComparison(BaseModel):
    run_a: CompareSide
    run_b: CompareSide
    same_model: bool
    model_differs: bool
    model_note: str
    both_locatable: bool
    not_locatable_reasons: List[str]
    not_comparable_reason: Optional[str]
    metrics: CompareMetrics
    inputs: CompareInputs
    station_comparison: List[StationComparisonRow]


class WaveformOut(BaseModel):
    station_code: str
    channel: str
    starttime_epoch: float
    sampling_rate: float
    # 为绘图降采样后的数组
    times_s: List[float]
    counts: List[float]
    picks: List[dict]
