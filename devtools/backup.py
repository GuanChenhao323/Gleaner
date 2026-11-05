"""本地开发环境（SQLite）的数据库备份与恢复。

    python devtools/backup.py                      # 备份 data/dev.db 到 data/backups/dev-时间.db
    python devtools/backup.py --restore data/backups/dev-20261105-120000.db   # 恢复（先停掉 dev_all）

使用 SQLite 在线备份接口（``Connection.backup``），服务运行中也能得到一致的快照。
docker compose 部署（PostgreSQL）由 ``backup`` 服务每天自动备份，见 README“备份与恢复”。
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def backup(db: Path, out_dir: Path, keep: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{db.stem}-{time.strftime('%Y%m%d-%H%M%S')}.db"
    src = sqlite3.connect(db)
    try:
        target = sqlite3.connect(dst)
        try:
            src.backup(target)
        finally:
            target.close()
    finally:
        src.close()
    old = sorted(out_dir.glob(f"{db.stem}-*.db"))[:-keep]
    for p in old:
        p.unlink()
    return dst


def restore(snapshot: Path, db: Path) -> None:
    for suffix in ("-wal", "-shm"):  # WAL 模式的附属文件必须一起清掉，否则会把旧日志重放回去
        Path(str(db) + suffix).unlink(missing_ok=True)
    shutil.copyfile(snapshot, db)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "dev.db")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "backups")
    ap.add_argument("--keep", type=int, default=14, help="保留最近几份")
    ap.add_argument("--restore", type=Path, help="用这份备份覆盖 --db（先停掉服务）")
    a = ap.parse_args()
    if a.restore:
        restore(a.restore, a.db)
        print(f"restored {a.db} from {a.restore}")
    else:
        print(f"backup written: {backup(a.db, a.out, a.keep)}")


if __name__ == "__main__":
    main()
