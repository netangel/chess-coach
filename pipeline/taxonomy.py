"""Load taxonomy.yaml into flat skill keys like `tactics.fork`."""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel

from .config import ROOT

TRAINING_URL = "https://lichess.org/training/{theme}"


class Skill(BaseModel):
    key: str
    lichess_theme: str | None = None
    lichess_url: str | None = None
    resources: list[dict] = []

    @property
    def url(self) -> str | None:
        if self.lichess_url:
            return self.lichess_url
        if self.lichess_theme:
            return TRAINING_URL.format(theme=self.lichess_theme)
        return None


@cache
def load_taxonomy(path: Path = ROOT / "taxonomy.yaml") -> dict[str, Skill]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    skills: dict[str, Skill] = {}
    for group, leaves in raw.items():
        for leaf, attrs in (leaves or {}).items():
            key = f"{group}.{leaf}"
            skills[key] = Skill(key=key, **(attrs or {}))
    return skills


def skill(key: str) -> Skill:
    skills = load_taxonomy()
    if key not in skills:
        raise KeyError(f"unknown skill {key!r}; add it to taxonomy.yaml")
    return skills[key]
