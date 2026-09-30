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


class Claimant(models.Model):
    """认领名（专台）：复核进程以哪个台座的名义认领与落款。"""

    name = models.CharField(max_length=64, unique=True)
    code = models.CharField(max_length=32, unique=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code", "id"]

    def __str__(self) -> str:
        return self.name


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
    # 认领人落款的唯一数据源：进程切入“复核中”时写入，改派只改这一列，
    # 办结后原样保留。专页落款、认领写入、改派后落款三处同源于此。
    claimant = models.ForeignKey(
        Claimant,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="claims",
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.tool_code} {self.offset_um}µm"


class ReassignmentLog(models.Model):
    """在途改派痕迹簿：谁把哪条在途单从哪个认领名改给了哪个认领名。

    名称字段在写入时做字符串快照，即使日后认领人变动，痕迹也不丢名。
    """

    submission = models.ForeignKey(
        OffsetSubmission,
        on_delete=models.CASCADE,
        related_name="reassignments",
    )
    tool_code = models.CharField(max_length=32, db_index=True)
    from_claimant = models.ForeignKey(
        Claimant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reassignments_out",
    )
    to_claimant = models.ForeignKey(
        Claimant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reassignments_in",
    )
    from_name = models.CharField(max_length=64)
    to_name = models.CharField(max_length=64)
    operator_name = models.CharField(max_length=150)
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.tool_code}: {self.from_name} → {self.to_name}"
