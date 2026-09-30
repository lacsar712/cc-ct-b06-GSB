import time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from desk.models import OffsetSubmission, ReassignLog, User


class ReassignError(Exception):
    """改派被拒（已办结 / 无落款 / 同名等），调用方转成 4xx。"""


def evaluate_verdict(offset_um: int) -> str:
    if abs(offset_um) <= settings.OFFSET_TOLERANCE_UM:
        return OffsetSubmission.Verdict.PASS
    return OffsetSubmission.Verdict.FAIL


def claim_next_pending(claimant: User) -> OffsetSubmission | None:
    """用 SKIP LOCKED 领取一条待复核单，切入“复核中”并写入认领人落款。

    认领人与名字快照在同一事务写入；领取后到办结前即为“在途”，可被改派。
    """
    with transaction.atomic():
        submission = (
            OffsetSubmission.objects.select_for_update(skip_locked=True)
            .filter(status=OffsetSubmission.Status.PENDING)
            .order_by("created_at", "id")
            .first()
        )
        if submission is None:
            return None

        now = timezone.now()
        submission.status = OffsetSubmission.Status.PROCESSING
        submission.claimant = claimant
        submission.claimant_name = claimant.display_name
        submission.claimed_at = now
        submission.save(
            update_fields=["status", "claimant", "claimant_name", "claimed_at"]
        )
    return submission


def finish_submission(submission_id: int) -> bool:
    """重新加锁办结。只在“复核中”时成功；绝不改写认领人字段。

    与改派互斥：二者都对同一行 select_for_update，先提交者定状态，
    后到者凭 status 守卫决定成败，因此不会出现办结/改派各成一半。
    """
    with transaction.atomic():
        submission = (
            OffsetSubmission.objects.select_for_update()
            .filter(pk=submission_id)
            .first()
        )
        if submission is None:
            return False
        # 已办结（与改派撞车且办结先成）则幂等返回，不重复出结论。
        if submission.status != OffsetSubmission.Status.PROCESSING:
            return False

        submission.verdict = evaluate_verdict(submission.offset_um)
        submission.status = OffsetSubmission.Status.DONE
        submission.reviewed_at = timezone.now()
        # 刻意不含 claimant / claimant_name：落款保持认领（或改派后）的名字。
        submission.save(update_fields=["verdict", "status", "reviewed_at"])
        return True


def reassign_submission(
    submission_id: int, to_claimant: User, operator: User
) -> OffsetSubmission:
    """把“复核中”的单原子改派给另一认领名，并写痕迹簿。

    已办结或无落款（非在途）一律拒绝；痕迹簿与认领人在同一事务提交，
    任一步失败整体回滚，绝不留下“只换名字没留痕”或反之的半截状态。
    """
    with transaction.atomic():
        submission = (
            OffsetSubmission.objects.select_for_update()
            .filter(pk=submission_id)
            .first()
        )
        if submission is None:
            raise ReassignError("刀补记录不存在")
        if submission.status == OffsetSubmission.Status.DONE:
            raise ReassignError("该单已办结，不允许改派")
        if submission.status != OffsetSubmission.Status.PROCESSING:
            raise ReassignError("仅复核中（在途）的单可改派")
        if not submission.claimant_id:
            raise ReassignError("该单尚无认领人，无法改派")
        if submission.claimant_id == to_claimant.id:
            raise ReassignError("新认领人与当前认领人相同，无需改派")

        old_name = submission.claimant_name
        new_name = to_claimant.display_name

        ReassignLog.objects.create(
            submission=submission,
            submission_label=str(submission),
            tool_code=submission.tool_code,
            from_claimant_name=old_name,
            to_claimant_name=new_name,
            operator_name=operator.display_name,
        )

        submission.claimant = to_claimant
        submission.claimant_name = new_name
        # claimed_at 保留首次认领时刻；这里只换落款，不重置在途起点。
        submission.save(update_fields=["claimant", "claimant_name"])
        return submission


def processing_hold_seconds() -> float:
    """在途停留时长：认领后停留若干秒再办结，供在途改派。"""
    return float(getattr(settings, "WORKER_PROCESSING_HOLD_SECONDS", 2.0))


def sleep_hold() -> None:
    hold = processing_hold_seconds()
    if hold > 0:
        time.sleep(hold)
