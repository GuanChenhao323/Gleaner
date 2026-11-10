"""Deterministic comparison of selected content, without business extraction."""

import hashlib
import json

from gleaner.monitoring.models import TargetObservation


def content_digest(entry: TargetObservation) -> str:
    data = json.dumps(
        [entry.title, entry.text, entry.metadata], ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(data.encode()).hexdigest()
