from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.db.session import get_db_session
from app.schemas.agent_workspace import (
    AnswerInput,
    ApplicantQuestionInput,
    ApprovalInput,
    DraftInput,
    PublicationInput,
    RunInput,
    VerifyInput,
)
from app.services.agent_workspace import AgentWorkspaceService

router = APIRouter(tags=["Local agents and applicant portal"])


def service(response: Response, session=Depends(get_db_session)):
    response.headers["Cache-Control"] = "private, no-store"
    value = AgentWorkspaceService(session, get_settings())
    value.enabled()
    return value


@router.get("/public/jobs")
async def jobs(offset: int = Query(0, ge=0, le=10000), svc=Depends(service)):
    return await svc.public_jobs(offset)


@router.get("/portal/api/verification")
async def verification(user=Depends(get_current_user), svc=Depends(service)):
    return await svc.verification_info(user)


@router.post("/portal/api/verification/request")
async def request_verification(user=Depends(get_current_user), svc=Depends(service)):
    return await svc.request_verification(user)


@router.post("/portal/api/verification/confirm")
async def confirm(
    data: VerifyInput, user=Depends(get_current_user), svc=Depends(service)
):
    return await svc.verify(user, data)


@router.post("/portal/api/drafts", status_code=201)
async def draft(data: DraftInput, user=Depends(get_current_user), svc=Depends(service)):
    return await svc.draft(user, data)


@router.put("/portal/api/applications/{submission_id}/resume")
async def pdf(
    submission_id: UUID,
    request: Request,
    filename: str = Query(..., min_length=5, max_length=200),
    user=Depends(get_current_user),
    svc=Depends(service),
):
    return await svc.upload_pdf(user, submission_id, filename, request)


@router.post("/portal/api/applications/{submission_id}/submit", status_code=202)
async def submit(
    submission_id: UUID,
    data: RunInput,
    user=Depends(get_current_user),
    svc=Depends(service),
):
    return await svc.submit(user, submission_id, data.mode)


@router.get("/portal/api/applications")
async def applications(user=Depends(get_current_user), svc=Depends(service)):
    return await svc.portal_list(user)


@router.post("/portal/api/applications/{submission_id}/answer", status_code=202)
async def answer(
    submission_id: UUID,
    data: AnswerInput,
    user=Depends(get_current_user),
    svc=Depends(service),
):
    return await svc.answer(user, submission_id, data)


@router.post("/portal/api/applications/{submission_id}/ask", status_code=202)
async def ask(
    submission_id: UUID,
    data: ApplicantQuestionInput,
    user=Depends(get_current_user),
    svc=Depends(service),
):
    return await svc.ask(user, submission_id, data)


@router.get("/portal/api/agent-runs/{run_id}")
async def own_run(run_id: UUID, user=Depends(get_current_user), svc=Depends(service)):
    return await svc.own_agent_run(user, run_id)


@router.get("/portal/api/notifications")
async def own_notifications(user=Depends(get_current_user), svc=Depends(service)):
    return await svc.notifications(user)


@router.post("/portal/api/notifications/{notification_id}/read")
async def read_notification(
    notification_id: UUID, user=Depends(get_current_user), svc=Depends(service)
):
    return await svc.read_notification(user, notification_id)


@router.get("/organizations/{organization_id}/career-publications/{job_id}")
async def publication(
    organization_id: UUID,
    job_id: UUID,
    user=Depends(get_current_user),
    svc=Depends(service),
):
    return await svc.publication(organization_id, job_id, user)


@router.put("/organizations/{organization_id}/career-publications/{job_id}")
async def publish(
    organization_id: UUID,
    job_id: UUID,
    data: PublicationInput,
    user=Depends(get_current_user),
    svc=Depends(service),
):
    return await svc.publication(organization_id, job_id, user, data)


@router.get("/organizations/{organization_id}/applicant-submissions")
async def incoming(
    organization_id: UUID, user=Depends(get_current_user), svc=Depends(service)
):
    return await svc.list_submissions(organization_id, user)


@router.post(
    "/organizations/{organization_id}/applicant-submissions/{submission_id}/agent-runs",
    status_code=202,
)
async def review(
    organization_id: UUID,
    submission_id: UUID,
    data: RunInput,
    user=Depends(get_current_user),
    svc=Depends(service),
):
    return await svc.create_run(organization_id, submission_id, user, data)


@router.get("/organizations/{organization_id}/agent-runs")
async def runs(
    organization_id: UUID, user=Depends(get_current_user), svc=Depends(service)
):
    return await svc.runs(organization_id, user)


@router.get("/organizations/{organization_id}/agent-runs/{run_id}")
async def run(
    organization_id: UUID,
    run_id: UUID,
    user=Depends(get_current_user),
    svc=Depends(service),
):
    return await svc.run_view(await svc.get_run(organization_id, run_id, user), True)


@router.post("/organizations/{organization_id}/agent-runs/{run_id}/approval")
async def approval(
    organization_id: UUID,
    run_id: UUID,
    data: ApprovalInput,
    user=Depends(get_current_user),
    svc=Depends(service),
):
    return await svc.approve(organization_id, run_id, user, data)


@router.post("/organizations/{organization_id}/agent-runs/{run_id}/cancel")
async def cancel(
    organization_id: UUID,
    run_id: UUID,
    user=Depends(get_current_user),
    svc=Depends(service),
):
    return await svc.cancel(organization_id, run_id, user)


@router.get("/organizations/{organization_id}/agent-notifications")
async def notifications(
    organization_id: UUID, user=Depends(get_current_user), svc=Depends(service)
):
    return await svc.notifications(user, organization_id)


@router.get("/organizations/{organization_id}/agent-mail-status")
async def mail_status(
    organization_id: UUID, user=Depends(get_current_user), svc=Depends(service)
):
    return await svc.mail_status(organization_id, user)


@router.post("/organizations/{organization_id}/agent-mail-retry")
async def mail_retry(
    organization_id: UUID, user=Depends(get_current_user), svc=Depends(service)
):
    return await svc.mail_status(organization_id, user, True)
