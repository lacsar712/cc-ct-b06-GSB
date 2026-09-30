from datetime import datetime
from typing import Optional

from django.http import HttpRequest
from django.db.models import Q
from ninja import NinjaAPI, Query, Schema
from ninja.errors import HttpError

from desk.auth_utils import bearer_auth, create_access_token, verify_password
from desk.models import Claimant, OffsetSubmission, ReassignmentLog, User
from desk.services import ReassignmentError, reassign_submission

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
    claimant_id: Optional[int]
    claimant_name: str
    claimed_at: Optional[datetime]
    created_at: datetime
    reviewed_at: Optional[datetime]


class ClaimantOut(Schema):
    id: int
    name: str
    code: str
    active: bool


class ReassignmentOut(Schema):
    id: int
    submission_id: int
    tool_code: str
    from_claimant_id: Optional[int]
    to_claimant_id: Optional[int]
    from_name: str
    to_name: str
    operator_name: str
    note: str
    created_at: datetime


class ListFilters(Schema):
    claimant_id: Optional[int] = None
    tool_code: Optional[str] = None
    status: Optional[str] = None


class ReassignIn(Schema):
    to_claimant_id: int
    note: str = ""


def _to_out(row: OffsetSubmission) -> SubmissionOut:
    return SubmissionOut(
        id=row.id,
        tool_code=row.tool_code,
        offset_um=row.offset_um,
        status=row.status,
        verdict=row.verdict or "",
        claimant_id=row.claimant_id,
        claimant_name=row.claimant.name if row.claimant else "",
        claimed_at=row.claimed_at,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


def _to_reassignment_out(row: ReassignmentLog) -> ReassignmentOut:
    return ReassignmentOut(
        id=row.id,
        submission_id=row.submission_id,
        tool_code=row.tool_code,
        from_claimant_id=row.from_claimant_id,
        to_claimant_id=row.to_claimant_id,
        from_name=row.from_name,
        to_name=row.to_name,
        operator_name=row.operator_name,
        note=row.note,
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
    qs = OffsetSubmission.objects.select_related("claimant").all()
    if filters.claimant_id is not None:
        qs = qs.filter(claimant_id=filters.claimant_id)
    if filters.tool_code:
        qs = qs.filter(tool_code__icontains=filters.tool_code.strip())
    if filters.status:
        qs = qs.filter(status=filters.status)
    return [_to_out(r) for r in qs[:200]]


@api.get("/submissions/{submission_id}", response=SubmissionOut, auth=bearer_auth)
def get_submission(request: HttpRequest, submission_id: int):
    try:
        row = OffsetSubmission.objects.select_related("claimant").get(pk=submission_id)
    except OffsetSubmission.DoesNotExist:
        raise HttpError(404, "刀补记录不存在")
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
    # 复核员也可读：落款台要按认领名筛选、核对落款。
    return [
        ClaimantOut(id=c.id, name=c.name, code=c.code, active=c.active)
        for c in Claimant.objects.filter(active=True)
    ]


@api.get("/reassignments", response=list[ReassignmentOut], auth=bearer_auth)
def list_reassignments(request: HttpRequest, claimant_id: Optional[int] = None):
    # 痕迹簿对操作员与复核员都只读开放；改派另有写接口且仅限操作员。
    qs = ReassignmentLog.objects.all()
    if claimant_id is not None:
        qs = qs.filter(
            Q(to_claimant_id=claimant_id) | Q(from_claimant_id=claimant_id)
        )
    return [_to_reassignment_out(r) for r in qs[:200]]


@api.post(
    "/submissions/{submission_id}/reassign",
    response=ReassignmentOut,
    auth=bearer_auth,
)
def reassign(request: HttpRequest, submission_id: int, body: ReassignIn):
    user: User = request.auth
    # 复核侧只能阅读落款与痕迹簿，不能改派。
    if not user.can_write:
        raise HttpError(403, "复核侧只读，不能改派")
    try:
        log = reassign_submission(
            submission_id=submission_id,
            to_claimant_id=body.to_claimant_id,
            operator_name=user.username,
            note=body.note,
        )
    except ReassignmentError as exc:
        msg = str(exc)
        code = 404 if "不存在" in msg else 409
        raise HttpError(code, msg)
    return _to_reassignment_out(log)
