import asyncio

from sqlalchemy.exc import DBAPIError

from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.semantic_embeddings import EmbeddingFailure, normalized_vector
from app.core.semantic_retrieval import fuse, query_input
from app.repositories.job_retrieval import JobRetrievalRepository
from app.repositories.organization_membership import OrganizationMembershipRepository
from app.repositories.semantic_retrieval import SemanticRetrievalRepository
from app.schemas.semantic_retrieval import SemanticPage
from app.services.job import JobService


class SemanticRetrievalService:
    def __init__(self, session, settings, encoder):
        self._session, self._settings, self._encoder = session, settings, encoder
        self._memberships = OrganizationMembershipRepository(session)
        self._profiles = JobRetrievalRepository(session)
        self._jobs = JobService(session)
        self._repository = SemanticRetrievalRepository(session)

    async def search(self, data, *, organization_id, user_id, job_id=None):
        profile = None
        try:
            if await self._memberships.get_by_user_and_organization(
                organization_id=organization_id, user_id=user_id
            ) is None:
                raise NotFoundError(code="ORGANIZATION_NOT_FOUND", message="Organization was not found.")
            if job_id is not None:
                await self._jobs.get_for_user(job_id, organization_id=organization_id, user_id=user_id)
                current = await self._profiles.get_profile(
                    organization_id=organization_id, user_id=user_id, job_id=job_id)
                if current is None:
                    raise NotFoundError(code="JOB_SEARCH_PROFILE_NOT_FOUND", message="Job search profile was not found.")
                q = current.query_text
                profile = {"revision": current.revision, "updated_at": current.updated_at}
            else:
                q = data.q
            if not self._settings.semantic_enabled:
                raise AppError(code="SEMANTIC_DISABLED", message="Local semantic processing is disabled.", status_code=503)
            await self._session.rollback()
            async with asyncio.timeout(self._settings.embedding_timeout_seconds):
                identity = await self._encoder.identity()
                values = await self._encoder.encode((query_input(q),), identity)
            if len(values) != 1:
                raise EmbeddingFailure("EMBEDDING_VECTOR_INVALID")
            vector = normalized_vector(values[0])
            result = await self._repository.search(
                organization_id=organization_id, user_id=user_id, job_id=job_id,
                profile=profile, data=data, q=q, vector=vector, identity=identity,
                timeout_ms=self._settings.document_search_timeout_ms,
            )
            if not result["authorized"]:
                raise NotFoundError(code="ORGANIZATION_NOT_FOUND", message="Organization was not found.")
            if not result["job_exists"]:
                raise NotFoundError(code="JOB_NOT_FOUND", message="Job was not found.")
            if not result["profile_current"]:
                raise ConflictError(code="JOB_SEARCH_PROFILE_CHANGED", message="Job search profile changed. Retry retrieval.")
            hits = fuse(result["rows"], mode=data.mode, candidates=job_id is not None)
            return SemanticPage(
                model_digest=identity.digest, mode=data.mode,
                score_kind="cosine_similarity" if data.mode == "semantic" else "reciprocal_rank_fusion",
                unit="candidate" if job_id is not None else "chunk", job_id=job_id,
                profile_revision=profile["revision"] if profile else None,
                profile_updated_at=profile["updated_at"] if profile else None,
                applicants_only=data.applicants_only if job_id is not None else False,
                eligible_chunks=result["eligible_chunks"], embedded_chunks=result["embedded_chunks"],
                pool_truncated=result["pool_truncated"], pooled_count=len(hits),
                limit=data.limit, items=hits[:data.limit],
            )
        except EmbeddingFailure as error:
            raise AppError(code=error.code, message="Local embedding model is unavailable or incompatible.", status_code=503) from error
        except TimeoutError as error:
            raise AppError(code="SEMANTIC_MODEL_TIMEOUT", message="Local query encoding exceeded its execution limit.", status_code=503) from error
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) == "57014":
                raise AppError(code="SEMANTIC_RETRIEVAL_TIMEOUT", message="Retrieval exceeded its database execution limit.", status_code=503) from error
            raise
        finally:
            await self._session.rollback()
