# AI-Native Data Platform Intelligence
## Product Vision, Architecture & Technical Development Plan

**Initial Platform:** Databricks  
**Initial Use Case:** Data Pipeline Failure RCA  
**Long-Term Vision:** AI-native Data Engineering / Autonomous DataOps Platform

---

# 1. Executive Summary

The proposed product is a SaaS platform that connects to a customer's modern data platform, initially Databricks, and constructs a continuously updated, machine-readable representation of the customer's data ecosystem.

This representation will be called the **Synthetic Warehouse**.

The Synthetic Warehouse is not intended to replicate the customer's actual data. Instead, it will represent the **structure, relationships, history, semantics, lineage, operational behaviour, and evidence surrounding the data platform**.

On top of this Synthetic Warehouse, specialized AI agents will provide data-engineering capabilities such as:

- Pipeline failure RCA
- Upstream/downstream impact analysis
- Data quality investigation
- Schema-change detection
- Pipeline dependency analysis
- Root-cause identification
- Remediation planning
- Eventually, controlled autonomous remediation

The long-term architecture will introduce an **Agent Gateway / Supervisor** that routes requests to specialized MCP servers and agents.

The fundamental product thesis is:

> **Build a machine-readable, continuously updated representation of an organization's data platform that AI agents can reliably reason over.**

The moat is therefore not simply "multiple AI agents."

The core technological asset is the combination of:

1. A deeply structured Synthetic Warehouse
2. Temporal understanding of the data platform
3. Table- and column-level lineage
4. Semantic understanding
5. Evidence-backed reasoning
6. Governed MCP interfaces
7. Controlled autonomous DataOps

---

# 2. Product Vision

The long-term vision is an **AI Data Engineer** capable of understanding and operating a company's data platform.

A user should eventually be able to ask:

> "Why did the customer 360 pipeline fail?"

> "What changed since yesterday that caused this?"

> "What downstream datasets are affected?"

> "Which pipelines will be affected if I change this column?"

> "Why is this dashboard showing incorrect numbers?"

> "Which upstream dataset is responsible for this anomaly?"

> "Create a remediation plan."

> "Create a PR with the proposed fix."

> "Validate the fix and rerun the pipeline."

The system should provide not merely an answer, but an **evidence-backed investigation**.

---

# 3. Core Product Principle

The system should follow this fundamental architecture:

**Deterministic extraction → canonical representation → AI enrichment → evidence-backed reasoning**

AI should not be responsible for discovering facts that can be deterministically retrieved from Databricks.

For example:

Bad approach:

```text
Databricks → LLM → "What tables exist?"
```

Better approach:

```text
Databricks
    ↓
Connector
    ↓
Deterministic extraction
    ↓
Synthetic Warehouse
    ↓
AI enrichment / reasoning
```

The connector establishes facts.

AI agents interpret, classify, correlate and reason over those facts.

This separation improves:

- Reliability
- Cost
- Auditability
- Reproducibility
- Security
- Evaluation
- Debugging

---

# 4. High-Level Architecture

```text
                         ┌──────────────────────┐
                         │        USER          │
                         │                      │
                         │ "Why did this fail?" │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   SUPERVISOR AGENT   │
                         └──────────┬───────────┘
                                    │
                         ┌──────────┴──────────┐
                         │                     │
                         ▼                     ▼
                  Investigation          Remediation
                         │                     │
                         ▼                     ▼
                ┌────────────────┐      ┌───────────────┐
                │ Agent Gateway  │      │ Policy Engine │
                └───────┬────────┘      └───────┬───────┘
                        │                       │
             ┌──────────┼──────────┐            │
             ▼          ▼          ▼            ▼
          Metadata   Pipeline   Lineage       Actions
             │          │          │
             └──────────┼──────────┘
                        ▼
             ┌────────────────────────┐
             │   SYNTHETIC WAREHOUSE  │
             │                        │
             │ Entity Graph            │
             │ Temporal State          │
             │ Semantic Layer          │
             │ Evidence                │
             │ Observations            │
             │ Change Events           │
             └───────────┬────────────┘
                         │
                         ▼
                ┌──────────────────┐
                │    CONNECTORS    │
                └────────┬─────────┘
                         │
                         ▼
                    DATABRICKS
```

---

# 5. Four Major System Layers

## 5.1 Connector Layer

Responsible for extracting factual information from the customer's data platform.

For the first version:

**Databricks Connector**

It will interact with:

- Unity Catalog
- Information Schema
- Jobs APIs
- Lineage system tables
- Query history
- Table history
- Job/run information
- Audit information
- Pipeline information
- Other relevant system tables/APIs

