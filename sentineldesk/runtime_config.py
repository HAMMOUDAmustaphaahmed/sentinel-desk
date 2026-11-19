"""Settings that can be changed while the platform runs, from the configuration page.

The environment gives the starting values (see config.py). Anything saved here is stored
in the database and overrides them. One list, FIELDS, describes every editable setting:
the API validates against it and the page renders from it, so the two cannot drift apart.

The API key is write-only: it can be set or cleared, never read back.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional

from sqlalchemy import JSON, String, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .config import Settings
from .db import Base


class ConfigEntry(Base):
    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


@dataclass(frozen=True)
class Field:
    key: str
    group: str
    label: str
    help: str
    kind: str  # int | float | text | url | select | secret
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None
    unit: str = ""
    options: tuple[str, ...] = ()


GROUPS = {
    "model": ("Language model", "The model behind the two agents. Leave the model name empty to run on "
                                "rules and runbooks only."),
    "triage": ("Triage", "How sure the classifier must be before a ticket is handled without a person."),
    "detection": ("Log detection", "When a service's exceptions count as an incident."),
    "correlation": ("Ticket and incident correlation", "Which tickets are linked to an incident, and when "
                                                       "complaints alone open one."),
    "knowledge": ("Knowledge base", "When an article is a good enough match to draft a reply from."),
    "bank": ("Monitored service", "Where recovery actions are sent."),
}

FIELDS: tuple[Field, ...] = (
    Field("llm_provider", "model", "API format",
          "\"openai\" covers every OpenAI-compatible provider. \"anthropic\" is the Claude API.",
          "select", options=("openai", "anthropic")),
    Field("llm_base_url", "model", "Base URL",
          "The provider's endpoint. Not used with the Claude API.", "url"),
    Field("llm_model", "model", "Model name",
          "As the provider names it. It must support tool calling. Empty turns the agents off.", "text"),
    Field("llm_api_key", "model", "API key",
          "Stored in this server's database and never sent back to the browser.", "secret"),
    Field("agent_max_steps", "model", "Steps per case",
          "Tool-calling rounds an agent may take before the case goes to a person.", "int", 1, 20, 1),

    Field("min_confidence", "triage", "Minimum confidence",
          "Below this, a ticket is never linked or answered automatically.", "float", 0.05, 0.95, 0.05),

    Field("spike_window_s", "detection", "Detection window",
          "How far back \"right now\" looks.", "int", 30, 900, 10, "s"),
    Field("baseline_window_s", "detection", "Baseline window",
          "The period just before the window that defines what is normal for the service.",
          "int", 300, 7200, 60, "s"),
    Field("spike_min_events", "detection", "Minimum exceptions",
          "Fewer exceptions than this in the window is never an incident.", "int", 2, 100, 1),
    Field("spike_ratio", "detection", "Spike ratio",
          "The window's rate must be this many times the baseline rate.", "float", 1.5, 20, 0.5, "×"),
    Field("new_error_min_events", "detection", "New error type",
          "Occurrences of a never-seen error needed to open an incident.", "int", 1, 50, 1),
    Field("quiet_resolve_s", "detection", "Quiet period",
          "With no new exception for this long, the incident is resolved.", "int", 60, 3600, 30, "s"),

    Field("link_before_s", "correlation", "Link tickets sent before",
          "Customers often complain before detection fires. Tickets this early are still linked.",
          "int", 0, 3600, 60, "s"),
    Field("link_after_s", "correlation", "Link tickets sent after",
          "How long after the last exception a complaint still belongs to the incident.",
          "int", 60, 14400, 60, "s"),
    Field("cluster_window_s", "correlation", "Complaint window",
          "Complaints this recent count towards opening an incident from tickets alone.",
          "int", 120, 7200, 60, "s"),
    Field("cluster_min_customers", "correlation", "Customers needed",
          "Distinct customers reporting the same feature failing, with nothing in the logs.",
          "int", 2, 50, 1),

    Field("min_retrieval_score", "knowledge", "Minimum match",
          "Below this score, no reply is drafted and the ticket goes to a person.",
          "float", 0.05, 0.9, 0.05),

    Field("bank_url", "bank", "Service URL",
          "The demo bank's address. Approved actions are posted to it.", "url"),
)

_BY_KEY = {f.key: f for f in FIELDS}


class ConfigError(ValueError):
    """A submitted value is not acceptable. Carries the field it concerns."""

    def __init__(self, key: str, message: str):
        super().__init__(message)
        self.key = key


def validate(key: str, value: Any) -> Any:
    """Check one submitted value against its field. Returns the value to store."""
    field = _BY_KEY.get(key)
    if field is None:
        raise ConfigError(key, "This setting does not exist.")

    if field.kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(key, "Enter a number.")
        if field.kind == "int":
            if float(value) != int(value):
                raise ConfigError(key, "Enter a whole number.")
            value = int(value)
        else:
            value = float(value)
        if not field.minimum <= value <= field.maximum:
            raise ConfigError(key, f"Must be between {field.minimum:g} and {field.maximum:g}.")
        return value

    if not isinstance(value, str):
        raise ConfigError(key, "Enter text.")
    value = value.strip()
    if len(value) > 400:
        raise ConfigError(key, "Too long (400 characters at most).")
    if field.kind == "select" and value not in field.options:
        raise ConfigError(key, f"Choose one of: {', '.join(field.options)}.")
    if field.kind == "url" and not value.startswith(("http://", "https://")):
        raise ConfigError(key, "Must start with http:// or https://.")
    return value


def load_overrides(session: Session) -> dict[str, Any]:
    stored = {entry.key: entry.value for entry in session.scalars(select(ConfigEntry))}
    return {key: value for key, value in stored.items() if key in _BY_KEY}  # ignore settings since removed


def save_overrides(session: Session, changes: dict[str, Any]) -> None:
    """Validate everything first, then store. One bad value saves nothing."""
    cleaned = {key: validate(key, value) for key, value in changes.items()}
    for key, value in cleaned.items():
        session.merge(ConfigEntry(key=key, value=value))


def clear_overrides(session: Session) -> None:
    session.execute(delete(ConfigEntry))


def effective(base: Settings, overrides: dict[str, Any]) -> Settings:
    return replace(base, **overrides)


def describe(base: Settings, current: Settings, overrides: dict[str, Any]) -> dict[str, Any]:
    """Everything the configuration page needs. The API key itself is never included."""
    fields = []
    for f in FIELDS:
        entry: dict[str, Any] = {
            "key": f.key, "group": f.group, "label": f.label, "help": f.help, "kind": f.kind,
            "min": f.minimum, "max": f.maximum, "step": f.step, "unit": f.unit,
            "options": list(f.options), "changed": f.key in overrides,
        }
        if f.kind == "secret":
            entry["is_set"] = bool(getattr(current, f.key))
        else:
            entry["value"] = getattr(current, f.key)
            entry["default"] = getattr(base, f.key)
        fields.append(entry)
    return {
        "groups": [{"key": key, "title": title, "description": description}
                   for key, (title, description) in GROUPS.items()],
        "fields": fields,
        "presets": PRESETS,
    }


# Shortcuts for the model section. Picking one fills the format and the base URL.
PRESETS = [
    {"name": "OpenAI", "llm_provider": "openai", "llm_base_url": "https://api.openai.com/v1"},
    {"name": "Groq", "llm_provider": "openai", "llm_base_url": "https://api.groq.com/openai/v1"},
    {"name": "Mistral", "llm_provider": "openai", "llm_base_url": "https://api.mistral.ai/v1"},
    {"name": "Gemini", "llm_provider": "openai",
     "llm_base_url": "https://generativelanguage.googleapis.com/v1beta/openai"},
    {"name": "OpenRouter", "llm_provider": "openai", "llm_base_url": "https://openrouter.ai/api/v1"},
    {"name": "DeepSeek", "llm_provider": "openai", "llm_base_url": "https://api.deepseek.com/v1"},
    {"name": "Claude", "llm_provider": "anthropic", "llm_base_url": "https://api.anthropic.com"},
    {"name": "Local server", "llm_provider": "openai", "llm_base_url": "http://localhost:11434/v1"},
]
