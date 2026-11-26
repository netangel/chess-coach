"""Pydantic schemas for derived per-game data (DESIGN.md §6)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .chessmath import CP_CLAMP, win_pct
from .review import ReviewState

Phase = Literal["opening", "middlegame", "endgame"]
Color = Literal["white", "black"]
MoveClassT = Literal["good", "inaccuracy", "mistake", "blunder"]


class EngineInfo(BaseModel):
    name: str
    version: str
    nodes: int


class PositionEval(BaseModel):
    """Engine evaluation of one position, from White's point of view."""

    cp: int | None = None
    mate: int | None = None
    terminal: Literal["white_won", "black_won", "draw"] | None = None  # game over, no engine
    best: str | None = None  # UCI
    pv: list[str] = Field(default_factory=list)  # UCI, best line

    def win_white(self) -> float:
        if self.terminal is not None:
            return {"white_won": 100.0, "black_won": 0.0, "draw": 50.0}[self.terminal]
        return win_pct(self.cp, self.mate)

    def cp_white_clamped(self) -> int:
        if self.terminal is not None:
            return {"white_won": CP_CLAMP, "black_won": -CP_CLAMP, "draw": 0}[self.terminal]
        if self.mate is not None:
            return CP_CLAMP if self.mate > 0 else -CP_CLAMP
        return max(-CP_CLAMP, min(CP_CLAMP, self.cp or 0))


class Ply(BaseModel):
    ply: int  # 1-based
    san: str
    uci: str
    byPlayer: bool
    cpBefore: int | None  # mover's point of view
    cpAfter: int | None
    mateBefore: int | None
    mateAfter: int | None
    winBefore: float
    winAfter: float
    winDrop: float
    bestSan: str | None
    bestUci: str | None
    pvSan: list[str] = Field(default_factory=list)  # only for flagged player moves
    cls: MoveClassT = Field(alias="class")
    clockLeft: float | None  # seconds after the move
    phase: Phase
    timePressure: bool
    missedWin: bool = False

    model_config = {"populate_by_name": True}


class CrossCheck(BaseModel):
    """Our analysis vs Lichess server analysis, for the player's moves."""

    plies: int
    evalMaeWin: float  # mean |win% ours - win% Lichess| after each ply (White POV, all plies)
    classAgreement: float  # share of player moves where our class == Lichess judgment
    ours: dict[str, int]
    lichess: dict[str, int]


class Summary(BaseModel):
    acpl: int
    inaccuracies: int
    mistakes: int
    blunders: int
    accuracy: float | None
    result: Literal["win", "loss", "draw"]
    maxAdvantageWin: float
    minWin: float
    missedWins: int


class GameAnalysis(BaseModel):
    gameId: str
    engine: EngineInfo
    params: dict
    playerColor: Color
    perf: str
    createdAt: int
    clockInitial: int | None = None
    clockIncrement: int | None = None
    opening: dict | None = None
    division: dict | None = None
    initialFen: str | None = None
    positions: list[PositionEval]
    plies: list[Ply]
    summary: Summary
    crossCheck: CrossCheck | None = None


class Mistake(BaseModel):
    id: str
    gameId: str
    perf: str
    ply: int
    url: str
    fen: str
    playerColor: Color
    played: str
    best: str | None
    pv: list[str]
    cls: MoveClassT = Field(alias="class")
    winBefore: float
    winDrop: float
    phase: Phase
    timePressure: bool
    missedWin: bool
    tags: list[str]
    gameCreatedAt: int
    createdAt: int
    review: ReviewState

    model_config = {"populate_by_name": True}
