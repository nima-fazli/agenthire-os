from fastapi import APIRouter

from app.api.routes.applications import router as applications_router
from app.api.routes.auth import router as auth_router
from app.api.routes.candidate_documents import router as candidate_documents_router
from app.api.routes.candidates import router as candidates_router
from app.api.routes.document_chunks import router as document_chunks_router
from app.api.routes.document_embeddings import router as document_embeddings_router
from app.api.routes.document_search import router as document_search_router
from app.api.routes.health import router as health_router
from app.api.routes.job_matching import router as job_matching_router
from app.api.routes.job_retrieval import router as job_retrieval_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.organizations import router as organizations_router
from app.api.routes.semantic_retrieval import router as semantic_retrieval_router
from app.api.routes.users import router as users_router

api_router = APIRouter()

api_router.include_router(health_router)

api_router.include_router(auth_router)

api_router.include_router(users_router)

api_router.include_router(organizations_router)

api_router.include_router(jobs_router)

api_router.include_router(candidates_router)

api_router.include_router(applications_router)

api_router.include_router(candidate_documents_router)

api_router.include_router(document_chunks_router)

api_router.include_router(document_embeddings_router)

api_router.include_router(document_search_router)

api_router.include_router(job_retrieval_router)

api_router.include_router(job_matching_router)

api_router.include_router(semantic_retrieval_router)
