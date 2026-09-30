"""Background worker: claim pending rows with SKIP LOCKED, sign claimant, hold
while the row is 在途（复核中，可改派）, then apply verdict under a row lock."""

import os
import sys
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
    """本进程的认领人身份（落款名）。由 WORKER_NAME 指定，默认 worker-01。

    多个 worker 进程取不同 WORKER_NAME 即可各自落款；在途时操作员可把单
    改派给另一个认领名。
    """
    from desk.models import User

    name = os.environ.get("WORKER_NAME", "worker-01").strip() or "worker-01"
    user, _ = User.objects.get_or_create(
        username=name,
        defaults={
            "role": User.Role.MACHINIST,
            "is_active": True,
        },
    )
    if not user.is_active:
        user.is_active = True
        user.save(update_fields=["is_active"])
    return user


def claim_and_finish_one() -> bool:
    from desk.services import claim_next_pending, finish_submission, sleep_hold

    claimant = resolve_claimant()
    submission = claim_next_pending(claimant)
    if submission is None:
        return False

    # 认领后停留：此刻单子处于“复核中”，操作员可在落款台在途改派。
    sleep_hold()

    # 重新加锁办结；若期间被改派，落款已是新人名，办结原样保留。
    finish_submission(submission.id)
    return True


def run_loop(poll_seconds: float = 0.5) -> None:
    setup_django()
    worker_name = os.environ.get("WORKER_NAME", "worker-01").strip() or "worker-01"
    hold = os.environ.get("WORKER_PROCESSING_HOLD_SECONDS", "2")
    print(
        f"cnc-offset worker started as {worker_name!r} (hold={hold}s)",
        flush=True,
    )
    while True:
        try:
            claimed = claim_and_finish_one()
        except Exception as exc:  # 单条失败不拖垮循环
            print(f"worker iteration error: {exc!r}", flush=True)
            claimed = False
        if not claimed:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    setup_django()
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        claim_and_finish_one()
    else:
        run_loop()
