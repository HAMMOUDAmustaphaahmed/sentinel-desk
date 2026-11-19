"""Settings, read once from the environment. Every threshold the pipeline uses lives here."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    database_url: str = _env("DATABASE_URL", f"sqlite:///{ROOT / 'sentineldesk.sqlite3'}")
    model_path: Path = Path(_env("TRIAGE_MODEL", str(ROOT / "models" / "triage.joblib")))
    data_dir: Path = Path(_env("DATA_DIR", str(ROOT / "data")))
    runbook_dir: Path = ROOT / "runbooks"
    faq_dir: Path = ROOT / "faq"

    # Demo bank the platform watches and can act on.
    bank_url: str = _env("BANK_URL", "http://127.0.0.1:8100")

    # Language model behind the agents. Leave LLM_MODEL empty to run without one:
    # replies then come from the knowledge base and actions from the runbooks.
    #   LLM_PROVIDER=openai     any OpenAI-compatible endpoint (set LLM_BASE_URL)
    #   LLM_PROVIDER=anthropic  the Claude API
    llm_provider: str = _env("LLM_PROVIDER", "openai").lower()
    llm_base_url: str = _env("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_model: str = _env("LLM_MODEL")
    llm_api_key: str = _env("LLM_API_KEY")
    agent_max_steps: int = 8  # tool-calling rounds an agent may take on one case

    cors_origins: str = _env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")

    # --- Triage
    # Below this classifier confidence a ticket is never handled automatically.
    min_confidence: float = 0.35

    # --- Log detection (per service)
    spike_window_s: int = 120  # the "now" window
    baseline_window_s: int = 1800  # what "normal" is measured over, just before the window
    spike_min_events: int = 5  # fewer than this is never an incident
    spike_ratio: float = 3.0  # window rate must be this many times the baseline rate
    new_error_min_events: int = 3  # a never-seen error type needs this many occurrences
    quiet_resolve_s: int = 300  # no new exception for this long resolves the incident

    # --- Ticket/incident correlation
    link_before_s: int = 600  # customers may complain slightly before detection fires
    link_after_s: int = 1800  # and keep complaining for a while after the last exception
    cluster_window_s: int = 900  # tickets-only detection looks this far back
    cluster_min_customers: int = 4  # distinct customers reporting the same feature failing

    # --- Knowledge base
    # Below this match score the knowledge base has no answer and the ticket goes to a person.
    # Deliberately strict: a weak match makes a confident-looking wrong draft.
    min_retrieval_score: float = 0.2


settings = Settings()
