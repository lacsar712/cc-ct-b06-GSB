from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        MACHINIST = "machinist", "操作员"
        AUDITOR = "auditor", "复核员"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MACHINIST,
    )

    @property
    def can_write(self) -> bool:
        return self.role == self.Role.MACHINIST

    @property
    def display_name(self) -> str:
        """落款展示名：有全名用全名，否则用户名。认领/改派/落款三处同源取此值。"""
        return self.get_full_name() or self.username


class OffsetSubmission(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待复核"
        PROCESSING = "processing", "复核中"
        DONE = "done", "已完成"

    class Verdict(models.TextChoices):
        PASS = "合格", "合格"
        FAIL = "超差", "超差"

    tool_code = models.CharField(max_length=32, db_index=True)
    offset_um = models.IntegerField()
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    verdict = models.CharField(
        max_length=8,
        choices=Verdict.choices,
        blank=True,
        default="",
    )
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submissions",
    )

    # 认领人（落款）。worker 进程切入“复核中”时写入，办结后原样保留；
    # 在途改派只更新这一处，落款专页 / 详情 / 列表三处均读这同一列。
    claimant = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="claimed_submissions",
    )
    # 认领人名字快照，与 claimant 同事务写入/改派，作为落款展示的唯一来源；
    # 即便账号被删（claimant 置空），已落款的名字仍在。
    claimant_name = models.CharField(max_length=150, blank=True, default="", db_index=True)
    claimed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.tool_code} {self.offset_um}µm"


class ReassignLog(models.Model):
    """在途改派痕迹簿：只增不改，改派成功才落账，与改派同事务提交。"""

    submission = models.ForeignKey(
        OffsetSubmission,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reassign_logs",
    )
    # 快照字段：即便关联单被删，痕迹簿仍可独立查读。
    submission_label = models.CharField(max_length=64, default="")
    tool_code = models.CharField(max_length=32, db_index=True)
    from_claimant_name = models.CharField(max_length=150, blank=True, default="")
    to_claimant_name = models.CharField(max_length=150)
    operator_name = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.tool_code}: {self.from_claimant_name or '—'} → {self.to_claimant_name}"