---

## 5.2 Synthetic Warehouse Layer

The canonical representation of the customer's data platform.

It contains:

- Metadata
- Entities
- Relationships
- Lineage
- Transformations
- Historical state
- Semantic classifications
- Operational observations
- Evidence
- Change events

This becomes the primary knowledge substrate for the agents.

---

## 5.3 Agent Layer

Specialized agents reason over the Synthetic Warehouse.

Initial agents:

1. Metadata Agent
2. Pipeline Agent
3. Lineage Agent
4. Semantic Agent
5. Quality Agent
6. Operations Agent

Higher-level agents:

7. RCA Agent
8. Remediation Agent
9. Supervisor Agent

---

## 5.4 Experience Layer

The user-facing interface.

Initial interface:

- Workspace overview
- Pipeline health
- Incidents
- RCA investigation
- Evidence
- Lineage visualization
- Proposed remediation

Eventually:

- Natural-language Data Engineer
- Chat interface
- Automated incident investigation
- Remediation approval
- PR generation
- Autonomous operations

---

# 6. Synthetic Warehouse

The Synthetic Warehouse is the central component of the system.

It should not be thought of as merely another database.

Conceptually, it is:

> **A machine-readable operational knowledge graph of the customer's data platform.**

It represents the customer's data ecosystem without needing to replicate the customer's underlying datasets.

---

# 7. Synthetic Warehouse Responsibilities

The Synthetic Warehouse should represent:

### Structural metadata

- Workspace
- Metastore
- Catalog
- Schema
- Table
- View
- Volume
- Column
- Function
- Model

### Pipeline information

- Job
- Task
- Run
- Task Run
- Dependency
- Transformation
- Query
- Notebook
- Pipeline

### Lineage

- Table-level lineage
- Column-level lineage
- Upstream relationships
- Downstream relationships
- Transformation relationships

### Semantic information

- Business domain
- Business entity
- Business concept
- Metric
- Identifier
- Classification

### Operational information

- Run status
- Failure
- Retry
- Execution time
- Freshness
- SLA
- Anomaly

### Temporal information

- Versions
- Changes
- Snapshots
- Historical states
- Change events

### Evidence

- Source
- Timestamp
- Observation
- Query
- API response
- Error
- Transformation
- Historical state

---

# 8. Canonical Entity Model

Initial entities:

```text
Workspace
Metastore

Catalog
Schema
Table
View
Column
Volume

Job
Task
Run
TaskRun

Transformation
Query
Pipeline

Tag
BusinessEntity
DataDomain

LineageEdge

Evidence
Observation
ChangeEvent
```

---

# 9. Relationship Model

Example relationships:

```text
Catalog
 └── CONTAINS → Schema

Schema
 └── CONTAINS → Table

Table
 └── CONTAINS → Column

Job
 └── CONTAINS → Task

Task
 └── EXECUTES → Transformation

Task
 └── READS → Table

Task
 └── WRITES → Table

Table
 └── DERIVED_FROM → Table

Column
 └── DERIVED_FROM → Column

Run
 └── EXECUTES → Job

TaskRun
 └── EXECUTES → Task

Entity
 └── HAS_EVIDENCE → Evidence

Entity
 └── HAS_CHANGE → ChangeEvent
```

---

# 10. Stable Entity Identity

Every entity should have a stable internal ID.

Example:

```text
workspace:abc

catalog:workspace_abc.prod

schema:workspace_abc.prod.customer

table:workspace_abc.prod.customer.orders

column:workspace_abc.prod.customer.orders.customer_id
```

For jobs:

```text
job:workspace_abc:123456

task:workspace_abc:123456:load_orders

run:workspace_abc:123456:987654
```

Each entity should retain:

```text
entity_id
source_system
source_native_id
current_name
previous_names
workspace_id
```

Names should not be the sole identity mechanism because data-platform objects can be renamed.

---

# 11. Temporal Layer

Temporal awareness is a first-class capability.

Every important entity should support:

```text
first_seen_at
last_seen_at
valid_from
valid_to
observed_at
source_timestamp
version
```

Example:

```text
customer_status

2026-08-10
STRING
EXISTS

2026-08-11
STRING
EXISTS

2026-08-12
REMOVED
```

This allows the system to answer:

> "What changed between the last successful run and the failed run?"

This is fundamental to RCA.

The product should maintain its own historical snapshots because source-platform history may have finite retention.

---

# 12. Evidence Layer

Every important inference should have associated evidence.

The system should never simply store:

```text
customer_email → PII
```

Instead:

