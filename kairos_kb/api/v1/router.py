"""V1 API router — groups all v1 endpoints."""

from fastapi import APIRouter

from kairos_kb.api.v1.workspaces import router as workspaces_router
from kairos_kb.api.v1.catalog import router as catalog_router
from kairos_kb.api.v1.entities import router as entities_router
from kairos_kb.api.v1.jobs import router as jobs_router
from kairos_kb.api.v1.incidents import router as incidents_router
from kairos_kb.api.v1.agent import router as agent_router
from kairos_kb.api.v1.lineage import router as lineage_router
from kairos_kb.api.v1.warehouse import router as warehouse_router
from kairos_kb.api.v1.enrichment import router as enrichment_router
from kairos_kb.api.v1.mesh import router as mesh_router
from kairos_kb.api.v1.context import router as context_router
from kairos_kb.api.v1.agents import router as agents_router
from kairos_kb.api.v1.knowledge import router as knowledge_router
from kairos_kb.api.v1.evals import router as evals_router
from kairos_kb.api.v1.products import router as products_router
from kairos_kb.api.v1.test_console import router as test_router
from kairos_kb.api.v1.living import router as living_router
from kairos_kb.api.v1.companion import router as companion_router
from kairos_kb.api.v1.meetings import router as meetings_router

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(workspaces_router)
v1_router.include_router(catalog_router)
v1_router.include_router(entities_router)
v1_router.include_router(jobs_router)
v1_router.include_router(incidents_router)
v1_router.include_router(agent_router)
v1_router.include_router(lineage_router)
v1_router.include_router(warehouse_router)
v1_router.include_router(enrichment_router)
v1_router.include_router(mesh_router)
v1_router.include_router(context_router)
v1_router.include_router(agents_router)
v1_router.include_router(knowledge_router)
v1_router.include_router(evals_router)
v1_router.include_router(products_router)
v1_router.include_router(test_router)
v1_router.include_router(living_router)
v1_router.include_router(companion_router)
v1_router.include_router(meetings_router)
