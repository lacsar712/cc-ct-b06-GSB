from django.core.management.base import BaseCommand
from django.utils import timezone

from desk.auth_utils import hash_password
from desk.models import OffsetSubmission, User


class Command(BaseCommand):
    help = "创建默认账号与种子刀补记录"

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
        # 认领进程身份（落款名）。worker 启动也会按 WORKER_NAME 自动建同名账号；
        # 这里预置两个，便于在途改派演示与按人筛选。
        for worker_name in ("worker-01", "worker-02"):
            User.objects.update_or_create(
                username=worker_name,
                defaults={
                    "role": User.Role.MACHINIST,
                    "is_active": True,
                },
            )

        now = timezone.now()
        seeds = [
            ("T01", 5, OffsetSubmission.Verdict.PASS),
            ("T09", 20, OffsetSubmission.Verdict.FAIL),
        ]
        for tool_code, offset_um, verdict in seeds:
            # 已办结单也带落款：认领进程写入的名字办结后原样保留。
            OffsetSubmission.objects.update_or_create(
                tool_code=tool_code,
                offset_um=offset_um,
                defaults={
                    "status": OffsetSubmission.Status.DONE,
                    "verdict": verdict,
                    "submitted_by": machinist,
                    "claimant": machinist,
                    "claimant_name": machinist.display_name,
                    "claimed_at": now,
                    "reviewed_at": now,
                },
            )

        self.stdout.write(self.style.SUCCESS("seed_offset_desk 完成"))
