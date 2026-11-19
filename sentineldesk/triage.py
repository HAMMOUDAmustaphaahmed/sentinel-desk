"""Triage: which of the 77 banking intents is this ticket about, and how sure are we.

A linear model over word and character n-grams. It trains in seconds on a laptop, its
confidence is a real probability, and it costs nothing per ticket: no model API is called
to route a ticket, only to investigate the ones that need it.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from .intents import feature_of, is_problem


@dataclass(frozen=True)
class Triage:
    intent: str
    confidence: float
    feature: str
    is_problem: bool


def load_csv(path: Path) -> tuple[list[str], list[str]]:
    """Banking77 files have two columns: text, category."""
    texts, labels = [], []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            texts.append(row["text"])
            labels.append(row["category"])
    return texts, labels


def build_pipeline() -> Pipeline:
    features = FeatureUnion([
        ("words", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)),
        # Character n-grams absorb typos and inflections ("top-up", "topup", "topped").
        ("chars", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True)),
    ])
    return Pipeline([("features", features), ("clf", LogisticRegression(C=20.0, max_iter=2000))])


class TriageModel:
    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline

    @classmethod
    def train(cls, texts: list[str], labels: list[str]) -> "TriageModel":
        pipeline = build_pipeline()
        pipeline.fit(texts, labels)
        return cls(pipeline)

    @classmethod
    def load(cls, path: Path) -> "TriageModel":
        return cls(joblib.load(path))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.pipeline, path)

    def classify_many(self, texts: list[str]) -> list[Triage]:
        out = []
        for row in self.pipeline.predict_proba(texts):
            best = int(row.argmax())
            intent = str(self.pipeline.classes_[best])
            out.append(Triage(intent, float(row[best]), feature_of(intent), is_problem(intent)))
        return out

    def classify(self, text: str) -> Triage:
        return self.classify_many([text])[0]
