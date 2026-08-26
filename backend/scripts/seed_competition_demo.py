#!/usr/bin/env python3
"""Create or refresh the isolated offline competition demo dataset."""

import asyncio
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import async_session, engine, init_db
from app.core.config import settings
from app.services.demo_seed import seed_competition_demo


def reset_dedicated_demo_database() -> None:
    """Delete only the repository-owned disposable demo database."""
    prefix = "sqlite+aiosqlite:///"
    if not settings.database_url.startswith(prefix):
        raise RuntimeError("--reset 只支持专用 SQLite 比赛演示库")
    configured = Path(settings.database_url[len(prefix):]).expanduser()
    backend_root = Path(__file__).resolve().parents[1]
    expected = backend_root / "data" / "competition-demo.db"
    if configured.resolve(strict=False) != expected.resolve(strict=False):
        raise RuntimeError(f"拒绝重置非专用演示库: {configured}")
    targets = [configured, Path(f"{configured}-wal"), Path(f"{configured}-shm")]
    for target in targets:
        if target.is_symlink():
            raise RuntimeError(f"拒绝重置符号链接: {target}")
        if target.exists():
            if not target.is_file():
                raise RuntimeError(f"演示库目标不是普通文件: {target}")
            target.unlink()


async def main():
    await init_db()
    async with async_session() as db:
        manifest = await seed_competition_demo(db)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset", action="store_true",
        help="安全重建 backend/data/competition-demo.db，确保每次演示从同一状态开始",
    )
    args = parser.parse_args()
    if args.reset:
        reset_dedicated_demo_database()
    asyncio.run(main())