```text
customer_email
    ↓
classification: PII
confidence: 0.97
    ↓
Evidence #1:
column name = customer_email

Evidence #2:
table comment

Evidence #3:
upstream lineage

Evidence #4:
usage pattern

Classified by:
Metadata Agent v1.x
```

Each evidence record should contain:

```text
evidence_id
source_type
source_id
entity_id
observed_at
content
content_hash
metadata
```

AI-generated claims should also record:

```text
claim
confidence
model
model_version
prompt_version
evidence_ids
created_at
```

This allows every important conclusion to be traced back to factual observations.

---

# 13. Catalog / Metadata Agent

## Purpose

Create the deepest-grain representation of Unity Catalog and enrich it with semantic classifications.

## Responsibilities

### Structural extraction

- Catalogs
- Schemas
- Tables
- Views
- Volumes
- Columns
- Properties
- Comments
- Tags
- Owners
- Permissions
- Statistics where available
- Table history

### Semantic enrichment

For example:

```json
{
  "entity_type": "column",
  "column": "customer_email",
  "business_domain": "customer",
  "semantic_type": "email",
  "sensitivity": "potential_pii",
  "confidence": 0.94
}
```

The agent should enrich deterministic facts rather than create them.

---

# 14. Pipeline Information Agent

## Purpose

Understand how data is produced and transformed.

The agent should represent:

```text
Job
 ↓
Task
 ↓
Transformation
 ↓
Input datasets
 ↓
Output datasets
```

For each job:

- Job ID
- Name
- Owner
- Schedule
- Trigger
- Parameters
- Dependencies
- Compute
- Retry configuration
- Timeout

For each task:

- Task type
- Notebook
- SQL
- Python
- dbt
- Pipeline
- Input datasets
- Output datasets
- Transformation logic
- Dependencies

The system should preserve the actual transformation source where possible.

---

# 15. Deep Transformation Representation

For example:

```sql
SELECT
    customer_id,
    SUM(amount) AS lifetime_value
FROM orders
WHERE status = 'COMPLETED'
GROUP BY customer_id
```

The Synthetic Warehouse should not only record:

```text
orders → customer_lifetime_value
```

It should ideally represent:

```text
orders.amount
       │
       │ SUM()
       ▼
customer_lifetime_value

orders.status
       │
       │ FILTER status = COMPLETED
       ▼
customer_lifetime_value
```

This allows the system to reason at column level.

---

# 16. Lineage Agent

## Purpose

Build the complete table- and column-level lineage graph.

The agent should identify:

- Upstream tables
- Downstream tables
- Upstream columns
- Downstream columns
- Transformation logic
- Jobs responsible for transformations
- Tasks responsible for transformations
- Statements
- Runs
- Historical lineage

A lineage edge should contain:

```text
source_column
target_column

transformation
statement_id
task_id
job_id
run_id

observed_at
confidence
evidence
```

Example:

```text
orders.amount
       │
       │ SUM()
       ▼
customer.total_spend
```

---

# 17. Semantic / Ontology Agent

This is an important additional agent.

Its purpose is to understand what data means rather than merely how it is structured.

It can infer relationships such as:

```text
customer_id
    ↓
Customer entity

order_id
    ↓
Order entity

amount
    ↓
Financial metric

created_at
    ↓
Event timestamp
```

It can also identify potentially equivalent concepts:

```text
customer
customers
customer_master
customer_dim
cust
```

The Semantic Agent should never overwrite factual metadata.

Store separately:

```text
FACT
```

and:

```text
INFERENCE
```

---

# 18. Data Quality Agent

The Data Quality Agent understands how datasets behave over time.

For important tables it can maintain:

```text
row_count
null_percentage
distinct_count
freshness
partition_count
schema
data_volume
```

Historical behaviour:

```text
orders

10.2M rows
10.5M rows
10.4M rows
10.7M rows
1.1M rows ← anomaly
```

This becomes additional evidence during RCA.

---

# 19. Operations Agent

The Operations Agent understands execution behaviour.

It should capture:

- Job runs
- Task runs
- Failures
- Retries
- Repair history
- Execution time
- Error messages
- Query failures
- Operational anomalies
- Compute-related failures

It becomes the primary entry point for incidents.

---

# 20. Agent Responsibilities Summary

| Agent | Primary Responsibility |
|---|---|
| Metadata Agent | Unity Catalog and metadata |
| Pipeline Agent | Jobs, tasks, transformations |
| Lineage Agent | Table/column lineage |
| Semantic Agent | Business meaning and ontology |
| Quality Agent | Data quality and anomalies |
| Operations Agent | Runs, failures and operational state |
| RCA Agent | Root-cause investigation |
| Remediation Agent | Fix planning |
| Supervisor Agent | Orchestration and routing |

