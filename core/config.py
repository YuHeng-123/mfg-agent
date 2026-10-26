"""Runtime settings. Everything tunable lives here so that a report can quote it."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "evals" / "reports"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass
class Settings:
    provider: str = field(default_factory=lambda: os.environ.get("PROVIDER", "stub"))
    # Evidence gate. A question must match at least this many distinct content
    # terms, and their summed IDF must clear this mass, before we agree we have
    # material to answer from. Values below were measured on the sample corpus
    # shipped in tests/ and are re-calibrated on the full eval set; whatever a
    # report uses is quoted inside that report.
    evidence_min_terms: int = field(default_factory=lambda: int(_env_float("EVIDENCE_MIN_TERMS", 3)))
    evidence_min_mass: float = field(default_factory=lambda: _env_float("EVIDENCE_MIN_MASS", 2.5))
    evidence_min_hits: int = 2
    max_steps: int = 6
    tool_timeout_s: float = 3.0
    top_k: int = 5
    model_name: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", "deepseek-chat"))
    base_url: str = field(default_factory=lambda: os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"))
    api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))
    # The sensor series is a replay. "Now" is pinned so that answers are
    # reproducible and so the demo question lands inside the planted anomaly
    # instead of wherever the CSV happens to end.
    demo_now: str = field(default_factory=lambda: os.environ.get("DEMO_NOW", "2026-10-24 12:40"))
    # Simulated per-tool latency used only to make the parallel-vs-serial
    # argument measurable in a demo. Zero by default; README states it is fake.
    tool_latency_ms: int = field(default_factory=lambda: int(_env_float("TOOL_LATENCY_MS", 0)))

    @property
    def real_provider_ready(self) -> bool:
        return bool(self.api_key)


settings = Settings()
