import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# 测试替身（fake_moodle、fake_mail）位于 devtools/
sys.path.insert(0, str(ROOT / "devtools"))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_email_code_by_default(monkeypatch):
    """大多数测试不关心注册验证码；专门的测试会重新打开。"""
    monkeypatch.setenv("GLEANER_REQUIRE_EMAIL_CODE", "0")
