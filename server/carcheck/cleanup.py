"""Retention: delete videos and photos after RETENTION_DAYS. The marks table and hashes stay.
Cron daily:  30 3 * * * cd /opt/carcheck/app && python3 -m carcheck.cleanup"""
import shutil
import time

from . import db
from .config import RETENTION_DAYS


def main():
    limit = time.time() - RETENTION_DAYS * 86400
    with db.connect() as con:
        old = [dict(r) for r in con.execute(
            "SELECT id, dir FROM checks WHERE created < ? AND status IN ('reported','done','error')",
            (limit,))]
    for c in old:
        shutil.rmtree(c["dir"], ignore_errors=True)
        db.update_check(c["id"], status="purged")
    print(f"purged {len(old)} check(s)")
    from . import bookdocs
    print(f"purged documents of {len(bookdocs.purge_expired())} booking(s)")


if __name__ == "__main__":
    main()
