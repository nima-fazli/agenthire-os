from sqlalchemy import func, or_, select, true

from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership


def literal_pattern(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def page_statement(kind, options, *, user_id, organization_id=None, status=None,
                   job_id=None, candidate_id=None):
    models = {"organizations": Organization, "jobs": Job,
              "candidates": Candidate, "applications": Application}
    model = models[kind]
    source = select(*model.__table__.c)
    statement = source
    if kind == "organizations":
        statement = statement.join(OrganizationMembership,
                                   OrganizationMembership.organization_id == Organization.id)
        statement = statement.where(OrganizationMembership.user_id == user_id)
        columns = (Organization.name, Organization.slug)
    else:
        statement = statement.where(model.organization_id == organization_id)
        if kind == "jobs":
            columns = (Job.title, Job.description)
        elif kind == "candidates":
            columns = (Candidate.full_name, Candidate.email, Candidate.headline, Candidate.location)
        else:
            statement = statement.join(Job, (Job.id == Application.job_id)
                                       & (Job.organization_id == Application.organization_id))
            statement = statement.join(Candidate, (Candidate.id == Application.candidate_id)
                                       & (Candidate.organization_id == Application.organization_id))
            statement = statement.add_columns(Job.title.label("job_title"),
                                               Candidate.full_name.label("candidate_name"))
            source = statement
            columns = (Job.title, Candidate.full_name)
            if job_id is not None:
                statement = statement.where(Application.job_id == job_id)
            if candidate_id is not None:
                statement = statement.where(Application.candidate_id == candidate_id)
        if status is not None:
            statement = statement.where(model.status == status)
    if options.q:
        statement = statement.where(or_(*(column.ilike(literal_pattern(options.q), escape="\\")
                                          for column in columns)))
    # Materialize IDs and sort keys, rather than every candidate's long summary.
    filtered = statement.with_only_columns(model.id, model.created_at,
                                            maintain_column_froms=True).cte("filtered")
    positions = (select(filtered.c.id).order_by(filtered.c.created_at.desc(), filtered.c.id.desc())
                 .limit(options.limit).offset(options.offset).cte("positions"))
    page = source.join(positions, model.id == positions.c.id).subquery("page")
    count = select(func.count().label("_total")).select_from(filtered).subquery("count")
    # One statement keeps the total and rows in the same PostgreSQL snapshot.
    # LEFT JOIN also returns the total for an empty or out-of-range page.
    return select(*page.c, count.c._total).select_from(count.outerjoin(page, true())).order_by(
        page.c.created_at.desc(), page.c.id.desc())


class RecruitingRepository:
    def __init__(self, session):
        self.session = session

    async def page(self, kind, options, **scope):
        result = await self.session.execute(page_statement(kind, options, **scope))
        rows = [dict(row) for row in result.mappings().all()]
        return {
            "items": [{key: value for key, value in row.items() if key != "_total"}
                      for row in rows if row["id"] is not None],
            "total": rows[0]["_total"] if rows else 0,
            "limit": options.limit, "offset": options.offset,
        }
