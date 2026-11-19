"""Train the triage classifier on the Banking77 training split.

    python -m scripts.train
"""
from __future__ import annotations

import time

from sentineldesk.config import settings
from sentineldesk.triage import TriageModel, load_csv


def main() -> None:
    path = settings.data_dir / "train.csv"
    if not path.exists():
        raise SystemExit("data/train.csv is missing. Run: python -m scripts.fetch_data")
    texts, labels = load_csv(path)
    start = time.perf_counter()
    model = TriageModel.train(texts, labels)
    model.save(settings.model_path)
    print(f"Trained on {len(texts)} tickets, {len(set(labels))} intents, "
          f"in {time.perf_counter() - start:.1f} s -> {settings.model_path}")


if __name__ == "__main__":
    main()