The first six primarily **build and enrich the platform's knowledge**.

The RCA and Remediation agents **reason over that knowledge**.

The Supervisor orchestrates the system.

---

# 21. Ingestion Architecture

The ingestion system should be incremental.

```text
                  Sync Manager
                      │
       ┌──────────────┼──────────────┐
       ▼              ▼              ▼
  Catalog Sync    Job Sync       Lineage Sync
       │              │              │
       └──────────────┼──────────────┘
                      ▼
               Normalization
                      │
                      ▼
               Change Detection
                      │
             ┌────────┴────────┐
             ▼                 ▼
        New entities       Changed entities
             │                 │
             └────────┬────────┘
                      ▼
                 Event Store
```

Initial synchronization:

```text
initial_sync
    ↓
full snapshot
```

Subsequent synchronization:

```text
incremental_sync
    ↓
diff
    ↓
change events
```

The entire workspace should not be unnecessarily reprocessed during every synchronization cycle.

---

# 22. Initial Databricks Scope

## Tier 1 — Core metadata

```text
Catalog
Schema
Table
View
Column
Properties
Tags
Comments
Owners
Privileges
```

## Tier 2 — Pipeline information

```text
Jobs
Tasks
Dependencies
Runs
Failures
```

## Tier 3 — Lineage and history

```text
Table lineage
Column lineage
Query history
Table history
```

## Tier 4 — Future expansion

```text
Audit logs
Clusters
Compute
Volumes
Pipelines
Dashboards
Git
Notebooks
```

---

# 23. Data Storage Architecture

The initial system should use a pragmatic polyglot architecture.

## PostgreSQL

Use for:

- Tenants
- Users
- Connections
- Configuration
- Synchronization state
- Entity metadata
- Relationships
- Agent runs

PostgreSQL can initially also represent graph relationships through relational tables.

Do not introduce a dedicated graph database until graph traversal requirements justify it.

---

## Object Storage

Use S3 for:

```text
raw/
snapshots/
evidence/
logs/
notebooks/
sql/
```

This stores large source artifacts and raw responses.

---

## Graph Layer

Initially:

```text
entities
relationships
lineage_edges
```

inside PostgreSQL.

Later, if traversal complexity becomes significant, evaluate a dedicated graph database.

---

## Vector Search

Use vector search only where semantic retrieval is valuable:

- Notebook source
- SQL
- Documentation
- Business descriptions
- Incident history
- Semantic context

The vector index should never become the system's source of truth.

---

# 24. Authentication and Security

The SaaS should use a service-principal / OAuth-based authentication model rather than depending on individual user PATs as the long-term architecture.

The connector should use the minimum privileges necessary and preferably operate read-only during the initial phases.

The product should support:

- Tenant isolation
- Workspace isolation
- Credential encryption
- Secret management
- RBAC
- Audit logging
- Fine-grained access
- Data retention policies
- Evidence access control

---

# 25. Data Privacy Strategy

The SaaS should avoid copying actual customer datasets whenever possible.

Prefer storing:

```text
Metadata
Schema
Lineage
Transformation logic
Operational information
Statistics
Evidence
```

rather than raw business data.

For enterprise deployments, eventually support a deployment architecture where the Synthetic Warehouse and sensitive components can operate within the customer's cloud/VPC.

---

# 26. RCA Engine

The first killer workflow is:

# "Why did my Databricks pipeline fail?"

The RCA process should be structured rather than simply sending a failure log to an LLM.

```text
Failed Run
    ↓
Identify Failed Task
    ↓
Extract Error
    ↓
Find Relevant Entities
    ↓
Retrieve Evidence
    ↓
Check Recent Changes
    ↓
Traverse Lineage
    ↓
Check Historical Behaviour
    ↓
Generate Candidate Causes
    ↓
Rank Causes
    ↓
Validate Against Evidence
    ↓
Produce RCA
```

---

# 27. RCA Investigation Example

Suppose:

```text
Pipeline:
customer_360_daily

Status:
FAILED
```

The system discovers:

```text
Task:
build_customer_360

Error:
Column customer_status cannot be resolved
```

Metadata investigation:

```text
customer_status
    ↓
silver.customer
    ↓
Column no longer exists
```

Historical investigation:

```text
Yesterday:
customer_status STRING

Today:
customer_status REMOVED
```

Pipeline investigation:

```sql
SELECT
    customer_id,
    customer_status
FROM silver.customer
```

Lineage investigation:

