"""Background worker: 以固定认领名署名认领待复核单，停留一个在途窗口后办结。

- 认领带 ``skip_locked`` 行锁，切入“复核中”时写入 claimant（落款同源列）。
- 切入后停留 ``PROCESSING_HOLD_SECONDS`` 秒再办结，这段“在途”时间里
  专台能看到认领人、操作员可以改派。
- 办结走 services.finalize_submission，在锁内复核状态：若期间已被改派，
  沿用新认领人落款；撞车时由数据库行锁决定先后，不产生半截换人。
"""

import os
import sys
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import django


def setup_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def resolve_claimant():
    from desk.models import Claimant

    name = os.environ.get("CLAIMANT_NAME", "甲台复核员")
    code = os.environ.get("CLAIMANT_CODE", name)
    # 等迁移把表建好后再取认领人，避免与 backend 启动赛跑。
    for attempt in range(60):
        try:
            claimant, _ = Claimant.objects.get_or_create(
                code=code,
                defaults={"name": name, "active": True},
            )
            return claimant
        except Exception as exc:  # 表尚未就绪等瞬时错误
            print(f"waiting for claimant table ({attempt}): {exc}", flush=True)
            time.sleep(1)
    raise RuntimeError("认领人表长时间不可用，worker 启动失败")


def claim_one_pending(claimant):
    from desk.services import claim_pending

    return claim_pending(claimant)


def finalize_after_hold(submission, hold_seconds: float) -> None:
    from django.db import connection

    from desk.services import finalize_submission

    try:
        if hold_seconds > 0:
            time.sleep(hold_seconds)
        ok = finalize_submission(submission)
        if ok:
            print(
                f"finalized {submission.tool_code}#{submission.id}",
                flush=True,
            )
    finally:
        # 线程持有独立的数据库连接，办结后主动关闭，避免连接泄漏。
        connection.close()


def run_loop(poll_seconds: float = 0.5) -> None:
    setup_django()
    hold_seconds = float(os.environ.get("PROCESSING_HOLD_SECONDS", "8"))
    max_in_flight = int(os.environ.get("MAX_IN_FLIGHT", "8"))
    claimant = resolve_claimant()
    print(
        f"cnc-offset worker started claimant={claimant.name} hold={hold_seconds}s",
        flush=True,
    )

    in_flight: list[threading.Thread] = []

    def reap(joined: threading.Thread | None = None) -> None:
        if joined is not None:
            joined.join()
        gone = [t for t in in_flight if not t.is_alive()]
        for t in gone:
            in_flight.remove(t)

    while True:
        # 控制在途上限：满了就等最早的一条办结，给专台留出改派窗口。
        if len(in_flight) >= max_in_flight:
            in_flight[0].join()
            reap()

        submission = claim_one_pending(claimant)
        if submission is None:
            reap()
            time.sleep(poll_seconds)
            continue

        print(
            f"claimed {submission.tool_code}#{submission.id} by {claimant.name}",
            flush=True,
        )
        thread = threading.Thread(
            target=finalize_after_hold,
            args=(submission, hold_seconds),
            daemon=True,
        )
        in_flight.append(thread)
        thread.start()
        reap()


if __name__ == "__main__":
    setup_django()
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        # 脚本/测试用：认领一条并立即办结（不等待在途窗口）。
        claimant = resolve_claimant()
        row = claim_one_pending(claimant)
        if row is not None:
            from desk.services import finalize_submission

            finalize_submission(row)
    else:
        run_loop()
