"""Knowledge base: runbooks for engineers and FAQ answers for customers, as Markdown files.

Search is lexical (TF-IDF). With a few dozen short documents that is enough, it is
deterministic, and an agent that wants a second angle can simply search again.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel


@dataclass(frozen=True)
class Document:
    id: str
    kind: str  # "runbook" | "faq"
    title: str
    body: str
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def service(self) -> str:
        return self.meta.get("service", "")


def parse_document(path: Path, kind: str) -> Document:
    """A file is `key: value` lines between two `---` lines, then the Markdown body."""
    text = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        _, header, body = text.split("---", 2)
        for line in header.strip().splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return Document(id=path.stem, kind=kind, title=meta.get("title", path.stem), body=body.strip(), meta=meta)


class KnowledgeBase:
    def __init__(self, documents: list[Document]):
        self.documents = documents
        self._by_id = {d.id: d for d in documents}
        self._vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
        corpus = [f"{d.title}. {d.meta.get('keywords', '')}. {d.body}" for d in documents]
        self._matrix = self._vectorizer.fit_transform(corpus) if documents else None

    @classmethod
    def from_dirs(cls, runbook_dir: Path, faq_dir: Path) -> "KnowledgeBase":
        documents = [parse_document(p, "runbook") for p in sorted(runbook_dir.glob("*.md"))]
        documents += [parse_document(p, "faq") for p in sorted(faq_dir.glob("*.md"))]
        return cls(documents)

    def get(self, doc_id: str) -> Optional[Document]:
        return self._by_id.get(doc_id)

    def search(self, query: str, kind: Optional[str] = None, service: Optional[str] = None,
               k: int = 3) -> list[tuple[Document, float]]:
        if self._matrix is None or not query.strip():
            return []
        scores = linear_kernel(self._vectorizer.transform([query]), self._matrix)[0]
        ranked = sorted(zip(self.documents, scores), key=lambda pair: pair[1], reverse=True)
        hits = [
            (doc, float(score)) for doc, score in ranked
            if score > 0 and (kind is None or doc.kind == kind) and (service is None or doc.service == service)
        ]
        return hits[:k]

    def runbook_for(self, service: str, source: str) -> Optional[Document]:
        """The runbook written for this service and this kind of incident, if there is one."""
        candidates = [d for d in self.documents if d.kind == "runbook" and d.service == service]
        for doc in candidates:
            if doc.meta.get("trigger", "logs") == source:
                return doc
        return candidates[0] if candidates else None
