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


class CompareRequest(BaseModel):
    run_a_id: int = Field(description="基准候选解（A）的 run id")
    run_b_id: int = Field(description="对照候选解（B）的 run id；所有差值均为 B − A")


class CompareSide(BaseModel):
    """对照中一侧的只读历史信息（全部取自保存的 run 记录，不按当前拾取重算）。"""
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
    n_used: int
    pick_data_version: str
    excludes: List[int]
    excluded_station_codes: List[str]
    uncertainty: Optional[dict]
    created_at: datetime


class StationResidualChange(BaseModel):
    station_code: str
    # 两侧该台站的参与情况：located = 参与了该次反演并保存了残差；
    # excluded = 用户排除；missing = 无有效到时；not_locatable = 该次整体不可定位
    status_a: Optional[str]
    status_b: Optional[str]
    residual_a_s: Optional[float]
    residual_b_s: Optional[float]
    residual_delta_s: Optional[float]      # B − A
    observed_delta_s: Optional[float]      # 保存的观测到时差 B − A（如人工修订）
    used_a: bool
    used_b: bool


class RunComparison(BaseModel):
    comparable: bool                        # False = 案例/震相不允许组成一次对照
    notes: List[str]                        # 人类可读的限制与提示
    model_differs: bool
    pick_version_differs: bool
    robust_differs: bool
    scenario_key: str
    scenario_title: str
    phase: str
    side_a: CompareSide
    side_b: CompareSide
    # 以下差值均为 B − A；任一侧不可定位时为 null（前端显示「不可比较」）
    horizontal_distance_km: Optional[float]
    depth_delta_km: Optional[float]
    origin_time_delta_s: Optional[float]
    rms_delta_s: Optional[float]
    station_changes: List[StationResidualChange]


class WaveformOut(BaseModel):
    station_code: str
    channel: str
    starttime_epoch: float
    sampling_rate: float
    # 为绘图降采样后的数组
    times_s: List[float]
    counts: List[float]
    picks: List[dict]
