"""Project transport envelopes into content without relaxing content validation."""

import copy
from typing import Any


class CaptureSnapshotProjector:
    transport_fields = frozenset({"reading", "capture_generation"})

    def project(self, value: dict[str, Any]) -> dict[str, Any]:
        # Keep unknown fields: the typed content contract must still reject them.
        return {k: copy.deepcopy(v) for k, v in value.items() if k not in self.transport_fields}
