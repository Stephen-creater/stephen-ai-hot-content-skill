"""Shared delivery history used before acquisition and again at publication."""
import json
from pathlib import Path


def delivered_candidates(topics: Path, exclude: Path | None = None) -> list[dict]:
    rows = []
    for path in sorted(topics.glob('*/run.json')):
        if exclude is not None and path.parent.resolve() == exclude.resolve():
            continue
        run = json.loads(path.read_text(encoding='utf-8'))
        if run.get('delivery_registered') is True or (
            run.get('delivery_ready') is True and run.get('manual_editorial_review') is True
        ):
            rows.extend(json.loads(path.with_name('candidates.json').read_text(encoding='utf-8')))
    return rows
