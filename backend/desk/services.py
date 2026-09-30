"""落款与在途改派的事务边界。

三处同源：认领写入、专页落款、改派后落款全部读写
``OffsetSubmission.claimant`` 这一列，再无第二处存放落款名。

并发安全：办结（finalize）与改派（reassign）都在 ``select_for_update``
行锁内先复核状态再落库。两者撞车时先拿到锁者提交结果：
- 办结先成 → 状态已是 done，改派在锁内复核到 done，整体回滚，不换人、不留痕；
- 改派先成 → claimant 已换，随后办结沿用新认领人落款，不会回写旧名。
"""

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from desk.models import Claimant, OffsetSubmission, ReassignmentLog


class ReassignmentError(Exception):
    """改派被拒（非在途 / 目标认领人无效 / 同名）。"""


def evaluate_verdict(offset_um: int) -> str:
    if abs(offset_um) <= settings.OFFSET_TOLERANCE_UM:
        return OffsetSubmission.Verdict.PASS
    return OffsetSubmission.Verdict.FAIL


def claim_pending(claimant: Claimant):
    """在一个事务内锁住一条待复核单，写入认领人并切入“复核中”。

    行锁用 skip_locked，多个认领进程互不抢同一行。返回被认领的记录，
    没有待复核单时返回 None。
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
        submission.claimed_at = now
        submission.save(update_fields=["status", "claimant", "claimed_at"])
    return submission


def finalize_submission(submission: OffsetSubmission) -> bool:
    """对一条在途单办结并落款。

    行锁内复核状态仍为 processing 才办结；认领人（可能已被改派更换）
    原样保留为落款。返回是否实际办结（已办结/已不存在返回 False）。
    """
    with transaction.atomic():
        locked = (
            OffsetSubmission.objects.select_for_update()
            .filter(pk=submission.pk, status=OffsetSubmission.Status.PROCESSING)
            .first()
        )
        if locked is None:
            return False
        locked.verdict = evaluate_verdict(locked.offset_um)
        locked.status = OffsetSubmission.Status.DONE
        locked.reviewed_at = timezone.now()
        # 不动 claimant：谁是当前认领人，办结落款就是谁（含改派后的新人）。
        locked.save(update_fields=["verdict", "status", "reviewed_at"])
        submission.verdict = locked.verdict
        submission.status = locked.status
        submission.reviewed_at = locked.reviewed_at
    return True


def reassign_submission(
    *,
    submission_id: int,
    to_claimant_id: int,
    operator_name: str,
    note: str = "",
) -> ReassignmentLog:
    """把一条“复核中、未结清”的单改派给另一认领名，并写痕迹簿。

    全部在同一事务、同一行锁内完成：状态校验、换落款、写痕迹要么一起
    成功，要么一起回滚。已办结（done）拒绝改派。
    """
    note = (note or "").strip()
    with transaction.atomic():
        submission = (
            OffsetSubmission.objects.select_for_update()
            .filter(pk=submission_id)
            .select_related("claimant")
            .first()
        )
        if submission is None:
            raise ReassignmentError("刀补记录不存在")

        # 锁内复核：已办结的不许改派（办结先成的撞车也在此被挡下）。
        if submission.status != OffsetSubmission.Status.PROCESSING:
            if submission.status == OffsetSubmission.Status.DONE:
                raise ReassignmentError("该单已办结，不得改派")
            raise ReassignmentError("该单尚未进入复核中，暂不能改派")

        try:
            target = Claimant.objects.get(pk=to_claimant_id, active=True)
        except Claimant.DoesNotExist:
            raise ReassignmentError("目标认领名不存在或已停用")

        current = submission.claimant
        if current is not None and current.pk == target.pk:
            raise ReassignmentError("目标认领名与当前认领人相同，无需改派")

        from_name = current.name if current else ""
        log = ReassignmentLog.objects.create(
            submission=submission,
            tool_code=submission.tool_code,
            from_claimant=current,
            to_claimant=target,
            from_name=from_name,
            to_name=target.name,
            operator_name=operator_name,
            note=note[:255],
        )
        # 唯一落款列换人；专页此后读到的就是新名，三处依旧同源。
        submission.claimant = target
        submission.save(update_fields=["claimant"])
    return log
