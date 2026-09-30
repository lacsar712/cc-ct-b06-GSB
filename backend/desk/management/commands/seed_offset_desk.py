from django.core.management.base import BaseCommand
from django.utils import timezone

from desk.auth_utils import hash_password
from desk.models import Claimant, OffsetSubmission, User


class Command(BaseCommand):
    help = "创建默认账号、认领名（专台）与种子刀补记录"

    def handle(self, *args, **options):
        machinist, _ = User.objects.update_or_create(
            username="machinist",
            defaults={
                "role": User.Role.MACHINIST,
                "password": hash_password("machine123456"),
                "is_active": True,
            },
        )
        User.objects.update_or_create(
            username="auditor",
            defaults={
                "role": User.Role.AUDITOR,
                "password": hash_password("audit123456"),
                "is_active": True,
            },
        )

        # 三个可落款/可改派的认领名（专台）。
        claimants = {}
        for code, name in [
            ("A", "甲台复核员"),
            ("B", "乙台复核员"),
            ("C", "丙台复核员"),
        ]:
            claimants[code], _ = Claimant.objects.update_or_create(
                code=code,
                defaults={"name": name, "active": True},
            )

        now = timezone.now()
        seeds = [
            ("T01", 5, OffsetSubmission.Verdict.PASS),
            ("T09", 20, OffsetSubmission.Verdict.FAIL),
        ]
        for tool_code, offset_um, verdict in seeds:
            OffsetSubmission.objects.update_or_create(
                tool_code=tool_code,
                offset_um=offset_um,
                defaults={
                    "status": OffsetSubmission.Status.DONE,
                    "verdict": verdict,
                    "submitted_by": machinist,
                    # 已办结记录保留认领人落款（甲台）。
                    "claimant": claimants["A"],
                    "claimed_at": now,
                    "reviewed_at": now,
                },
            )

        self.stdout.write(self.style.SUCCESS("seed_offset_desk 完成"))