```text
silver.customer.customer_status
             ↓
customer_360.customer_status
```

Final RCA:

```text
ROOT CAUSE

Upstream schema change.

customer_status was removed from
silver.customer at 02:14 UTC.

The customer_360_daily task still references
the removed column.

Confidence: 97%
```

Evidence:

```text
✓ Schema history
✓ Failed SQL
✓ Column lineage
✓ Previous successful run
✓ Upstream modification
```

---

# 28. RCA Output Contract

The backend should produce a structured RCA object.

```json
{
  "incident_id": "...",
  "job_id": "...",
  "run_id": "...",

  "root_cause": {
    "category": "SCHEMA_CHANGE",
    "entity_id": "...",
    "description": "...",
    "confidence": 0.97
  },

  "evidence": [
    "...",
    "...",
    "..."
  ],

  "timeline": [
    "...",
    "...",
    "..."
  ],

  "affected_assets": [
    "...",
    "..."
  ],

  "proposed_remediation": {
    "type": "CODE_CHANGE",
    "description": "...",
    "risk": "MEDIUM"
  }
}
```

This structured representation is preferable to storing only a large LLM-generated response.

---

# 29. MCP Architecture

Once the Synthetic Warehouse and internal services are working, introduce MCP.

The MCP servers should provide domain-specific capabilities.

## Metadata MCP

```text
get_table()
get_column()
search_entities()
get_schema()
get_tags()
get_permissions()
get_table_changes()
```

## Lineage MCP

```text
get_upstream()
get_downstream()
get_column_lineage()
find_impact()
get_transformation()
```

## Pipeline MCP

```text
get_job()
get_task()
get_transformation()
get_dependencies()
```

## Operations MCP

```text
get_failed_run()
get_run_history()
get_task_failure()
get_error()
get_retry_history()
```

## Quality MCP

```text
get_quality_profile()
get_anomalies()
get_freshness()
compare_periods()
```

The MCP layer should be a controlled interface over internal domain services rather than direct arbitrary database access.

---

# 30. Agent Gateway / Supervisor

The "Super Server" should eventually become an:

# Agent Gateway / Agent Orchestrator

Its responsibilities:

- Intent classification
- Task decomposition
- Agent selection
- MCP routing
- Context management
- Evidence aggregation
- Policy enforcement
- Response synthesis
- Action authorization

Example:

```text
User:
Why did customer_360_daily fail?

        ↓

Supervisor

        ↓

Operations MCP
"What failed?"

        ↓

Pipeline MCP
"What task and SQL?"

        ↓

Metadata MCP
"What changed?"

        ↓

Lineage MCP
"What is upstream?"

        ↓

Quality MCP
"Is the upstream dataset anomalous?"

        ↓

Evidence Aggregation

        ↓

RCA Agent

        ↓

Evidence-backed RCA
```

---

# 31. Remediation Engine

RCA and remediation should be separate stages.

```text
Incident
    ↓
RCA
    ↓
Impact Analysis
    ↓
Remediation Planner
    ↓
Proposed Fix
    ↓
Validation Plan
    ↓
Human Approval
    ↓
Execution
```

Example:

```text
CHANGE

customer_status → status

FILE:
customer_360.sql

AFFECTED:
17 downstream assets

RISK:
Medium

VALIDATION:
✓ SQL compilation
✓ Schema compatibility
✓ Upstream availability
✓ Downstream impact check

ACTION:
Create PR
```

---

# 32. Controlled Actions

The system should never allow unrestricted LLM execution against production.

Actions should be typed and policy-controlled.

Examples:

```text
create_pr()
rerun_job()
pause_job()
update_configuration()
```

Potential permission model:

```text
READ
✓ Automatic

ANALYZE
✓ Automatic

PROPOSE
✓ Automatic

CREATE PR
✓ Configurable

RERUN JOB
⚠ Approval configurable

MODIFY PRODUCTION
🔴 Explicit approval
```

Eventually, low-risk operations can become fully autonomous.

---

# 33. User Interface

The first interface should be deliberately simple.

## Platform Dashboard

```text
Data Platform

1,284 Tables
84 Jobs
17 Incidents

Recent Incidents

🔴 customer_360_daily
   Schema mismatch
   14 min ago

🟡 orders_ingestion
   Freshness SLA breach
   2 hrs ago
```

---

# 34. Incident View

```text
customer_360_daily
FAILED

ROOT CAUSE

Upstream schema change.

customer_status was removed from
silver.customer at 02:14 UTC.

Confidence: 97%

EVIDENCE

✓ Schema history
✓ Failed SQL
✓ Column lineage
✓ Previous successful run
✓ Upstream modification

IMPACT

17 downstream assets

PROPOSED REMEDIATION

Replace customer_status with status
in task build_customer_360.

[Review Fix]
```

