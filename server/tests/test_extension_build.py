"""DOM-only extension boundary, independently checked from extraction fixtures."""

import json
from pathlib import Path


def test_default_extension_is_dom_only():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "extension/manifest.json").read_text())
    assert manifest["minimum_chrome_version"] == "110"
    assert "debugger" not in manifest["permissions"]
    assert "debugger" not in manifest.get("optional_permissions", [])
    reader = (root / "extension/extraction/readers.js").read_text()
    assert "chrome.debugger" not in reader
    assert "AxPageReader" not in reader
    assert not (root / "devtools/build_extension.py").exists()
    for filename in ("popup.html", "workspace.html"):
        ui = (root / "extension" / filename).read_text()
        assert 'id="query"' in ui
        assert 'type="checkbox"' not in ui
        assert "ax-option" not in ui
