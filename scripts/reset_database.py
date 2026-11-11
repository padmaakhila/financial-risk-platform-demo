"""Safely reset the DEVELOPMENT database.
  python -m scripts.reset_database --yes            # wipe, recreate schema, reseed
  python -m scripts.reset_database --yes --no-seed  # wipe, recreate schema only
SQLite files are backed up to data/backups/ first. Refuses to run in production
or against a non-SQLite database unless --allow-non-sqlite is given.
"""
import argparse
import shutil
from datetime import datetime
from pathlib import Path

from backend.core.config import BASE_DIR, get_settings
from backend.database.session import get_engine, reset_engine


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="confirm that you want to erase data")
    ap.add_argument("--no-seed", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--allow-non-sqlite", action="store_true")
    a = ap.parse_args()
    s = get_settings()
    if s.is_production:
        raise SystemExit("Refusing to reset when APP_ENV=production.")
    if not a.yes:
        raise SystemExit("Add --yes to confirm. This erases the development database.")
    engine = get_engine()
    if engine.url.get_backend_name() == "sqlite":
        db_path = Path(engine.url.database or "")
        reset_engine()
        if db_path.exists():
            backups = BASE_DIR / "data" / "backups"
            backups.mkdir(parents=True, exist_ok=True)
            dest = backups / f"{db_path.stem}_{datetime.now():%Y%m%d_%H%M%S}.db"
            shutil.copy2(db_path, dest)
            print("Backup saved:", dest)
        for suffix in ("", "-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
    elif a.allow_non_sqlite:
        from backend.models import Base
        Base.metadata.drop_all(engine)
        reset_engine()
    else:
        raise SystemExit("Non-SQLite database: pass --allow-non-sqlite to drop all tables.")
    from scripts.init_db import init_db
    init_db()
    if not a.no_seed:
        from backend.database.session import session_scope
        from scripts.generate_data import build_dataset
        from scripts.seed_database import seed
        with session_scope() as sess:
            seed(sess, build_dataset(a.seed))
    print("Reset complete.")


if __name__ == "__main__":
    main()