This should become the first major product demonstration.

---

# 35. Technology Stack

## Backend

**Python + FastAPI**

Reasons:

- AI ecosystem
- Databricks SDK ecosystem
- PySpark compatibility
- MCP support
- Strong data-engineering ecosystem
- Async API support

---

## Database

**PostgreSQL**

Use PostgreSQL for the initial application and Synthetic Warehouse representation.

---

## Object Storage

**Amazon S3**

For raw artifacts, snapshots, logs and evidence.

---

## Queue

**Amazon SQS**

Use for:

- Synchronization jobs
- Agent enrichment
- Incident processing
- Background tasks

---

## Frontend

**Next.js + React**

---

## AI

Create an internal LLM abstraction layer rather than hard-coding a single model.

Track:

```text
model
temperature
prompt_version
token_usage
latency
cost
```

This allows models to be replaced without redesigning the agent architecture.

---

## MCP

Use Python MCP tooling and expose domain-specific MCP servers.

---

# 36. Proposed Repository Structure

```text
platform-intelligence/
│
├── apps/
│   ├── api/
│   ├── worker/
│   ├── scheduler/
│   └── frontend/
│
├── connectors/
│   └── databricks/
│       ├── catalog.py
│       ├── jobs.py
│       ├── lineage.py
│       ├── query_history.py
│       ├── audit.py
│       └── tables.py
│
├── ingestion/
│   ├── extractors/
│   ├── normalizers/
│   ├── change_detection/
│   └── snapshots/
│
├── synthetic_warehouse/
│   ├── entities/
│   ├── relationships/
│   ├── evidence/
│   ├── temporal/
│   └── repositories/
│
├── agents/
│   ├── metadata/
│   ├── pipeline/
│   ├── lineage/
│   ├── semantic/
│   ├── quality/
│   ├── operations/
│   ├── rca/
│   └── remediation/
│
├── mcp/
│   ├── metadata/
│   ├── lineage/
│   ├── pipeline/
│   ├── quality/
│   └── operations/
│
├── orchestration/
│   ├── supervisor.py
│   ├── workflows/
│   └── policies/
│
├── evaluation/
│   ├── rca/
│   ├── lineage/
│   └── agents/
│
└── shared/
    ├── models/
    ├── auth/
    ├── logging/
    └── telemetry/
```

---

# 37. Development Roadmap

## Phase 0 — Architecture

Define:

- Product scope
- Entity model
- Relationship model
- Evidence model
- Temporal model
- Tenant model
- Security model

Do not build agents yet.

---

## Phase 1 — Databricks Connector

Implement:

```text
✓ Authentication
✓ Workspace connection
✓ Catalog discovery
✓ Schema discovery
✓ Table discovery
✓ Column discovery
✓ Properties
✓ Tags
✓ Comments
```

Milestone:

> Connect Databricks and see the entire Unity Catalog programmatically.

---

# Phase 2 — Synthetic Warehouse

Implement:

```text
✓ Entity model
✓ Relationships
✓ Stable IDs
✓ PostgreSQL schema
✓ Raw snapshot storage
✓ Incremental synchronization
✓ Change detection
```

Milestone:

> A machine-readable representation of the Databricks workspace exists independently of the UI.

---

# Phase 3 — Jobs + Lineage

Implement:

```text
✓ Jobs
✓ Tasks
✓ Runs
✓ Failures
✓ Table lineage
✓ Column lineage
✓ Transformations
```

Milestone:

> Given any dataset, the system can explain how it was produced and where it flows.

---

# Phase 4 — Evidence + Temporal Layer

Implement:

```text
✓ Evidence
✓ Observations
✓ Historical snapshots
✓ Change events
✓ Schema changes
✓ Lineage changes
✓ Job changes
```

Milestone:

> The system can explain what changed and when.

---

# Phase 5 — First AI Agent

Build the Metadata Agent.

Capabilities:

- Semantic classification
- Business domain inference
- Sensitivity classification
- Entity identification
- Description generation

Milestone:

> The system understands what the technical metadata means.

---

# Phase 6 — RCA Engine

Build:

```text
Failed run
 ↓
Failed task
 ↓
Error
 ↓
Affected entity
 ↓
Recent changes
 ↓
Lineage
 ↓
Historical state
 ↓
Candidate causes
 ↓
Evidence validation
 ↓
RCA
```

Milestone:

> "Why did this pipeline fail?" produces a defensible answer.

