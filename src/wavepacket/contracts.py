"""Public wire records shared by OpenAPI, stored artifacts and the browser."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import SimulationConfig

RunStatus = Literal["queued", "running", "finalizing", "completed", "cancelled", "failed"]
ACTIVE_STATUSES = frozenset({"queued", "running", "finalizing"})
TERMINAL_STATUSES = frozenset({"completed", "cancelled", "failed"})
Values = list[float] | list[list[float]]
Measurements = dict[str, float | None]


class UnitScalesRecord(BaseModel):
    length_nm: float
    time_fs: float
    energy_ev: float
    momentum_si: float
    momentum_inverse_nm: float
    density_per_nm: float
    density_per_nm2: float
    current_per_fs: float
    current_per_nm_fs: float
    mass: Literal["electron"] = "electron"
    note: str = "Display conversions only; numerical core uses hbar=m=1."


class MeasurementValidity(BaseModel):
    conditional_status: Literal["resolved", "below_reporting_floor", "numerically_zero"]
    reporting_floor: float
    initial_norm: float
    reason: str | None = None
    uncertainty_status: (
        Literal["unavailable", "boundary_or_nyquist_contaminated", "localized_line_approximation"]
        | None
    ) = None
    uncertainty_reason: str | None = None


class EvidenceRecord(BaseModel):
    configuration_sha256: str
    status: Literal["report_required", "checked", "failed", "stale"]
    check_ids: list[str]
    scope: str
    conditions: dict[str, Any]
    report_sha256: str | None = None
    measured_conditions: dict[str, Any] | None = None
    reference_configuration_sha256: str | None = None
    metrics: dict[str, Any] | None = None


class PresetRecord(BaseModel):
    id: str
    title: str
    name: str
    dimension: Literal[1, 2]
    scientific_question: str
    question: str
    evidence: str
    validation_status: str
    limitations: list[str]
    config: SimulationConfig
    evidence_record: EvidenceRecord


class EvidenceFreshness(BaseModel):
    source_match: bool | None
    mismatched_sources: list[str]
    report_sha256: str
    evidence_path: str


class ValidationCase(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    status: str
    evidence: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    criteria: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ValidationSummary(BaseModel):
    passed: int
    failed: int
    total: int


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="allow")
    suite: Literal["quick", "full"]
    status: str
    cases: list[ValidationCase] = Field(default_factory=list)
    summary: ValidationSummary | None = None
    created_utc: str | None = None
    note: str | None = None
    limitations: list[str] = Field(default_factory=list)
    freshness: EvidenceFreshness | None = None


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal[1, 2] = 2
    id: str
    status: RunStatus
    progress: float = 0.0
    created_at: str
    config: SimulationConfig
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    owner: dict[str, Any] | None = None
    resources: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] | None = None
    scientific_status: str = "pending"
    report_status: str = "pending"


class ScreenProfile(BaseModel):
    x: float
    requested_x: float | None = None
    density_x: float
    y: list[float]
    current_integral: list[float]
    density: list[float]
    time: float
    definition: str
    quadrature: str
    current_location: str | None = None


class Frame(BaseModel):
    time: float
    dimension: Literal[1, 2]
    shape: list[int]
    axes: dict[str, list[float]]
    density: Values
    phase: Values
    potential: Values
    current_x: Values
    current_y: Values | None = None
    current_location: str
    observables: Measurements
    validity: MeasurementValidity | None = None
    step: int
    total_steps: int
    run_id: str | None = None
    config_sha256: str | None = None
    density_scale_max: float = 0.0
    density_scale_scope: Literal["running_max", "max_across_saved_frames"] = "running_max"
    screen: ScreenProfile | None = None
