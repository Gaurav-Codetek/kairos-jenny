"""Synthetic Warehouse entity models.

Import all models here so Alembic can discover them via ``from kairos_kb.models import *``.
"""

from kairos_kb.models.workspace import Workspace
from kairos_kb.models.catalog import Catalog
from kairos_kb.models.schema import Schema
from kairos_kb.models.table import Table
from kairos_kb.models.column import Column
from kairos_kb.models.job import Job
from kairos_kb.models.task import Task
from kairos_kb.models.run import Run
from kairos_kb.models.task_run import TaskRun
from kairos_kb.models.lineage_edge import LineageEdge
from kairos_kb.models.evidence import Evidence
from kairos_kb.models.change_event import ChangeEvent
from kairos_kb.models.sync_state import SyncState
from kairos_kb.models.entity_profile import EntityProfile
from kairos_kb.models.discovered import DiscoveredEntity, DiscoveredRelation
from kairos_kb.models.enrichment_run import EnrichmentRun, EnrichmentItem, EnrichmentEvent
from kairos_kb.models.incident import Incident, RcaReport
from kairos_kb.models.context import AgentActivity, AgentClient, ContextDocument, ContextFeedback
from kairos_kb.models.knowledge import KnowledgeBinding, KnowledgeConcept, KnowledgePack, KnowledgeRelation
from kairos_kb.models.evaluation import EvalRun, EvalThread
from kairos_kb.models.data_product import DataProduct
from kairos_kb.models.living import AgentNote, AgentRun, MetricObservation, Watch
from kairos_kb.models.companion import CompanionConversation, CompanionMessage, CompanionPulse, CompanionState

__all__ = [
    "CompanionConversation",
    "CompanionMessage",
    "CompanionPulse",
    "CompanionState",
    "AgentNote",
    "AgentRun",
    "MetricObservation",
    "Watch",
    "DataProduct",
    "Workspace",
    "Catalog",
    "Schema",
    "Table",
    "Column",
    "Job",
    "Task",
    "Run",
    "TaskRun",
    "LineageEdge",
    "Evidence",
    "ChangeEvent",
    "SyncState",
    "EntityProfile",
    "DiscoveredEntity",
    "DiscoveredRelation",
    "EnrichmentRun",
    "EnrichmentItem",
    "EnrichmentEvent",
    "Incident",
    "RcaReport",
    "ContextDocument",
    "AgentClient",
    "AgentActivity",
    "ContextFeedback",
    "KnowledgePack",
    "KnowledgeConcept",
    "KnowledgeRelation",
    "EvalRun",
    "EvalThread",
    "KnowledgeBinding",
]