This is the **MVP**.

---

# Phase 7 — Quality + Operations

Add:

```text
✓ Freshness
✓ Row-count anomalies
✓ Schema anomalies
✓ Execution anomalies
✓ Query history
✓ Operational signals
```

Milestone:

> RCA can correlate structural, operational and behavioural evidence.

---

# Phase 8 — MCP

Expose:

```text
Metadata MCP
Lineage MCP
Pipeline MCP
Quality MCP
Operations MCP
```

Milestone:

> External agents can query the Synthetic Warehouse through controlled tools.

---

# Phase 9 — Supervisor

Build:

```text
User request
    ↓
Intent
    ↓
Task decomposition
    ↓
MCP calls
    ↓
Evidence aggregation
    ↓
Reasoning
    ↓
Answer
```

Milestone:

> The platform becomes a natural-language Data Engineering assistant.

---

# Phase 10 — Remediation

Build:

```text
RCA
 ↓
Proposed fix
 ↓
Impact analysis
 ↓
Validation
 ↓
PR
```

Milestone:

> The system can produce concrete, reviewable remediation.

---

# Phase 11 — Autonomous DataOps

Eventually:

```text
Incident
 ↓
RCA
 ↓
Remediation
 ↓
Validation
 ↓
Approval / Policy
 ↓
Execution
 ↓
Monitoring
```

Eventually some low-risk scenarios can be completely automated.

---

# 38. Development Priority

The priority should be:

```text
1. Connector
2. Synthetic Warehouse
3. Evidence
4. Temporal state
5. Lineage
6. Pipeline intelligence
7. RCA
8. Quality
9. MCP
10. Supervisor
11. Remediation
12. Autonomous execution
```

Do not reverse this order.

---

# 39. What NOT to Build Initially

Avoid starting with:

```text
❌ Six autonomous agents
❌ Complex multi-agent conversations
❌ Fully autonomous remediation
❌ Dedicated graph database
❌ Massive vector database
❌ Multi-cloud support
❌ Multiple data platforms
❌ Generic AI assistant
❌ Arbitrary production execution
```

The first objective is much narrower:

> **Build a trustworthy machine-readable representation of Databricks and use it to perform evidence-backed pipeline RCA.**

---

# 40. First-Week Implementation Plan

## Day 1

Create a Databricks test environment containing:

- Multiple catalogs
- Multiple schemas
- Tables
- Views
- Columns
- Tags
- Jobs
- Multiple tasks
- Dependencies
- Deliberate pipeline failures

---

## Day 2

Build:

```text
DatabricksConnector
```

with:

```text
list_catalogs()
list_schemas()
list_tables()
get_table()
list_columns()
get_table_history()
```

---

## Day 3

Design:

```text
Entity
Relationship
Observation
Evidence
ChangeEvent
```

---

## Day 4

Build:

```text
Databricks
    ↓
Extractor
    ↓
Normalizer
    ↓
PostgreSQL
```

The system should support:

```text
sync_workspace()
```

---

## Day 5

Build APIs:

```text
GET /entities/{id}

GET /entities/{id}/upstream

GET /entities/{id}/downstream

GET /entities/{id}/changes

GET /jobs/{id}

GET /runs/{id}

GET /incidents/{id}
```

Only after these foundations work should the first agent be introduced.

---

# 41. Evaluation Framework

A benchmark should be created before declaring the RCA system successful.

Build a dataset of approximately:

```text
100 historical incidents
```

Each incident should contain:

```text
Actual failure
Actual root cause
Affected tables
Affected columns
Actual change
Actual remediation
```

Evaluate the system against this benchmark.

---

# 42. Key Evaluation Metrics

## RCA Accuracy

Did the system identify the actual root cause?

---

## Evidence Precision

Did the cited evidence actually support the conclusion?

---

## Impact Recall

Did the system identify the relevant downstream assets?

---

## Remediation Correctness

Would the proposed fix actually solve the issue?

---

## Hallucination Rate

Did the agent invent facts, relationships or evidence?

---

## Investigation Efficiency

Measure:

- Number of tool calls
- Token usage
- Latency
- Cost

---

# 43. Primary Product Metric

The most important product metric should be:

# Mean Time to Root Cause

Example:

```text
Human engineer:
47 minutes

AI platform:
4 minutes
```

The product should ultimately demonstrate:

> **A substantial reduction in the time required to diagnose data-platform incidents while maintaining evidence-backed accuracy.**

The number of agents is not the product metric.

---

# 44. Long-Term Multi-Platform Architecture

Once Databricks is mature, introduce additional connectors:

