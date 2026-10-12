from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel


class MetricPoint(BaseModel):
    ts: datetime
    value: float


class LogLine(BaseModel):
    ts: datetime
    service: str
    level: Literal["DEBUG", "INFO", "WARN", "ERROR"]
    message: str


class Deployment(BaseModel):
    minute: int
    service: str
    version: str
    commit: str
    message: str


class Effect(BaseModel):
    service: str
    metric: str
    shape: Literal["step", "ramp"] = "ramp"
    start: int
    end: int | None = None
    to: float


class LogRule(BaseModel):
    service: str
    start: int
    end: int | None = None
    level: Literal["DEBUG", "INFO", "WARN", "ERROR"]
    rate: float
    message: str


class Alert(BaseModel):
    service: str
    text: str


class GroundTruth(BaseModel):
    root_cause: str
    root_service: str | None = None
    decoys: list[str] = []


class IncidentSpec(BaseModel):
    id: str
    title: str
    seed: int
    duration_minutes: int
    incident_start: int
    alert: Alert
    ground_truth: GroundTruth
    deployments: list[Deployment] = []
    effects: list[Effect] = []
    logs: list[LogRule] = []