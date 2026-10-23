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


@pytest.fixture
def db_url(tmp_path):
    """测试数据库地址：默认 SQLite 临时文件；设置 GLEANER_TEST_PG 时改用 PostgreSQL（每次清空重建）。

    GLEANER_TEST_PG=postgresql://user:pw@host:5432/gleaner_test pytest
    """
    import os

    pg = os.environ.get("GLEANER_TEST_PG", "")

    def make(name: str) -> str:
        if not pg:
            return f"sqlite:///{tmp_path / name}"
        import psycopg

        with psycopg.connect(pg, autocommit=True) as c:
            c.execute("DROP SCHEMA public CASCADE")
            c.execute("CREATE SCHEMA public")
        return pg

    return make