```text
Databricks
Snowflake
BigQuery
Airflow
dbt
Fivetran
Kafka
GitHub
Jira
PagerDuty
Slack
```

The architecture should become:

```text
                 Your Platform
                      │
        ┌─────────────┼─────────────┐
        │             │             │
    Databricks     Snowflake     BigQuery
        │             │             │
        ▼             ▼             ▼
     Synthetic     Synthetic     Synthetic
     Platform      Platform      Platform
     Graph         Graph         Graph
        │             │             │
        └─────────────┼─────────────┘
                      │
                      ▼
                AI Data Engineer
```

The Synthetic Warehouse should therefore be **platform-independent at the conceptual level**, even if the initial implementation is Databricks-specific.

---

# 45. Enterprise Deployment Model

Eventually support:

```text
                 CUSTOMER CLOUD
┌────────────────────────────────────────┐
│                                        │
│ Databricks                             │
│      │                                 │
│      ▼                                 │
│ Connector / Collector                  │
│      │                                 │
│      ▼                                 │
│ Synthetic Warehouse                    │
│      │                                 │
│      ▼                                 │
│ MCP Servers / Agents                   │
│                                        │
└────────────────┬───────────────────────┘
                 │
          Secure Control Plane
                 │
                 ▼
            SaaS Platform
```

This reduces data-exfiltration concerns and may become important for enterprise adoption.

---

# 46. Final Product Evolution

The complete evolution should look like:

```text
                    TODAY
                      │
                      ▼
             Databricks Connector
                      │
                      ▼
              Synthetic Warehouse
                      │
                      ▼
               Evidence Engine
                      │
                      ▼
                RCA Engine
                      │
                      ▼
                First Agent
                      │
                      ▼
              More Knowledge
                      │
                      ▼
             MCP Architecture
                      │
                      ▼
                Supervisor
                      │
                      ▼
              Remediation
                      │
                      ▼
            Autonomous DataOps
```

---

# 47. North-Star Architecture

```text
                         ┌──────────────────────┐
                         │        USER          │
                         │                      │
                         │ "Why did this fail?" │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   SUPERVISOR AGENT   │
                         └──────────┬───────────┘
                                    │
                         ┌──────────┴──────────┐
                         │                     │
                         ▼                     ▼
                  Investigation          Remediation
                         │                     │
                         ▼                     ▼
                ┌────────────────┐      ┌───────────────┐
                │ Agent Gateway  │      │ Policy Engine │
                └───────┬────────┘      └───────┬───────┘
                        │                       │
             ┌──────────┼──────────┐            │
             ▼          ▼          ▼            ▼
          Metadata   Pipeline   Lineage       Actions
             │          │          │
             └──────────┼──────────┘
                        ▼
             ┌────────────────────────┐
             │   SYNTHETIC WAREHOUSE  │
             │                        │
             │ Entity Graph            │
             │ Temporal State          │
             │ Semantic Layer          │
             │ Evidence                │
             │ Observations            │
             │ Change Events           │
             └───────────┬────────────┘
                         │
                         ▼
                ┌──────────────────┐
                │    CONNECTORS    │
                └────────┬─────────┘
                         │
                         ▼
                    DATABRICKS
```

---

# 48. Final Strategic Principle

The product should not be built around the idea:

> **"Let's create six AI agents."**

The stronger thesis is:

> **"Let's create a continuously updated operational model of a company's data platform, and give AI agents reliable, governed access to it."**

The agents are consumers of that intelligence layer.

The Synthetic Warehouse is the foundation.

The evidence layer makes the reasoning trustworthy.

The temporal layer makes RCA possible.

The lineage graph makes impact analysis possible.

The MCP layer makes the knowledge reusable.

The Supervisor makes the system feel like an AI Data Engineer.

The remediation layer turns intelligence into action.

And eventually, controlled autonomous execution turns the platform into an **Autonomous DataOps system**.

---

# 49. MVP Definition

The first production-worthy MVP should be considered complete when a customer can:

```text
1. Connect a Databricks workspace

2. Synchronize Unity Catalog

3. Synchronize jobs and runs

4. Synchronize table/column lineage

5. Maintain historical changes

6. Query the Synthetic Warehouse

7. Detect a failed pipeline

8. Investigate the failure

9. Identify probable root cause

10. Provide concrete evidence

11. Identify affected downstream assets

12. Generate a remediation plan
```

The core user promise becomes:

> **Connect your Databricks workspace. We build a living intelligence model of your data platform and investigate pipeline failures with evidence, lineage and historical context.**

That is the foundation upon which the broader **AI Data Engineer** vision can be built.