from datetime import datetime
from typing import Optional

from django.db.models import Q
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import NinjaAPI, Query, Schema
from ninja.errors import HttpError

from desk.auth_utils import bearer_auth, create_access_token, verify_password
from desk.models import OffsetSubmission, ReassignLog, User
from desk.services import ReassignError, reassign_submission

api = NinjaAPI(title="数控刀补复核台", version="1.0")


class HealthOut(Schema):
    status: str


class LoginIn(Schema):
    username: str
    password: str


class LoginOut(Schema):
    token: str
    username: str
    role: str
    can_write: bool


class SubmissionIn(Schema):
    tool_code: str
    offset_um: int


class SubmissionOut(Schema):
    id: int
    tool_code: str
    offset_um: int
    status: str
    verdict: str
    # 认领人落款：与认领进程写入、改派后落款三处同源（都来自 claimant_name）。
    claimant_name: str
    claimed_at: Optional[datetime]
    created_at: datetime
    reviewed_at: Optional[datetime]


class ReassignIn(Schema):
    to_username: str


class ReassignLogOut(Schema):
    id: int
    submission_id: Optional[int]
    submission_label: str
    tool_code: str
    from_claimant_name: str
    to_claimant_name: str
    operator_name: str
    created_at: datetime


class ClaimantOut(Schema):
    id: int
    username: str
    display_name: str


class ListFilters(Schema):
    status: Optional[str] = None
    claimant: Optional[str] = None  # 按认领人落款名精确筛
    tool_code: Optional[str] = None  # 按刀号核对
    signed: Optional[bool] = None  # 仅看已落款（有认领人）的清单


def _to_out(row: OffsetSubmission) -> SubmissionOut:
    return SubmissionOut(
        id=row.id,
        tool_code=row.tool_code,
        offset_um=row.offset_um,
        status=row.status,
        verdict=row.verdict or "",
        claimant_name=row.claimant_name or "",
        claimed_at=row.claimed_at,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


def _log_to_out(row: ReassignLog) -> ReassignLogOut:
    return ReassignLogOut(
        id=row.id,
        submission_id=row.submission_id,
        submission_label=row.submission_label,
        tool_code=row.tool_code,
        from_claimant_name=row.from_claimant_name,
        to_claimant_name=row.to_claimant_name,
        operator_name=row.operator_name,
        created_at=row.created_at,
    )


@api.get("/health", response=HealthOut)
def health(request: HttpRequest):
    return {"status": "ok"}


@api.post("/auth/login", response=LoginOut)
def login(request: HttpRequest, body: LoginIn):
    try:
        user = User.objects.get(username=body.username)
    except User.DoesNotExist:
        raise HttpError(401, "用户名或密码错误")
    if not verify_password(body.password, user.password):
        raise HttpError(401, "用户名或密码错误")
    token = create_access_token(user)
    return {
        "token": token,
        "username": user.username,
        "role": user.role,
        "can_write": user.can_write,
    }


@api.get("/submissions", response=list[SubmissionOut], auth=bearer_auth)
def list_submissions(request: HttpRequest, filters: ListFilters = Query(...)):
    qs = OffsetSubmission.objects.all()
    if filters.status:
        qs = qs.filter(status=filters.status)
    if filters.claimant:
        qs = qs.filter(claimant_name=filters.claimant.strip())
    if filters.tool_code:
        qs = qs.filter(tool_code__icontains=filters.tool_code.strip())
    if filters.signed:
        qs = qs.exclude(claimant_name="")
    return [_to_out(r) for r in qs[:200]]


@api.get("/submissions/{submission_id}", response=SubmissionOut, auth=bearer_auth)
def get_submission(request: HttpRequest, submission_id: int):
    row = get_object_or_404(OffsetSubmission, pk=submission_id)
    return _to_out(row)


@api.post("/submissions", response=SubmissionOut, auth=bearer_auth)
def create_submission(request: HttpRequest, body: SubmissionIn):
    user: User = request.auth
    if not user.can_write:
        raise HttpError(403, "当前账号只读，不能提交刀补")
    tool_code = body.tool_code.strip()
    if not tool_code:
        raise HttpError(400, "刀具编号不能为空")
    row = OffsetSubmission.objects.create(
        tool_code=tool_code,
        offset_um=body.offset_um,
        submitted_by=user,
        status=OffsetSubmission.Status.PENDING,
    )
    return _to_out(row)


@api.get("/claimants", response=list[ClaimantOut], auth=bearer_auth)
def list_claimants(request: HttpRequest):
    """可作为落款/改派目标的认领名（操作员与 worker 认领进程账号）。"""
    rows = User.objects.filter(role=User.Role.MACHINIST, is_active=True).order_by(
        "username"
    )
    return [
        ClaimantOut(id=r.id, username=r.username, display_name=r.display_name)
        for r in rows
    ]


@api.post(
    "/submissions/{submission_id}/reassign",
    response=SubmissionOut,
    auth=bearer_auth,
)
def reassign(request: HttpRequest, submission_id: int, body: ReassignIn):
    """在途改派：仅操作员、仅复核中。已办结拒绝，痕迹簿同事务落账。"""
    operator: User = request.auth
    if not operator.can_write:
        raise HttpError(403, "复核侧只读，不能改派")
    target_name = body.to_username.strip()
    if not target_name:
        raise HttpError(400, "请指定新的认领人")
    try:
        target = User.objects.get(username=target_name, is_active=True)
    except User.DoesNotExist:
        raise HttpError(404, f"认领人不存在：{target_name}")
    if target.role != User.Role.MACHINIST:
        raise HttpError(400, "只能改派给认领（操作员）身份")
    try:
        row = reassign_submission(submission_id, target, operator)
    except ReassignError as exc:
        # 已办结 / 非在途 / 同名 → 409/400，调用方提示，且不会留下半截换人。
        status = 409 if "已办结" in str(exc) else 400
        raise HttpError(status, str(exc))
    return _to_out(row)


@api.get("/reassign-logs", response=list[ReassignLogOut], auth=bearer_auth)
def list_reassign_logs(
    request: HttpRequest,
    tool_code: Optional[str] = None,
    claimant: Optional[str] = None,
):
    """改派痕迹簿：操作员与复核员均可只读查阅。"""
    qs = ReassignLog.objects.all()
    if tool_code:
        qs = qs.filter(tool_code__icontains=tool_code.strip())
    if claimant:
        name = claimant.strip()
        qs = qs.filter(Q(from_claimant_name=name) | Q(to_claimant_name=name))
    return [_log_to_out(r) for r in qs[:200]]
