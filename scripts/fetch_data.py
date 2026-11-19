"""Download the Banking77 dataset (PolyAI, CC BY 4.0) into data/.

    python -m scripts.fetch_data

13,083 real customer-service queries labelled with 77 banking intents.
Casanueva et al., "Efficient Intent Detection with Dual Sentence Encoders", 2020.
"""
from __future__ import annotations

import urllib.request

from sentineldesk.config import settings

BASE = "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data"


def main() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    for name in ("train.csv", "test.csv"):
        target = settings.data_dir / name
        if target.exists():
            print(f"{name}: already there")
            continue
        urllib.request.urlretrieve(f"{BASE}/{name}", target)
        print(f"{name}: {target.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
