"""Load and validate config.yaml and secrets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent

Perf = Literal["ultraBullet", "bullet", "blitz", "rapid", "classical", "correspondence"]


class LichessCfg(BaseModel):
    username: str
    review_study_id: str | None = None


class BudgetCfg(BaseModel):
    daily_minutes: int = 20
    games_per_week: int = 3
    weekend_block_minutes: int = 30


class TrainingCfg(BaseModel):
    main_perf: Perf = "rapid"
    tracked_perfs: list[Perf] = Field(default_factory=lambda: ["rapid", "classical", "blitz"])
    budget: BudgetCfg = Field(default_factory=BudgetCfg)
    focus_duration_weeks: int = 2


class EngineCfg(BaseModel):
    binary: str = "stockfish"
    version: str = "auto"
    nodes_per_position: int = 1_000_000
    threads: int = 2
    hash_mb: int = 256


class AnalysisCfg(BaseModel):
    only_perfs: list[Perf] = Field(default_factory=lambda: ["rapid", "classical"])
    min_plies: int = 20
    since: int | None = None
    time_pressure_fraction: float = 0.10
    thresholds: tuple[float, float, float] = (5.0, 10.0, 15.0)


class ReviewCfg(BaseModel):
    boxes_days: list[int] = Field(default_factory=lambda: [1, 3, 7, 14, 30])
    max_due_per_day: int = 5
    max_chapters: int = 60


class CoachCfg(BaseModel):
    language: str = "ru"


class DashboardCfg(BaseModel):
    public: bool = True


class Config(BaseModel):
    lichess: LichessCfg
    training: TrainingCfg = Field(default_factory=TrainingCfg)
    engine: EngineCfg = Field(default_factory=EngineCfg)
    analysis: AnalysisCfg = Field(default_factory=AnalysisCfg)
    review: ReviewCfg = Field(default_factory=ReviewCfg)
    coach: CoachCfg = Field(default_factory=CoachCfg)
    dashboard: DashboardCfg = Field(default_factory=DashboardCfg)


def load_config(path: Path | None = None) -> Config:
    path = path or ROOT / "config.yaml"
    with path.open(encoding="utf-8") as f:
        return Config.model_validate(yaml.safe_load(f))


def load_token(env_file: Path | None = None) -> str | None:
    """LICHESS_TOKEN from the environment, falling back to a gitignored .env file."""
    token = os.environ.get("LICHESS_TOKEN")
    if token:
        return token.strip()
    env_file = env_file or ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "LICHESS_TOKEN":
                return value.strip().strip("'\"") or None
    return None
