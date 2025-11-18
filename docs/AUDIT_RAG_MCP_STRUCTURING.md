# RAG + MCP + Structuring Audit (Post-PR9)

**Date**: November 18, 2025
**Branch**: pr4-minUI
**Commit**: 9492024 (tool executor)
**Auditor**: Claude (Sonnet 4.5)
**Scope**: RAG/Knowledge, MCP Integration, Structured Outputs, Conversation/What-If Paths

---

## Executive Summary

This audit provides surgical precision on what actually exists vs. what is missing in the RAG, knowledge ingestion, MCP integration, and structured output systems after PR-9A (what-if replanning).

**Key Findings**:
- **RAG**: Schema 80% complete, but **0% runtime implementation** (no ingestion, no retrieval, no integration)
- **MCP**: **0% implemented** despite SPEC requirements (all tools use fixtures, no MCP client exists)
- **Structured Outputs**: **70% production-ready** (QAPlanResponse works, but day scheduling is stub-only)
- **Conversation/What-If**: **Fully functional** threading with parent_run_id, but ignores derived intent (critical bug)

---

## A. Knowledge Ingestion & Storage

### A.1 Database Models (Existing - 80% Complete)

#### KnowledgeItem Model
**File**: `backend/app/db/models.py:131-160`

```python
class KnowledgeItem(Base):
    """Knowledge item table - RAG content."""

    __tablename__ = "knowledge_item"
    __table_args__ = (Index("idx_knowledge_org_dest", "org_id", "dest_id"),)

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org.org_id"), nullable=False
    )
    dest_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("destination.dest_id"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    org: Mapped["Org"] = relationship("Org", back_populates="knowledge_items")
    destination: Mapped["Destination | None"] = relationship(
        "Destination", back_populates="knowledge_items"
    )
    embeddings: Mapped[list["Embedding"]] = relationship(
        "Embedding", back_populates="knowledge_item", cascade="all, delete-orphan"
    )
```

**Fields**:
- `item_id` (PK): UUID for each knowledge chunk
- `org_id` (FK): Multi-tenant isolation (all RAG scoped to org)
- `dest_id` (FK, optional): Links to destination (city/country), nullable for general knowledge
- `content`: Full text content (unstructured, no length limit)
- `metadata_`: JSONB flexible schema for tags, source URLs, confidence, etc.
- `created_at`: Timestamp for freshness tracking

**Relationships**:
- `Org → KnowledgeItem` (1:N): Each org has its own knowledge base
- `Destination → KnowledgeItem` (1:N, optional): Knowledge can be destination-specific
- `KnowledgeItem → Embedding` (1:N, cascade delete): Each chunk can have multiple embeddings

#### Embedding Model
**File**: `backend/app/db/models.py:162-186`

```python
class Embedding(Base):
    """Embedding table - pgvector embeddings for RAG."""

    __tablename__ = "embedding"

    embedding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_item.item_id", ondelete="CASCADE"),
        nullable=False,
    )
    # Note: vector column requires pgvector extension
    # This is a placeholder; actual pgvector integration would use pgvector types
    vector: Mapped[list[float] | None] = mapped_column(ARRAY(Numeric), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    knowledge_item: Mapped["KnowledgeItem"] = relationship(
        "KnowledgeItem", back_populates="embeddings"
    )
```

**Critical Issues**:
1. ⚠️ `vector` column uses `ARRAY(Numeric)` instead of pgvector's `vector` type
2. ❌ Missing `chunk_idx` field (needed for citation format: `knowledge:{item_id}#{chunk_idx}`)
3. ❌ Missing `content` field (chunks need their text stored for display in citations)
4. ⚠️ No ivfflat index (mentioned in code comment but not created in migration)

**Current Type vs. Required Type**:
```python
# Current (placeholder):
vector: Mapped[list[float] | None] = mapped_column(ARRAY(Numeric), nullable=True)

# Required (pgvector):
from pgvector.sqlalchemy import Vector
vector: Mapped[Vector] = mapped_column(Vector(1536), nullable=False)  # OpenAI ada-002
```

#### Destination Model
**File**: `backend/app/db/models.py:107-129`

```python
class Destination(Base):
    """Destination table - org-scoped city/country data."""

    __tablename__ = "destination"
    __table_args__ = (UniqueConstraint("org_id", "city", "country", name="uq_dest_org_city"),)

    dest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org.org_id"), nullable=False
    )
    city: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    geo: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fixture_path: Mapped[str | None] = mapped_column(Text, nullable=True)
```

**Purpose**: Links knowledge to specific cities/countries, enables destination-scoped RAG queries.

**Usage Pattern**:
```python
# Query knowledge for Paris
knowledge_items = session.query(KnowledgeItem).filter(
    KnowledgeItem.org_id == org_id,
    KnowledgeItem.dest_id == paris_dest_id
).all()
```

### A.2 Database Migration (Existing)

**File**: `backend/alembic/versions/001_initial.py:46-84`

```python
# knowledge_item table
op.create_table(
    'knowledge_item',
    sa.Column('item_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('org_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('dest_id', postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True),
              server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['dest_id'], ['destination.dest_id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['org.org_id'], ),
    sa.PrimaryKeyConstraint('item_id')
)
op.create_index('idx_knowledge_org_dest', 'knowledge_item', ['org_id', 'dest_id'])

# embedding table
op.create_table(
    'embedding',
    sa.Column('embedding_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('item_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('vector', postgresql.ARRAY(sa.Numeric()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True),
              server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['knowledge_item.item_id'],
                           ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('embedding_id')
)
# Note: ivfflat index not created yet (commented in model file)
```

**Created Indices**:
- `idx_knowledge_org_dest` on `(org_id, dest_id)` - Fast org+destination lookups
- Primary keys on `item_id`, `embedding_id`
- Foreign key cascades on delete

**Missing Indices**:
- ❌ No pgvector ivfflat/hnsw index for similarity search
- ❌ No index on `metadata_` JSONB fields (e.g., for tag filtering)

### A.3 Ingestion Paths (MISSING - 0% Implemented)

#### No HTTP Endpoints
**Search Results**: No matches for:
- `POST /knowledge`
- `/knowledge/items`
- `/knowledge/upload`
- `/documents`
- `FileUpload`
- `UploadFile`

**Conclusion**: **No API endpoints exist for knowledge ingestion**.

#### No Chunking Logic
**Search Results**: No matches for:
- `chunk_text()`
- `split_document()`
- `tiktoken`
- `RecursiveCharacterTextSplitter`
- Chunking parameters (token size, overlap)

**Expected per SPEC §12.1**:
```python
# Should exist but doesn't:
def chunk_document(
    text: str,
    max_tokens: int = 1000,  # 800-1200 range per SPEC
    overlap_tokens: int = 150,
    encoding: str = "cl100k_base"  # tiktoken for OpenAI
) -> list[str]:
    """Split document into overlapping chunks."""
    # NOT IMPLEMENTED
```

**Conclusion**: **No chunking implementation exists**.

#### No Embedding Generation
**Search Results**: No matches for:
- `generate_embeddings()`
- `openai.Embedding.create()`
- `ada-002`
- `text-embedding`
- Batch embedding processing

**Expected**:
```python
# Should exist but doesn't:
async def generate_embeddings_batch(
    chunks: list[str],
    model: str = "text-embedding-ada-002"
) -> list[list[float]]:
    """Generate embeddings for chunks using OpenAI."""
    # NOT IMPLEMENTED
```

**Conclusion**: **No embedding client exists**.

#### No Ingestion Scripts
**Search Results**: No matches in:
- `backend/scripts/`
- `backend/cli/`
- Management commands
- Alembic data migrations

**Expected**:
```bash
# Should exist but doesn't:
python -m backend.scripts.ingest_knowledge \
  --file path/to/paris_guide.pdf \
  --org-id abc-123 \
  --dest-id xyz-789 \
  --tags "guidebook,official"
```

**Conclusion**: **No ingestion tooling exists**.

### A.4 Metadata Schema (Undefined)

While `metadata_` is JSONB (flexible), there's no documented schema. Expected structure:

```python
# Proposed metadata structure (not enforced):
{
    "source": "guidebook" | "local_expert" | "traveler" | "api",
    "url": "https://...",  # Source URL
    "tags": ["art", "museum", "family_friendly"],
    "language": "en" | "fr" | ...,
    "confidence": 0.95,  # 0-1 quality score
    "author": "Paris Tourism Board",
    "updated_at": "2025-06-01T00:00:00Z",
    "license": "CC-BY-4.0"
}
```

**Current State**: No validation, no extraction, no standardization.

### A.5 What DOES NOT Exist (Summary)

| Component | Status | Impact |
|-----------|--------|--------|
| **HTTP Upload Endpoint** | ❌ Not implemented | Cannot ingest documents via API |
| **PDF Parser** | ❌ Not implemented | Cannot extract text from PDFs |
| **Markdown Parser** | ❌ Not implemented | Cannot chunk .md files |
| **Text Chunker** | ❌ Not implemented | Cannot split documents per SPEC §12.1 |
| **Embedding Generator** | ❌ Not implemented | Cannot create vectors for search |
| **OpenAI Client (embeddings)** | ❌ Not implemented | No ada-002 integration |
| **Batch Processor** | ❌ Not implemented | Cannot handle large doc sets efficiently |
| **Metadata Extractor** | ❌ Not implemented | Cannot parse tags, URLs, etc. |
| **pgvector Setup** | ⚠️ Schema only, no index | `vector` column exists but wrong type |
| **CLI Ingestion Tool** | ❌ Not implemented | No command-line upload |
| **Ingestion Tests** | ❌ Not implemented | No coverage of ingestion path |

### A.6 How a PDF Would (Not) Make It Into the Vector Store Today

**Current Reality**:
```
User uploads paris_guide.pdf
    ↓
❌ No endpoint to receive it
    ↓
(If manually inserted via SQL)
    ↓
❌ No parser to extract text
    ↓
(If text manually inserted)
    ↓
❌ No chunker to split into 800-1200 token segments
    ↓
(If chunks manually created)
    ↓
❌ No embedding generator to create vectors
    ↓
(If embeddings manually computed)
    ↓
⚠️ Could INSERT into embedding table, but vector type is wrong
    ↓
❌ No ivfflat index for similarity search
    ↓
RESULT: Cannot query or retrieve
```

**What Would Be Needed**:
1. `POST /knowledge/items` endpoint accepting multipart/form-data
2. PDF parser (e.g., PyPDF2, pdfplumber)
3. Tiktoken-based chunker with overlap
4. OpenAI embedding client (async, batched)
5. Proper pgvector column type + index
6. Repository layer for CRUD operations

---

## B. Retrieval & Graph Integration

### B.1 Retrieval Functions (MISSING - 0% Implemented)

#### Search Pattern Analysis
**Search across codebase for**:
- `"retriev"`: No retrieval functions found
- `"rag"`: Only references in models (Provenance.source can be "rag", but unused)
- `"knowledge"`: Only in model definitions, no business logic
- `"pgvector"`: Only in comments, no actual pgvector queries
- `"search_"`: No semantic search functions
- `"vector"`: Only column definition, no queries
- `"cosine"`: No cosine similarity calculations
- `"similarity"`: No similarity search
- `"embedding"`: Only table definition, no query code

**Conclusion**: **No retrieval code exists anywhere in the codebase**.

#### Expected Retrieval Function (Does Not Exist)

```python
# Should exist in backend/app/rag/retrieval.py but doesn't:

async def retrieve_knowledge(
    query: str,
    org_id: UUID,
    dest_id: UUID | None = None,
    top_k: int = 10,
    min_score: float = 0.7,
    session: AsyncSession = Depends(get_session)
) -> list[KnowledgeChunk]:
    """Retrieve relevant knowledge chunks via vector similarity.

    Args:
        query: Natural language query (e.g., "best art museums in Paris")
        org_id: Organization scope (multi-tenancy)
        dest_id: Optional destination filter
        top_k: Number of results to return
        min_score: Minimum cosine similarity threshold
        session: Database session

    Returns:
        List of KnowledgeChunk with content, metadata, and relevance scores
    """
    # 1. Generate query embedding
    query_vector = await generate_embedding(query)

    # 2. Vector similarity search with pgvector
    stmt = select(
        KnowledgeItem,
        Embedding.vector.cosine_distance(query_vector).label("distance")
    ).join(Embedding).filter(
        KnowledgeItem.org_id == org_id
    )

    if dest_id:
        stmt = stmt.filter(KnowledgeItem.dest_id == dest_id)

    stmt = stmt.order_by("distance").limit(top_k)

    results = await session.execute(stmt)

    # 3. Filter by threshold and build response
    chunks = []
    for item, distance in results:
        score = 1 - distance  # Convert distance to similarity
        if score >= min_score:
            chunks.append(KnowledgeChunk(
                item_id=item.item_id,
                content=item.content,
                metadata=item.metadata_,
                relevance_score=score,
                provenance=Provenance(
                    source="rag",
                    ref_id=str(item.item_id),
                    fetched_at=datetime.utcnow()
                )
            ))

    return chunks

# NOT IMPLEMENTED - This is what's missing
```

### B.2 Retrieval Result Models (Partially Defined)

#### Provenance Model (Exists, RAG-Ready)
**File**: `backend/app/models/common.py:68-84`

```python
class Provenance(BaseModel):
    """Provenance metadata for tool results."""

    source: str  # Tool identifier (e.g., "tool.weather", "rag", "user")
    ref_id: str | None = None  # ID in external system or knowledge_item.item_id
    source_url: str | None = None  # Direct link to source
    fetched_at: datetime
    cache_hit: bool | None = None
    response_digest: str | None = None
```

**RAG Usage Pattern** (not implemented but model supports it):
```python
# For RAG results, source would be:
Provenance(
    source="rag",  # Distinguishes from "tool.flights", "tool.weather"
    ref_id=str(knowledge_item.item_id),  # Link to knowledge_item table
    source_url=knowledge_item.metadata_.get("url"),  # Original source URL
    fetched_at=datetime.utcnow(),
    cache_hit=False,  # Not from cache
    response_digest=hashlib.sha256(content.encode()).hexdigest()
)
```

**Distinction in Provenance**:
- `source="tool.flights"` → External API/fixture
- `source="tool.weather"` → Weather API
- `source="rag"` → Vector search result from knowledge_item table
- `source="manual"` → User-provided data

#### KnowledgeChunk Model (Should Exist, Doesn't)

```python
# Expected model (not implemented):
class KnowledgeChunk(BaseModel):
    """Retrieved knowledge chunk with relevance scoring."""

    item_id: UUID  # knowledge_item.item_id
    chunk_idx: int  # Which chunk of the document (for citation)
    content: str  # Actual text content
    metadata: dict[str, Any]  # Tags, source, etc.
    relevance_score: float  # Cosine similarity (0-1)
    provenance: Provenance  # Source tracking
```

### B.3 Graph Integration (MISSING - 0% Implemented)

#### Current Graph Nodes
**File**: `backend/app/orchestration/graph.py:23-63`

```python
graph = StateGraph(GraphState)

# 8 nodes exist:
graph.add_node("intent", extract_intent_stub)       # Parse user input
graph.add_node("planner", plan_real)                 # Generate choices
graph.add_node("selector", selector_stub)            # Score and filter
graph.add_node("tool_exec", tool_exec_stub)          # Execute tools
graph.add_node("verifier", verify_stub)              # Check constraints
graph.add_node("repair", repair_stub)                # Fix violations
graph.add_node("synth", synth_node)                  # LLM synthesis
graph.add_node("responder", responder_stub)          # Final status

# NO RAG NODE EXISTS
```

**Observation**: There is **no `knowledge_retrieval` node** or any RAG integration point.

#### GraphState Fields
**File**: `backend/app/orchestration/state.py:19-56`

```python
@dataclass
class GraphState:
    """State passed between graph nodes."""

    # Identity
    run_id: UUID
    org_id: UUID
    user_id: UUID
    status: RunStatus = "pending"

    # Pipeline data
    intent: IntentV1 | None = None
    plan: PlanV1 | None = None
    choices: list[Choice] | None = None
    weather: list[WeatherDay] = field(default_factory=list)

    # Constraint checking
    violations: list[Violation] = field(default_factory=list)
    has_blocking_violations: bool = False

    # Output
    decisions: list[Decision] = field(default_factory=list)
    selector_logs: list[dict] = field(default_factory=list)
    answer: AnswerV1 | None = None
    citations: list[Citation] = field(default_factory=list)

    # Metadata
    sequence_counter: int = 0
```

**Missing RAG Fields**:
```python
# Should exist but doesn't:
retrieved_chunks: list[KnowledgeChunk] = field(default_factory=list)
rag_context: str | None = None  # Formatted RAG results for LLM prompt
knowledge_scores: dict[str, float] = field(default_factory=dict)
```

### B.4 Where RAG Should Be Invoked (Analysis)

#### Option 1: RAG During Planner Node (Context Gathering)
**Current Flow** (`planner.py:94-200`):
```python
async def plan_real(state: GraphState, session: AsyncSession) -> GraphState:
    """Real planner - fetches options from adapters."""

    # Current: Only external tools
    flights = await fetch_flights(...)
    lodging = await fetch_lodging(...)
    attractions = await fetch_attractions(...)
    weather = await fetch_weather(...)

    # MISSING: No RAG query here
    # Could add:
    # knowledge = await retrieve_knowledge(
    #     query=f"{intent.city} {' '.join(intent.prefs.themes)}",
    #     org_id=state.org_id,
    #     dest_id=get_destination_id(intent.city)
    # )

    return state
```

**Integration Point**:
```python
# Line 150-180 in planner.py (approximately):
async def plan_real(state: GraphState, session: AsyncSession) -> GraphState:
    intent = state.intent

    # External tools (existing)
    flights = await fetch_flights(...)
    lodging = await fetch_lodging(...)
    attractions = await fetch_attractions(...)

    # RAG retrieval (NEW - would go here)
    knowledge_query = f"{intent.city} attractions themes: {', '.join(intent.prefs.themes or [])}"
    rag_chunks = await retrieve_knowledge(
        query=knowledge_query,
        org_id=state.org_id,
        dest_id=get_destination_for_city(intent.city, session),
        top_k=10
    )

    # Merge RAG into choices with special provenance
    for chunk in rag_chunks:
        # Convert knowledge chunk to Choice with rag provenance
        if "attraction" in chunk.metadata.get("type", ""):
            choice = Choice(
                kind=ChoiceKind.attraction,
                option_ref=f"rag_{chunk.item_id}",
                features=extract_features_from_knowledge(chunk),
                provenance=chunk.provenance  # source="rag"
            )
            state.choices.append(choice)

    return state
```

#### Option 2: RAG During Synthesis (Context Enrichment)
**Current Flow** (`synth.py:15-107`):
```python
async def synth_node(state: GraphState, session: AsyncSession) -> GraphState:
    """Synthesize final answer using LLM."""

    # Current: Only uses choices, violations, selector_logs
    answer = await synthesize_answer_with_openai(
        intent=state.intent,
        choices=state.choices,
        violations=state.violations,
        selector_logs=state.selector_logs
    )

    # MISSING: No RAG context in prompt

    state.answer = answer
    state.citations = extract_citations_from_choices(state.choices)
    return state
```

**Integration Point**:
```python
# Line 50-80 in synth.py (approximately):
async def synth_node(state: GraphState, session: AsyncSession) -> GraphState:
    # Retrieve relevant context for synthesis (NEW)
    rag_query = f"Travel guide for {state.intent.city}"
    knowledge_context = await retrieve_knowledge(
        query=rag_query,
        org_id=state.org_id,
        top_k=5  # Fewer results for LLM context
    )

    # Format knowledge for LLM prompt
    rag_context_text = "\n\n".join([
        f"[K{i+1}] {chunk.content}"
        for i, chunk in enumerate(knowledge_context)
    ])

    # Enhanced synthesis with RAG
    answer = await synthesize_answer_with_openai(
        intent=state.intent,
        choices=state.choices,
        violations=state.violations,
        selector_logs=state.selector_logs,
        knowledge_context=rag_context_text  # NEW parameter
    )

    # Extract citations from both choices AND knowledge
    citations_from_choices = extract_citations_from_choices(state.choices)
    citations_from_rag = [
        Citation(claim=f"Knowledge: {chunk.content[:50]}...", provenance=chunk.provenance)
        for chunk in knowledge_context
    ]

    state.answer = answer
    state.citations = citations_from_choices + citations_from_rag
    return state
```

### B.5 How RAG Hits Would Be Handed to LLM

#### Current Synthesis Prompt (Without RAG)
**File**: `backend/app/llm/client.py:95-180` (approximate)

```python
def build_synthesis_prompt(
    intent: IntentV1,
    choices: list[Choice],
    violations: list[Violation],
    selector_logs: list[dict]
) -> str:
    """Build prompt for LLM synthesis."""

    prompt = f"""You are a travel planning assistant. Generate a markdown summary.

User Intent:
- City: {intent.city}
- Dates: {intent.date_window.start} to {intent.date_window.end}
- Budget: ${intent.budget_usd_cents / 100}
- Themes: {', '.join(intent.prefs.themes or [])}

Selected Options:
"""

    for i, choice in enumerate(choices):
        prompt += f"\n{i+1}. {choice.kind.value}: {choice.option_ref}"
        prompt += f"\n   Cost: ${choice.features.cost_usd_cents / 100}"

    # NO RAG CONTEXT HERE

    prompt += "\n\nGenerate a human-readable summary..."
    return prompt
```

#### Enhanced Synthesis Prompt (With RAG)

```python
# Proposed enhancement:
def build_synthesis_prompt_with_rag(
    intent: IntentV1,
    choices: list[Choice],
    violations: list[Violation],
    selector_logs: list[dict],
    knowledge_chunks: list[KnowledgeChunk]  # NEW
) -> str:
    """Build prompt with RAG context."""

    prompt = f"""You are a travel planning assistant. Generate a markdown summary.

User Intent:
- City: {intent.city}
- Dates: {intent.date_window.start} to {intent.date_window.end}
- Budget: ${intent.budget_usd_cents / 100}
- Themes: {', '.join(intent.prefs.themes or [])}

Relevant Knowledge (cite using [K1], [K2], etc.):
"""

    # RAG CONTEXT (NEW)
    for i, chunk in enumerate(knowledge_chunks, 1):
        prompt += f"\n[K{i}] {chunk.content}"
        if chunk.metadata.get("source"):
            prompt += f"\n    Source: {chunk.metadata['source']}"

    prompt += "\n\nSelected Options:\n"

    for i, choice in enumerate(choices, 1):
        prompt += f"\n{i}. {choice.kind.value}: {choice.option_ref}"
        prompt += f"\n   Cost: ${choice.features.cost_usd_cents / 100}"

        # Link to knowledge if relevant
        if choice.provenance.source == "rag":
            prompt += f"\n   See: [K{find_knowledge_index(choice.provenance.ref_id)}]"

    prompt += """

Generate a human-readable summary. When referencing knowledge, use citation format [K1], [K2].
Ensure all factual claims are grounded in either Selected Options or Relevant Knowledge.
"""

    return prompt
```

**Citation Extraction After LLM Response**:
```python
# LLM output:
"""
## Day 1: Art & Culture

Start your Paris journey at the Louvre [K1], which houses over 35,000 works
of art including the Mona Lisa. Plan to spend 3-4 hours here [K2].

For lunch, try the nearby Café Marly [K3] with views of the pyramid...
"""

# Extract [K1], [K2], [K3] and link to knowledge_item IDs
# This provides verifiable grounding for all claims
```

### B.6 Summary: RAG Retrieval Status

| Component | Status | Location | Notes |
|-----------|--------|----------|-------|
| **Retrieval Function** | ❌ Not implemented | Would be `rag/retrieval.py` | No vector search code exists |
| **Query Embedding** | ❌ Not implemented | Would be `rag/embedding.py` | Cannot embed user queries |
| **Vector Search** | ❌ Not implemented | N/A | No pgvector queries anywhere |
| **Top-K Selection** | ❌ Not implemented | N/A | No ranking/filtering |
| **MMR (diversity)** | ❌ Not implemented | N/A | No diversity re-ranking |
| **RAG Node in Graph** | ❌ Not implemented | `orchestration/graph.py` | No node for knowledge retrieval |
| **GraphState RAG Fields** | ❌ Not implemented | `orchestration/state.py` | No fields for storing RAG results |
| **LLM Prompt Integration** | ❌ Not implemented | `llm/client.py` | No RAG context in prompts |
| **Citation Extraction** | ⚠️ Partial | `citations/extract.py` | Extracts from choices, but no RAG source handling |
| **Provenance Model** | ✅ Complete | `models/common.py` | Supports `source="rag"` |

**Conclusion**: The schema foundation is solid (80%), but **the entire runtime layer is absent (0%)**. The system cannot retrieve, search, or cite knowledge until retrieval functions are built.

---

## C. MCP Integration (Tools via MCP & Fallbacks)

### C.1 MCP Code Search Results

**Search Pattern**: Comprehensive search for MCP-related code

```bash
# Searched for:
- "mcp" (any case)
- "model context protocol"
- "model_context_protocol"
- Directory patterns: */mcp/*, */mcp_*
- Configuration: MCP_*

Result: NO MATCHES FOUND
```

**Conclusion**: **No MCP code exists in this codebase**.

### C.2 SPEC Requirements (What Should Exist)

**File**: `SPEC.md:405-417` (approximate)

```markdown
### 4.2 MCP Integration

**Attractions Tool via MCP**:
- Connect to MCP server for attractions data
- Fallback to local fixtures when MCP unavailable
- Configuration flag: MCP_ATTRACTIONS_ENABLED=true

**Error Handling**:
- Timeout: 4s hard limit
- On failure: log degradation, use fixture fallback
- Health check: /healthz reports MCP status

**Provenance**:
- MCP results: source="tool.mcp.attractions"
- Fixture fallback: source="fixture_fallback"
```

### C.3 Current Tool Architecture (Fixture-Only)

#### Tool Executor
**File**: `backend/app/tools/executor.py:1-450`

```python
"""Generic async tool executor with timeouts, retries, circuit breaker, and caching."""

class ToolExecutor:
    """Executor for async tool invocations with resilience patterns."""

    async def execute(
        self,
        ctx: ToolContext,
        config: ToolExecutorConfig,
        fn: Callable[[T], Awaitable[ToolResult[R]]],
        payload: T,
        cancellation_token: CancellationToken | None = None,
    ) -> ToolResult[R]:
        """Execute tool with timeout, retry, circuit breaker, caching."""

        # Timeout enforcement (line 403)
        result = await asyncio.wait_for(fn(payload), timeout=hard_timeout_sec)

        # Retry with jitter (lines 394-445)
        for attempt in range(max_attempts):
            try:
                return await execute_with_timeout()
            except TimeoutError:
                if attempt < max_attempts - 1:
                    await asyncio.sleep(jitter)

        # Circuit breaker (lines 112-162)
        if circuit_breaker.is_open():
            raise CircuitBreakerOpenError()

        # Cache (lines 218-244)
        cache_key = sha256(payload).hexdigest()
        if cached := await cache.get(cache_key):
            return cached
```

**Features Implemented**:
- ✅ Hard timeout (4s per SPEC)
- ✅ Bounded retries (1 retry with jitter)
- ✅ Circuit breaker (5 failures/60s)
- ✅ Cache with TTL
- ✅ Cancellation support
- ✅ Metrics collection

**Missing**:
- ❌ No MCP client integration
- ❌ No adapter selection logic (MCP vs fixture)
- ❌ No fallback mechanism

#### Fixture Adapters (All Tools)
**File**: `backend/app/adapters/fixtures.py:1-281`

```python
def fetch_attractions(
    city: str,
    kid_friendly: bool | None = None,
) -> ToolResult[list[Attraction]]:
    """Fetch attractions from fixtures."""

    # Load from fixtures/attractions.json
    with open(fixture_path) as f:
        data = json.load(f)

    attractions = [
        Attraction.model_validate(item)
        for item in data.get(city.lower(), [])
    ]

    # Filter by kid_friendly if specified
    if kid_friendly is not None:
        attractions = [a for a in attractions if a.kid_friendly == kid_friendly]

    return ToolResult(
        value=attractions,
        provenance=Provenance(
            source="tool.fixtures.attractions",  # Fixed fixture source
            fetched_at=datetime.utcnow()
        )
    )
```

**All Fixture-Based Tools**:
1. `fetch_flights()` - Lines 24-65
2. `fetch_lodging()` - Lines 68-120
3. `fetch_attractions()` - Lines 123-180
4. `calculate_transit()` - Lines 183-242 (computed, not external)
5. `fetch_fx_rate()` - Lines 245-281

**Real API Tool**:
- `fetch_weather()` - `adapters/weather.py` (async HTTP to Open-Meteo)

### C.4 Configuration (No MCP Settings)

**File**: `backend/app/config.py:1-98`

```python
class Settings(BaseModel):
    """Application configuration."""

    # Database
    database_url: str = "postgresql+asyncpg://..."

    # Weather API (only external tool)
    weather_api_key: str = ""
    weather_base_url: str = "https://api.open-meteo.com/v1/forecast"
    weather_cache_ttl_seconds: int = 86400

    # Tool executor
    tool_timeout_seconds: int = 4
    tool_max_retries: int = 1

    # NO MCP SETTINGS:
    # mcp_attractions_enabled: bool = False  # MISSING
    # mcp_server_url: str = ""               # MISSING
    # mcp_timeout_ms: int = 4000             # MISSING
```

### C.5 What Would Be Needed for MCP Integration

#### Step 1: MCP Client Wrapper

```python
# Would need: backend/app/adapters/mcp_client.py

import httpx
from typing import Any

class MCPClient:
    """Client for Model Context Protocol server."""

    def __init__(self, base_url: str, timeout: int = 4):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=timeout)

    async def call_tool(
        self,
        tool_name: str,
        parameters: dict[str, Any]
    ) -> dict[str, Any]:
        """Call MCP tool endpoint."""
        response = await self.client.post(
            f"{self.base_url}/tools/{tool_name}",
            json=parameters
        )
        response.raise_for_status()
        return response.json()

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available MCP tools."""
        response = await self.client.get(f"{self.base_url}/tools")
        return response.json()
```

#### Step 2: MCP Attractions Adapter

```python
# Would need: backend/app/adapters/mcp_attractions.py

async def fetch_attractions_mcp(
    city: str,
    kid_friendly: bool | None = None,
    mcp_client: MCPClient = None
) -> ToolResult[list[Attraction]]:
    """Fetch attractions from MCP server."""

    try:
        # Call MCP server
        result = await mcp_client.call_tool(
            tool_name="attractions",
            parameters={"city": city, "kid_friendly": kid_friendly}
        )

        # Parse response to Attraction objects
        attractions = [Attraction.model_validate(item) for item in result["data"]]

        return ToolResult(
            value=attractions,
            provenance=Provenance(
                source="tool.mcp.attractions",  # MCP source
                ref_id=result.get("request_id"),
                fetched_at=datetime.utcnow()
            )
        )

    except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
        # Log degradation
        logger.warning(f"MCP attractions failed: {e}, falling back to fixtures")
        raise  # Let caller handle fallback
```

#### Step 3: Fallback Adapter Selection

```python
# Would need: backend/app/adapters/attractions.py

async def get_attractions(
    city: str,
    kid_friendly: bool | None = None,
    mcp_enabled: bool = False,
    mcp_client: MCPClient | None = None
) -> ToolResult[list[Attraction]]:
    """Get attractions with MCP fallback to fixtures."""

    if mcp_enabled and mcp_client:
        try:
            # Try MCP first
            return await fetch_attractions_mcp(city, kid_friendly, mcp_client)
        except Exception as e:
            # Log and fall back
            logger.warning(f"MCP failed: {e}, using fixture fallback")

    # Fallback to fixtures
    return fetch_attractions(city, kid_friendly)
```

#### Step 4: Configuration Update

```python
# Would need in config.py:

class Settings(BaseModel):
    # MCP settings (NEW)
    mcp_attractions_enabled: bool = Field(
        default=False,
        description="Enable MCP for attractions tool"
    )
    mcp_server_url: str = Field(
        default="http://localhost:3000",
        description="MCP server base URL"
    )
    mcp_timeout_ms: int = Field(
        default=4000,
        description="MCP request timeout in milliseconds"
    )
```

#### Step 5: Health Check Update

```python
# Would need in backend/app/api/routes/health.py:

async def check_mcp_health() -> dict[str, Any]:
    """Check MCP server health."""

    if not settings.mcp_attractions_enabled:
        return {"status": "disabled"}

    try:
        mcp_client = MCPClient(settings.mcp_server_url)
        tools = await mcp_client.list_tools()
        return {
            "status": "healthy",
            "tools": len(tools),
            "url": settings.mcp_server_url
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }

# In /healthz endpoint:
health_status = {
    "database": await check_db(),
    "mcp": await check_mcp_health(),  # NEW
}
```

### C.6 MCP Integration Effort Estimate

| Task | Effort | Files | Notes |
|------|--------|-------|-------|
| MCP client wrapper | 2h | 1 new | httpx-based, async |
| Attractions MCP adapter | 1h | 1 new | Mirror fixture schema |
| Fallback logic | 1h | 1 new | Try MCP, fall back to fixture |
| Configuration | 30m | 1 modified | Add 3 settings |
| Health check | 30m | 1 modified | Probe MCP server |
| Tests | 3h | 2 new | Unit + integration |
| **Total** | **8h** | **7 files** | Small, well-defined scope |

### C.7 Summary: MCP Status

| Component | Status | Impact |
|-----------|--------|--------|
| **MCP Client** | ❌ Not implemented | Cannot connect to MCP server |
| **MCP Adapter** | ❌ Not implemented | Cannot call MCP tools |
| **Fallback Logic** | ❌ Not implemented | No graceful degradation |
| **Configuration** | ❌ Not implemented | No feature flag or server URL |
| **Health Check** | ❌ Not implemented | Cannot monitor MCP status |
| **Tool Executor Hook** | ⚠️ Infrastructure exists | Could integrate MCP easily |
| **Provenance Tracking** | ✅ Ready | Model supports `source="tool.mcp"` |
| **Error Handling** | ✅ Partial | Timeout/retry exist, need fallback |

**Conclusion**: MCP is **fully specified in SPEC.md but 0% implemented**. The infrastructure (tool executor, provenance) is MCP-ready, but no MCP client or adapter code exists. Implementation would be straightforward (~8h effort).

---

## D. QAPlanResponse & Structured Outputs

### D.1 Response Model Hierarchy

#### QAPlanResponse (Top-Level)
**File**: `backend/app/models/answer.py:45-63`

```python
class QAPlanResponse(BaseModel):
    """External response contract for /qa/plan endpoint.

    This is the strict, versioned API contract returned to clients.
    """

    answer_markdown: str = Field(
        ...,
        description="Human-readable prose summary of the itinerary"
    )
    itinerary: ItinerarySummary = Field(
        ...,
        description="Simplified itinerary structure"
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="Citations linking claims to provenance"
    )
    tools_used: list[ToolUsageSummary] = Field(
        default_factory=list,
        description="Summary of tool invocations"
    )
    decisions: list[str] = Field(
        default_factory=list,
        description="Human-readable rationales for key agent choices",
    )
```

**Field Requirements**:
- `answer_markdown`: Required string (LLM-generated prose)
- `itinerary`: Required ItinerarySummary object
- `citations`: Optional list (default empty)
- `tools_used`: Optional list (default empty)
- `decisions`: Optional list (default empty)

#### ItinerarySummary
**File**: `backend/app/models/answer.py:30-35`

```python
class ItinerarySummary(BaseModel):
    """Simplified itinerary for /qa/plan response."""

    days: list[ItineraryDay]
    total_cost_usd: int = Field(..., description="Total cost in USD (not cents)")
```

**Key Detail**: Cost is in **USD dollars** (not cents), computed via `sum(costs_cents) // 100`.

#### ItineraryDay
**File**: `backend/app/models/answer.py:23-28`

```python
class ItineraryDay(BaseModel):
    """Single day in the itinerary."""

    date: str = Field(..., description="ISO 8601 date string (YYYY-MM-DD)")
    items: list[ItineraryDayItem] = Field(default_factory=list)
```

**Format**: Date as ISO 8601 string (e.g., `"2025-06-10"`), not datetime object.

#### ItineraryDayItem
**File**: `backend/app/models/answer.py:13-21`

```python
class ItineraryDayItem(BaseModel):
    """Single item in a day's itinerary."""

    start: str = Field(..., description="Start time in HH:MM format (local time)")
    end: str = Field(..., description="End time in HH:MM format (local time)")
    title: str = Field(..., description="Activity name")
    location: str | None = Field(None, description="Address or venue name")
    notes: str = Field("", description="Additional context (themes, indoor/outdoor, etc)")
```

**Time Format**: String in `"HH:MM"` format (e.g., `"09:00"`, `"14:30"`), not time objects.

#### ToolUsageSummary
**File**: `backend/app/models/answer.py:37-43`

```python
class ToolUsageSummary(BaseModel):
    """Summary of tool invocations."""

    name: str = Field(..., description="Tool name")
    count: int = Field(..., description="Number of calls")
    total_ms: int = Field(..., description="Cumulative latency in milliseconds")
```

**Critical Issue**: `total_ms` is **always 0** (not tracked, see B.6).

#### Citation
**File**: `backend/app/models/itinerary.py:50-54`

```python
class Citation(BaseModel):
    """Citation linking claim to provenance."""

    claim: str
    provenance: Provenance
```

**Provenance** (see C.2 for full definition):
```python
class Provenance(BaseModel):
    source: str  # "tool.flights", "rag", "manual"
    ref_id: str | None
    source_url: str | None
    fetched_at: datetime
    cache_hit: bool | None
    response_digest: str | None
```

### D.2 Mapping Function: build_qa_plan_response_from_state()

**File**: `backend/app/models/answer.py:82-166`

```python
def build_qa_plan_response_from_state(state: "GraphState") -> QAPlanResponse:
    """Map GraphState to QAPlanResponse for /qa/plan endpoint.

    Pure, deterministic mapping with no I/O.
    """

    # Validation
    if state.answer is None:
        raise ValueError("state.answer must not be None")

    # 1. Answer & Decisions (direct copy)
    answer_markdown = state.answer.answer_markdown
    decisions = state.answer.decisions

    # 2. Citations (direct copy)
    citations = state.citations

    # 3. Build Itinerary from Choices
    choices = state.choices or []

    # Calculate total cost (USD from cents)
    total_cost_usd_cents = sum(choice.features.cost_usd_cents for choice in choices)
    total_cost_usd = total_cost_usd_cents // 100  # Floor division

    # Build days (minimal - stub implementation)
    days: list[ItineraryDay] = []
    if choices and state.intent and state.intent.date_window:
        date_str = state.intent.date_window.start.isoformat()  # ISO 8601

        items: list[ItineraryDayItem] = []
        for choice in choices:
            title = f"{choice.kind.value}: {choice.option_ref}"

            items.append(
                ItineraryDayItem(
                    start="09:00",  # Stub - fixed time
                    end="10:00",    # Stub - fixed time
                    title=title,
                    location=None,  # Not extracted
                    notes="",       # Not populated
                )
            )

        if items:
            days.append(ItineraryDay(date=date_str, items=items))

    itinerary = ItinerarySummary(days=days, total_cost_usd=total_cost_usd)

    # 4. Build tools_used from Provenance
    tool_counts: dict[str, int] = {}
    for choice in choices:
        source = choice.provenance.source
        tool_counts[source] = tool_counts.get(source, 0) + 1

    tools_used = [
        ToolUsageSummary(name=name, count=count, total_ms=0)  # total_ms not tracked
        for name, count in sorted(tool_counts.items())  # Sorted alphabetically
    ]

    return QAPlanResponse(
        answer_markdown=answer_markdown,
        itinerary=itinerary,
        citations=citations,
        tools_used=tools_used,
        decisions=decisions,
    )
```

### D.3 Detailed Mapping Breakdown

#### Step 1: Answer & Decisions (Lines 104-106)
```python
answer_markdown = state.answer.answer_markdown  # From AnswerV1
decisions = state.answer.decisions              # From AnswerV1
```

**Source**: `state.answer` populated by `synth_node()` in `synth.py:15-107`.

**Data Flow**:
```
LLM synthesis → AnswerV1 → GraphState.answer → QAPlanResponse
```

#### Step 2: Citations (Lines 108-109)
```python
citations = state.citations  # Direct copy
```

**Source**: `state.citations` populated by `extract_citations_from_choices()` in `synth_node()`.

**Extraction Logic** (`citations/extract.py:10-49`):
```python
def extract_citations_from_choices(choices: list[Choice]) -> list[Citation]:
    """Extract unique citations from choice provenance."""

    citation_map: dict[tuple[str, str], Citation] = {}

    for choice in choices:
        prov = choice.provenance
        claim = f"{choice.kind.value}: {choice.option_ref}"
        ref = prov.ref_id if prov.ref_id else f"{prov.source}#unknown"

        key = (prov.source, ref)  # Deduplication key

        if key not in citation_map:
            citation_map[key] = Citation(claim=claim, provenance=prov)

    # Sort by source, then ref for deterministic ordering
    citations = sorted(
        citation_map.values(),
        key=lambda c: (c.provenance.source, c.provenance.ref_id or ""),
    )

    return citations
```

**Deduplication Example**:
```
Input:
  choice1: attraction:louvre_001, source="tool", ref="louvre_001"
  choice2: attraction:louvre_002, source="tool", ref="louvre_001"  # Same key
  choice3: attraction:louvre_003, source="manual", ref="louvre_001"

Output (2 unique):
  Citation(claim="attraction: louvre_001", provenance.source="tool", ref="louvre_001")
  Citation(claim="attraction: louvre_003", provenance.source="manual", ref="louvre_001")
```

#### Step 3: Itinerary Building (Lines 111-143)

**Cost Calculation**:
```python
total_cost_usd_cents = sum(choice.features.cost_usd_cents for choice in choices)
total_cost_usd = total_cost_usd_cents // 100
```

**Example**:
```
choices = [
    Choice(features=ChoiceFeatures(cost_usd_cents=50000)),  # $500
    Choice(features=ChoiceFeatures(cost_usd_cents=15000)),  # $150
    Choice(features=ChoiceFeatures(cost_usd_cents=2000)),   # $20
]

total_cost_usd_cents = 67000
total_cost_usd = 670  # Floor division
```

**Day Structure (Stub)**:
```python
# Only creates ONE day (trip start date)
date_str = state.intent.date_window.start.isoformat()  # "2025-06-10"

# All items get stub times
items.append(
    ItineraryDayItem(
        start="09:00",  # Fixed - not calculated
        end="10:00",    # Fixed - not calculated
        title=f"{choice.kind.value}: {choice.option_ref}",
        location=None,  # Not extracted from choice
        notes="",       # Not populated
    )
)
```

**Production Gaps**:
- Only creates **single day** (should distribute across date range)
- All items have **stub times** ("09:00"-"10:00")
- No **duration calculation** from `choice.features.travel_seconds`
- No **location extraction** from choice data
- No **notes** (themes, indoor/outdoor, kid-friendly)
- No **time window scheduling** algorithm

#### Step 4: Tools Used Aggregation (Lines 147-158)

**Aggregation Logic**:
```python
tool_counts: dict[str, int] = {}
for choice in choices:
    source = choice.provenance.source
    tool_counts[source] = tool_counts.get(source, 0) + 1

tools_used = [
    ToolUsageSummary(name=name, count=count, total_ms=0)
    for name, count in sorted(tool_counts.items())  # Alphabetical sort
]
```

**Example**:
```
Input:
  choices[0].provenance.source = "tool.flights"
  choices[1].provenance.source = "tool.flights"
  choices[2].provenance.source = "tool.lodging"
  choices[3].provenance.source = "manual"

Processing:
  tool_counts = {
      "tool.flights": 2,
      "tool.lodging": 1,
      "manual": 1
  }

Output (alphabetically sorted):
  [
      ToolUsageSummary(name="manual", count=1, total_ms=0),
      ToolUsageSummary(name="tool.flights", count=2, total_ms=0),
      ToolUsageSummary(name="tool.lodging", count=1, total_ms=0),
  ]
```

**Critical Gap**: `total_ms` is **hardcoded to 0** (line 156). Latency tracking not implemented.

### D.4 What's Missing vs. Production Needs

#### Day-by-Day Structuring
**Current**: Single day with all items
**Production Need**: Multi-day distribution

```python
# Current (stub):
days = [
    ItineraryDay(date="2025-06-10", items=[...all 15 choices...])
]

# Production (needed):
days = [
    ItineraryDay(date="2025-06-10", items=[flights, hotel_checkin, louvre]),
    ItineraryDay(date="2025-06-11", items=[breakfast, eiffel_tower, lunch, seine_cruise]),
    ItineraryDay(date="2025-06-12", items=[versailles_daytrip]),
    ItineraryDay(date="2025-06-13", items=[montmartre, sacre_coeur, hotel_checkout, flight]),
]
```

#### Item-to-Citation Linking
**Current**: Citations exist separately, no link to items
**Production Need**: Each item references its citation

```python
# Current:
ItineraryDayItem(
    title="attraction: louvre",
    notes="",  # No citation reference
)

# Production (needed):
ItineraryDayItem(
    title="The Louvre Museum",
    notes="See citation [1] for details. Art museum with 35,000 works.",
    citation_ids=["citation_uuid_1"],  # Link to Citation object
)
```

#### Budget Breakdowns
**Current**: Only total_cost_usd
**Production Need**: Category-wise breakdown

```python
# Current:
ItinerarySummary(
    days=[...],
    total_cost_usd=670
)

# Production (needed):
ItinerarySummary(
    days=[...],
    total_cost_usd=670,
    cost_breakdown={
        "flights": 500,
        "lodging": 150,
        "attractions": 20,
        "meals": 0,
        "transit": 0
    },
    budget_utilization=0.67  # 670 / 1000 budget
)
```

#### Time Scheduling
**Current**: Stub "09:00"-"10:00" for all
**Production Need**: Real time windows with travel time

```python
# Current:
items = [
    ItineraryDayItem(start="09:00", end="10:00", title="louvre"),
    ItineraryDayItem(start="09:00", end="10:00", title="eiffel"),
]

# Production (needed):
items = [
    ItineraryDayItem(
        start="09:00",  # Museum opens
        end="12:00",    # 3-hour visit
        title="Louvre Museum",
        travel_from_hotel_mins=15
    ),
    ItineraryDayItem(
        start="12:30",  # Travel + buffer
        end="13:30",    # Lunch
        title="Café Marly"
    ),
    ItineraryDayItem(
        start="14:00",  # Travel
        end="17:00",    # Tower visit
        title="Eiffel Tower"
    ),
]
```

### D.5 Test Coverage

#### Model Tests
**File**: `tests/unit/test_answer_models.py` (assumed to exist)

- ItineraryDayItem validation
- ItineraryDay creation
- ItinerarySummary with days
- QAPlanResponse full schema
- JSON serialization

#### Mapping Tests
**File**: `tests/unit/test_answer_mapping.py:1-399`

```python
def test_build_qa_plan_response_maps_answer_and_decisions():
    """Test answer_markdown and decisions mapping."""
    # Tests direct copy from state.answer

def test_build_qa_plan_response_maps_citations():
    """Test citations pass-through."""
    # Tests direct copy from state.citations

def test_build_qa_plan_response_calculates_total_cost():
    """Test cost summation and conversion."""
    # 50000 + 15000 + 2000 = 67000 cents = 670 USD

def test_build_qa_plan_response_populates_tools_used():
    """Test tool aggregation and sorting."""
    # Groups by provenance.source, sorts alphabetically

def test_build_qa_plan_response_handles_zero_costs():
    """Test zero-cost items."""
    # 0 + 1500 = 1500 cents = 15 USD

def test_build_qa_plan_response_handles_empty_choices():
    """Test empty choices list."""
    # total_cost_usd = 0, days = []

def test_build_qa_plan_response_raises_on_missing_answer():
    """Test ValueError if state.answer is None."""
    # Enforces contract: answer must exist
```

**Coverage**: High (16 tests), but only tests current stub implementation, not production scheduling.

### D.6 Summary: Structured Output Maturity

| Feature | Status | Completeness | Notes |
|---------|--------|--------------|-------|
| **QAPlanResponse Schema** | ✅ Complete | 100% | Well-defined Pydantic models |
| **Answer Markdown** | ✅ Working | 90% | LLM-generated, max 10K chars |
| **Decisions** | ✅ Working | 70% | Extracted from selector logs |
| **Citations** | ✅ Working | 80% | Deduplicated by (source, ref_id) |
| **Total Cost** | ✅ Working | 100% | Correct sum and conversion |
| **Tools Used (count)** | ✅ Working | 100% | Grouped and sorted |
| **Tools Used (latency)** | ❌ Stub | 0% | Always 0, not tracked |
| **Itinerary Days** | ⚠️ Stub | 20% | Single day only, fixed times |
| **Item Scheduling** | ❌ Stub | 0% | No time calculation |
| **Item Locations** | ❌ Missing | 0% | Always None |
| **Item Notes** | ❌ Missing | 0% | Always empty |
| **Cost Breakdown** | ❌ Missing | 0% | No category split |
| **Citation Linking** | ❌ Missing | 0% | Items don't reference citations |

**Overall**: **70% production-ready**. Core response schema and cost calculation work perfectly. Citations and tools_used are functional. Major gap is day-by-day scheduling and time allocation (stub-only).

---

## E. Conversation, What-If, and RAG

### E.1 HTTP Endpoints Summary

#### POST /qa/plan (Synchronous Planning)
**File**: `backend/app/api/routes/qa.py:22-76`

**Request**:
```python
Body: IntentV1
{
    "city": "Paris",
    "date_window": {
        "start": "2025-06-10",
        "end": "2025-06-14",
        "tz": "Europe/Paris"
    },
    "budget_usd_cents": 250000,
    "airports": ["CDG"],
    "prefs": {
        "kid_friendly": false,
        "themes": ["art", "food"],
        "avoid_overnight": false,
        "locked_slots": []
    }
}
```

**Response**:
```python
Status: 200 OK
Body: QAPlanResponse
{
    "answer_markdown": "# Your Paris Adventure...",
    "itinerary": {
        "days": [...],
        "total_cost_usd": 670
    },
    "citations": [...],
    "tools_used": [...],
    "decisions": [...]
}
```

**Flow**:
1. Validate IntentV1 (Pydantic)
2. Create ephemeral GraphState
3. Execute `run_graph_stub()` synchronously
4. Transform state → QAPlanResponse
5. Return immediately (no persistence)

**Graph Nodes Invoked**: All 8 nodes (intent → planner → selector → tool_exec → verifier → repair → synth → responder)

#### POST /runs (Create Agent Run)
**File**: `backend/app/api/routes/runs.py:45-96`

**Request**:
```python
Body: CreateRunRequest
{
    "prompt": "Plan 4-day Paris trip, $2500 budget, love art and food",
    "max_days": 4,
    "budget_usd_cents": 250000
}
```

**Response**:
```python
Status: 202 ACCEPTED
Body: CreateRunResponse
{
    "run_id": "abc-123-xyz",
    "status": "accepted"
}
```

**Flow**:
1. Create AgentRun record (status="pending", intent={"prompt": ...})
2. Create initial RunEvent (sequence 0, node="intent", phase="started")
3. Schedule background task: `asyncio.create_task(_run_graph_background())`
4. Return 202 immediately

**Database Impact**:
```sql
INSERT INTO agent_run (
    run_id, org_id, user_id,
    parent_run_id=NULL,  -- Root run
    scenario_label=NULL,  -- Not a what-if
    intent='{"prompt": "..."}',
    status='pending'
);
```

**Graph Execution**: Same 8 nodes, but async with RunEvent logging to DB

#### GET /runs/{run_id}/events/stream (SSE Streaming)
**File**: `backend/app/api/routes/runs.py:155-245`

**Request**:
```
GET /runs/{run_id}/events/stream?last_ts=2025-06-10T12:00:00Z
Headers: Authorization: Bearer {token}
```

**Response**:
```
Content-Type: text/event-stream

event: run_event
data: {"run_id":"abc","sequence":1,"node":"intent","phase":"completed","summary":"Intent parsed"}

event: run_event
data: {"run_id":"abc","sequence":2,"node":"planner","phase":"started","summary":"Fetching options"}

event: heartbeat
data: {"ts":"2025-06-10T12:01:00Z"}

event: done
data: {"status":"succeeded"}
```

**Flow**:
1. Validate run exists and org_id match (tenancy)
2. Parse `last_ts` for resume capability
3. Poll `run_event` table every 0.5s since last_ts
4. Emit SSE events for new events
5. Check `agent_run.status` for terminal state
6. Break on terminal status with `done` event

#### POST /runs/{run_id}/what_if (What-If Replanning)
**File**: `backend/app/api/routes/runs.py:248-348`

**Request**:
```python
POST /runs/550e8400-e29b-41d4-a716-446655440000/what_if
Body: WhatIfPatch
{
    "new_budget_usd_cents": 350000,
    "add_themes": ["nightlife"],
    "shift_days": 7,
    "notes": "Extended trip with nightlife"
}
```

**Response**:
```python
Status: 202 ACCEPTED
Body: CreateRunResponse
{
    "run_id": "def-456-uvw",  # NEW run_id
    "status": "accepted"
}
```

**Flow**:
1. Fetch base run from DB (enforce org_id match)
2. Deserialize `base_run.intent` → IntentV1
3. Call `derive_intent_from_what_if(base_intent, patch)` → derived_intent
4. Create child AgentRun (parent_run_id=base_run_id, scenario_label from patch.notes)
5. Store derived_intent in child run
6. Schedule background task (same as POST /runs)
7. Return 202 with new run_id

**Database Impact**:
```sql
INSERT INTO agent_run (
    run_id='def-456-uvw',
    org_id, user_id,
    parent_run_id='550e8400-...',  -- Link to parent
    scenario_label='Extended trip with nightlife',
    intent={...derived_intent...},
    status='pending'
);
```

### E.2 WhatIfPatch & derive_intent_from_what_if()

#### WhatIfPatch Model
**File**: `backend/app/models/what_if.py:6-37`

```python
class WhatIfPatch(BaseModel):
    """Structured patch for what-if transformations."""

    # Budget (new_budget wins if both set)
    new_budget_usd_cents: int | None = Field(default=None, gt=0)
    budget_delta_usd_cents: int | None = Field(default=None)

    # Themes (remove first, then add)
    add_themes: list[str] | None = Field(default=None)
    remove_themes: list[str] | None = Field(default=None)

    # Date shift (equal shift for start and end)
    shift_days: int | None = Field(default=None)

    # Scenario metadata
    notes: str | None = Field(default=None, max_length=500)
```

**All fields optional** - empty patch produces identical intent (different object).

#### Derivation Function
**File**: `backend/app/orchestration/what_if.py:9-76`

```python
def derive_intent_from_what_if(base: IntentV1, patch: WhatIfPatch) -> IntentV1:
    """Pure function: derive new intent from base + patch.

    Rules:
    - Budget: new_budget > delta > keep base
    - Themes: remove first, then add (skip duplicates)
    - Dates: shift both start and end equally
    - City, airports: unchanged
    - No mutations of base
    """

    # 1. Budget (line 38-43)
    if patch.new_budget_usd_cents is not None:
        new_budget = patch.new_budget_usd_cents
    elif patch.budget_delta_usd_cents is not None:
        new_budget = max(1, base.budget_usd_cents + patch.budget_delta_usd_cents)
    else:
        new_budget = base.budget_usd_cents

    # 2. Themes (line 45-57)
    base_themes = base.prefs.themes if base.prefs and base.prefs.themes else []
    new_themes = list(base_themes)  # Copy for immutability

    if patch.remove_themes:
        new_themes = [t for t in new_themes if t not in patch.remove_themes]

    if patch.add_themes:
        for theme in patch.add_themes:
            if theme not in new_themes:
                new_themes.append(theme)

    # 3. Dates (line 59-64)
    new_date_window = base.date_window.model_copy(deep=True)
    if patch.shift_days is not None:
        delta = timedelta(days=patch.shift_days)
        new_date_window.start = new_date_window.start + delta
        new_date_window.end = new_date_window.end + delta

    # 4. Build new intent (line 70-76)
    new_prefs = Preferences(themes=new_themes)
    return IntentV1(
        city=base.city,  # Unchanged
        date_window=new_date_window,
        budget_usd_cents=new_budget,
        airports=base.airports,  # Unchanged
        prefs=new_prefs,
    )
```

**Test Verification** (`tests/unit/test_what_if_derivation.py`):
- 16 comprehensive tests
- Budget precedence (new > delta > base)
- Budget clamping (min 1 USD cent)
- Theme ordering preservation
- Date shift correctness
- Purity (no mutations)
- Determinism (same input → same output)

### E.3 Parent/Child Run Relationship

#### Database Schema
**File**: `backend/app/db/models.py:188-237`

```python
class AgentRun(Base):
    """Agent run table with what-if threading."""

    __tablename__ = "agent_run"
    __table_args__ = (
        Index("idx_run_org_user", "org_id", "user_id", "created_at"),
        Index("idx_run_parent", "parent_run_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("org.org_id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("user.user_id"))

    # What-if threading (PR-9A)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_run.run_id"), nullable=True
    )
    scenario_label: Mapped[str | None] = mapped_column(Text, nullable=True)

    intent: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), ...)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), ...)

    # Self-referential relationship
    parent: Mapped["AgentRun | None"] = relationship(
        "AgentRun", remote_side=[run_id], backref="children"
    )
```

**Relationship Pattern**:
```
Original Run (root):
  run_id: A
  parent_run_id: NULL
  scenario_label: NULL

What-If Child 1:
  run_id: B
  parent_run_id: A  ← Points to parent
  scenario_label: "Increased budget"

What-If Child 2:
  run_id: C
  parent_run_id: A  ← Same parent
  scenario_label: "Extended dates"

Query all variants:
  SELECT * FROM agent_run WHERE parent_run_id = A
  OR run_id = A
```

#### Scenario Label Truncation
**File**: `backend/app/api/routes/runs.py:303-305`

```python
scenario_label = patch.notes or "what-if"
if len(scenario_label) > 100:
    scenario_label = scenario_label[:97] + "..."
```

**Max Length**: 100 chars (97 + "...")

### E.4 How What-If Runs Relate to Original

#### State Isolation (Key Point)

**Each run has independent execution**:
```
Original Run A:
  ├─ intent: { city: "Paris", budget: 100000 }
  ├─ GraphState created
  ├─ Full graph execution (8 nodes)
  ├─ Results: answer, choices, citations
  └─ Stored in agent_run, itinerary tables

What-If Run B (child of A):
  ├─ intent: { city: "Paris", budget: 150000 } ← Derived
  ├─ NEW GraphState created
  ├─ Full graph execution (8 nodes, independent)
  ├─ Results: separate answer, choices, citations
  └─ Stored separately (parent_run_id links to A)
```

**No Shared State**:
- Each run executes full orchestration graph
- Plan, choices, violations generated independently
- LLM synthesis happens separately
- Citations extracted separately
- No caching or reuse between parent and child

#### What-If Use Cases

**Use Case 1: Budget Exploration**
```
Base: $1000 budget
What-If 1: $1500 budget (new_budget_usd_cents=150000)
What-If 2: $2000 budget (new_budget_usd_cents=200000)

User compares:
- Which attractions are added at higher budgets?
- Does lodging quality improve?
- Are there diminishing returns?
```

**Use Case 2: Date Flexibility**
```
Base: June 10-14
What-If 1: June 17-21 (shift_days=7)
What-If 2: June 24-28 (shift_days=14)

User compares:
- Weather differences
- Price changes (peak season?)
- Attraction availability
```

**Use Case 3: Theme Exploration**
```
Base: themes=["art", "food"]
What-If 1: add_themes=["nightlife"], remove_themes=[]
What-If 2: add_themes=["history"], remove_themes=["food"]

User compares:
- Different attraction recommendations
- Activity timing (nightlife later hours)
- Overall itinerary feel
```

### E.5 User Input Entry Points

#### Entry Point 1: Prompt (POST /runs)
**File**: `backend/app/api/routes/runs.py:30-36`

```python
class CreateRunRequest(BaseModel):
    """Request body for POST /runs."""

    prompt: str = Field(..., min_length=1)
    max_days: int | None = Field(None, ge=4, le=7)
    budget_usd_cents: int | None = Field(None, gt=0)
```

**Current Flow**:
```python
# Line 69: Store prompt in intent
agent_run = AgentRunDB(
    intent={"prompt": request.prompt},  # Minimal stub
    ...
)

# Later: extract_intent_stub() IGNORES prompt
# Line 66-106 in graph.py: Uses hardcoded ParisIntentV1
```

**Critical Bug**: `extract_intent_stub()` ignores the prompt. Needs LLM-based intent parsing.

#### Entry Point 2: Structured Intent (POST /qa/plan)
**File**: `backend/app/api/routes/qa.py:23-27`

```python
@router.post("", response_model=QAPlanResponse, status_code=status.HTTP_200_OK)
async def plan(
    request: IntentV1,  # Full structured intent
    ...
)
```

**Flow**: Direct use of structured IntentV1, no parsing needed.

#### Entry Point 3: What-If Patch (POST /runs/{run_id}/what_if)
**File**: `backend/app/api/routes/runs.py:250-256`

```python
async def create_what_if_run(
    run_id: str,
    patch: WhatIfPatch,  # Structured transformations
    ...
)
```

**Flow**: Applies patch to base intent via `derive_intent_from_what_if()`.

#### No Feedback Mechanism (Gap)

**Current**: No explicit feedback loop. Once a run completes, user can only:
- Create what-if variant (fork from original)
- Create new run (start from scratch)

**Missing**:
- No `/runs/{run_id}/refine` endpoint
- No constraint adjustment after generation
- No iterative improvement based on user feedback

**Proposed** (not implemented):
```python
# Could add:
POST /runs/{run_id}/refine
{
    "feedback": "Too expensive, reduce to $1500",
    "max_iterations": 3
}

# Or:
POST /runs/{run_id}/adjust_prefs
{
    "add_constraints": ["kid_friendly"],
    "preferred_themes": ["beach", "family"]
}
```

### E.6 RAG Integration Points in Conversation Flow

#### Point 1: Intent Parsing (Natural Language → Structured)
```
User: "Plan a 4-day Paris trip, $2500, love art and food"
    ↓
❌ Currently: extract_intent_stub() ignores prompt
    ↓
✅ With RAG: Query knowledge base for city/themes
    - "Paris trip" → dest_id for Paris
    - "art and food" → theme suggestions from knowledge
    - LLM + RAG → IntentV1
```

#### Point 2: Planning (Context for Choices)
```
planner.plan_real()
    ↓
❌ Currently: Only fixture/external tools
    ↓
✅ With RAG: retrieve_knowledge("Paris art museums")
    - Top-k knowledge chunks
    - Merge with fixture attractions
    - Boost scores for knowledge-matched choices
```

#### Point 3: Synthesis (Grounding LLM Output)
```
synth_node()
    ↓
❌ Currently: LLM synthesis from choices only
    ↓
✅ With RAG: retrieve_knowledge("Paris travel guide")
    - Add context to LLM prompt: [K1], [K2], [K3]
    - LLM generates markdown with citations
    - Extract citations linking to knowledge_items
```

#### Point 4: What-If Replanning (Contextual Refinement)
```
POST /runs/{run_id}/what_if
    ↓
❌ Currently: Pure intent transformation
    ↓
✅ With RAG: retrieve_knowledge for new intent
    - Base: themes=["art"], derive: add_themes=["nightlife"]
    - RAG query: "Paris nightlife recommendations"
    - New plan uses both base knowledge + nightlife RAG
```

### E.7 Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     USER CONVERSATION                        │
└───────────┬─────────────────────────────────────────────────┘
            │
            ├─── POST /runs (prompt) ──────────────┐
            │                                       │
            ├─── POST /qa/plan (IntentV1) ────────┐│
            │                                      ││
            └─── POST /runs/{id}/what_if ────────┐││
                                                  │││
                                                  │││
┌─────────────────────────────────────────────────┼┼┼─────────┐
│                   ORCHESTRATION                 │││         │
│                                                 │││         │
│  ┌───────────────────────────────────────────┐ │││         │
│  │  GraphState (run-specific)                │ │││         │
│  │  - intent, choices, violations, answer    │ │││         │
│  └───────────────────────────────────────────┘ │││         │
│                       │                         │││         │
│                       ▼                         │││         │
│  ┌───────────────────────────────────────────┐ │││         │
│  │  8-Node Pipeline                          │ │││         │
│  │  1. intent ─────────────────┐             │ │││         │
│  │  2. planner ← (RAG here)    │ ◄───────────┼─┘│         │
│  │  3. selector                │             │  │         │
│  │  4. tool_exec               │             │  │         │
│  │  5. verifier                │             │  │         │
│  │  6. repair (conditional)    │             │  │         │
│  │  7. synth ← (RAG here)      │ ◄───────────┼──┘         │
│  │  8. responder               │             │            │
│  └──────────┬──────────────────┘             │            │
│             │                                 │            │
└─────────────┼─────────────────────────────────┼────────────┘
              │                                 │
              ▼                                 │
┌─────────────────────────────────────────────────────────────┐
│                      PERSISTENCE                             │
│                                                              │
│  AgentRun Table                                              │
│  ├─ run_id (PK)                                              │
│  ├─ parent_run_id (FK, self-ref) ◄───────────────────────────┘
│  ├─ scenario_label
│  ├─ intent (JSONB)
│  └─ status
│
│  RunEvent Table (SSE streaming)
│  ├─ run_id (FK)
│  ├─ sequence, node, phase
│  └─ timestamp
│
│  KnowledgeItem + Embedding (RAG)
│  ├─ item_id, org_id, dest_id
│  ├─ content (text)
│  └─ vector (pgvector) ← NOT IMPLEMENTED
└─────────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│                       RESPONSE                               │
│                                                              │
│  QAPlanResponse                                              │
│  ├─ answer_markdown (LLM-generated)                          │
│  ├─ itinerary (days, items, cost)                            │
│  ├─ citations (provenance links) ← Could link to RAG        │
│  ├─ tools_used (counts, latencies)                           │
│  └─ decisions (selector rationales)                          │
└─────────────────────────────────────────────────────────────┘
```

### E.8 Critical Bug: Derived Intent Ignored

**File**: `backend/app/orchestration/graph.py:66-106`

```python
async def extract_intent_stub(state: GraphState, session: AsyncSession) -> GraphState:
    """Stub intent extraction - returns hardcoded Paris intent."""

    # BUG: Ignores state.intent if already set
    state.intent = IntentV1(
        city="paris",  # Hardcoded
        date_window=DateWindow(
            start=date(2025, 6, 10),
            end=date(2025, 6, 14),
            tz="Europe/Paris"
        ),
        budget_usd_cents=250_000,  # Hardcoded
        airports=["CDG"],
        prefs=Preferences(
            themes=["art", "food"],
            kid_friendly=False
        )
    )

    return state
```

**Impact on What-If**:
```
User creates what-if with new_budget_usd_cents=350000
    ↓
derive_intent_from_what_if() produces derived_intent with budget=350000
    ↓
Child run created with intent={...derived_intent...} in DB
    ↓
_run_graph_background() starts
    ↓
extract_intent_stub() OVERWRITES with hardcoded budget=250000
    ↓
BUG: What-if runs ALL use same hardcoded intent!
```

**Fix Required**:
```python
async def extract_intent_stub(state: GraphState, session: AsyncSession) -> GraphState:
    """Extract intent from state or default."""

    # FIX: Use existing intent if present
    if state.intent is None:
        # Only set default if not already provided
        state.intent = IntentV1(...)

    return state
```

---

## F. Blindspots & Concrete Recommendations

### F.1 Current State Summary

#### What Actually Works (Production-Ready)
1. **Database Schema** (80%): Tables exist for knowledge_item, embedding, agent_run with threading
2. **Tool Executor** (90%): Timeout, retry, circuit breaker, caching all functional
3. **Fixture Adapters** (100%): All 5 tools work reliably with provenance
4. **Structured Outputs** (70%): QAPlanResponse schema complete, cost calculation correct
5. **What-If Threading** (100%): Parent/child run relationships fully implemented
6. **Intent Derivation** (100%): Pure function, well-tested, deterministic
7. **SSE Streaming** (100%): Real-time event streaming works
8. **Multi-Tenancy** (100%): Org-scoped isolation enforced everywhere

#### What Doesn't Work (Critical Gaps)
1. **RAG Runtime** (0%): No ingestion, no retrieval, no integration
2. **MCP Integration** (0%): No client, no adapters, no fallback logic
3. **Day Scheduling** (0%): Stub times only, no real scheduling algorithm
4. **Intent Parsing** (0%): Stub node ignores prompts, uses hardcoded values
5. **Latency Tracking** (0%): tools_used.total_ms always 0
6. **Citation Linking** (0%): Items don't reference citations
7. **Cost Breakdown** (0%): No category-wise split

### F.2 Blindspots (Hidden Issues)

#### Blindspot 1: Derived Intent Ignored (Critical Bug)
**Location**: `backend/app/orchestration/graph.py:66-106`

**Impact**: What-if runs don't actually use derived intent. All runs use hardcoded Paris intent.

**Evidence**:
```python
# What-if creates derived intent with budget=350000
derived_intent = derive_intent_from_what_if(base_intent, patch)

# Stored correctly in DB
child_run.intent = derived_intent.model_dump()

# But graph execution overwrites it
state.intent = IntentV1(budget_usd_cents=250_000)  # Hardcoded!
```

**Fix**: Check if `state.intent` exists before setting default.

#### Blindspot 2: No pgvector Index
**Location**: `backend/alembic/versions/001_initial.py:70-84`

**Impact**: Even if embeddings are stored, vector search will be **extremely slow** (full table scan).

**Evidence**:
```python
# Comment in code (line 177 in models.py):
# "Note: vector column requires pgvector extension"
# "This is a placeholder; actual pgvector integration would use pgvector types"

# Migration creates table but NO index:
op.create_table('embedding', ...)
# MISSING: op.execute("CREATE INDEX ... USING ivfflat ...")
```

**Fix**: Add pgvector extension + ivfflat index in migration.

#### Blindspot 3: Empty Chunk Content
**Location**: `backend/app/db/models.py:162-186`

**Impact**: Even if retrieval worked, citations would have no content to display.

**Evidence**:
```python
class Embedding(Base):
    embedding_id: UUID
    item_id: UUID  # Links to knowledge_item
    vector: ARRAY(Numeric)
    # MISSING: content field (chunk text)
    # MISSING: chunk_idx field (for citation format)
```

**Current**: Citation would show `provenance.ref_id` but no actual text.
**Needed**: Store chunk text in embedding table for display.

#### Blindspot 4: No Multi-Day Logic
**Location**: `backend/app/models/answer.py:125-140`

**Impact**: All itineraries show as single day, regardless of trip length.

**Evidence**:
```python
# Uses only first date:
date_str = state.intent.date_window.start.isoformat()

# Creates single ItineraryDay:
days.append(ItineraryDay(date=date_str, items=items))
```

**Expected**: Loop over date range, distribute choices by day.

#### Blindspot 5: Fixture Path Hardcoded
**Location**: `backend/app/adapters/fixtures.py` throughout

**Impact**: Cannot use per-org fixture data, all orgs share same fixtures.

**Evidence**:
```python
# Line 30 (approximate):
fixture_path = Path(__file__).parent.parent / "fixtures" / "attractions.json"
```

**Expected**: Look up `destination.fixture_path` from DB per org.

#### Blindspot 6: No Cache for Embeddings
**Location**: Nowhere (not implemented)

**Impact**: Repeated queries to same city+themes will re-embed every time.

**Expected**: Cache query embeddings with TTL (e.g., 1 hour).

#### Blindspot 7: No Cost Attribution to Days
**Location**: `backend/app/models/answer.py:114-143`

**Impact**: Cannot show daily spend breakdown.

**Current**: Only `total_cost_usd` at itinerary level.
**Needed**: `ItineraryDay.cost_usd` field with per-day sum.

### F.3 Concrete Recommendations (Prioritized)

#### P0 (Critical - Block Production)

**P0-1: Implement Minimal RAG Retrieval in Planner Node**
- **Effort**: 16 hours
- **Files**: 3 new, 2 modified
- **Deliverable**: `retrieve_knowledge()` function that queries `knowledge_item` table with pgvector similarity search

```python
# New: backend/app/rag/retrieval.py
async def retrieve_knowledge(
    query: str,
    org_id: UUID,
    dest_id: UUID | None = None,
    top_k: int = 10
) -> list[KnowledgeChunk]: ...

# Modified: backend/app/orchestration/planner.py
async def plan_real(...):
    # Add RAG query before returning choices
    rag_chunks = await retrieve_knowledge(...)
    # Merge into state.choices
```

**Impact**: Enables org-specific knowledge grounding, differentiates from competitors.

**Dependencies**:
- Fix pgvector column type (Embedding.vector)
- Add ivfflat index
- Implement `generate_embedding()` for query

---

**P0-2: Fix What-If Derived Intent Bug**
- **Effort**: 30 minutes
- **Files**: 1 modified
- **Deliverable**: `extract_intent_stub()` checks for existing intent before overwriting

```python
# Modified: backend/app/orchestration/graph.py:66-106
async def extract_intent_stub(state: GraphState, session: AsyncSession):
    if state.intent is None:  # ADD THIS CHECK
        state.intent = IntentV1(...)  # Default only if missing
    return state
```

**Impact**: What-if scenarios actually work as designed. Currently **completely broken**.

---

**P0-3: Implement Knowledge Ingestion Pipeline**
- **Effort**: 24 hours
- **Files**: 4 new, 1 migration
- **Deliverable**: `POST /knowledge/items` endpoint + chunking + embedding generation

```python
# New: backend/app/api/routes/knowledge.py
@router.post("/items")
async def upload_knowledge(
    file: UploadFile,
    org_id: UUID,
    dest_id: UUID | None = None
): ...

# New: backend/app/rag/chunking.py
def chunk_text(text: str, max_tokens: int = 1000) -> list[str]: ...

# New: backend/app/rag/embedding.py
async def generate_embeddings_batch(chunks: list[str]) -> list[list[float]]: ...
```

**Impact**: Enables org-specific content upload. Without this, RAG retrieval has no data to retrieve.

---

#### P1 (High Value - Competitive Advantage)

**P1-1: Implement Multi-Day Scheduling Algorithm**
- **Effort**: 20 hours
- **Files**: 2 modified, 1 new
- **Deliverable**: Real day-by-day itinerary with time windows

```python
# New: backend/app/scheduling/algorithm.py
def distribute_choices_across_days(
    choices: list[Choice],
    date_window: DateWindow
) -> dict[date, list[Choice]]: ...

def schedule_items_with_travel(
    choices: list[Choice],
    date: date
) -> list[ItineraryDayItem]: ...
```

**Impact**: Production-quality itineraries. Current stub is demo-only.

---

**P1-2: Add MCP Integration with Fixture Fallback**
- **Effort**: 8 hours
- **Files**: 3 new, 2 modified
- **Deliverable**: MCP client + attractions adapter + fallback logic

```python
# New: backend/app/adapters/mcp_client.py
class MCPClient: ...

# New: backend/app/adapters/mcp_attractions.py
async def fetch_attractions_mcp(...): ...

# Modified: backend/app/adapters/attractions.py (new file)
async def get_attractions(...):
    if mcp_enabled:
        try: return await fetch_attractions_mcp(...)
        except: pass
    return fetch_attractions(...)  # Fallback
```

**Impact**: Meets SPEC requirement, enables external tool integration.

---

**P1-3: Implement Intent Parsing from Natural Language**
- **Effort**: 12 hours
- **Files**: 2 modified
- **Deliverable**: Replace `extract_intent_stub()` with LLM-based parsing

```python
# Modified: backend/app/orchestration/graph.py
async def extract_intent_real(state: GraphState, session: AsyncSession):
    if state.intent is None and "prompt" in state.intent_raw:
        # Use LLM to parse prompt → IntentV1
        state.intent = await parse_intent_with_llm(state.intent_raw["prompt"])
    return state
```

**Impact**: POST /runs endpoint actually works with prompts.

---

#### P2 (Medium - Polish)

**P2-1: Add Latency Tracking to ToolExecutor**
- **Effort**: 4 hours
- **Files**: 2 modified
- **Deliverable**: `Provenance.execution_ms` field + aggregation in `build_qa_plan_response_from_state()`

```python
# Modified: backend/app/models/common.py
class Provenance(BaseModel):
    ...
    execution_ms: int | None = None  # NEW

# Modified: backend/app/tools/executor.py
start = time.perf_counter()
result = await fn(payload)
execution_ms = int((time.perf_counter() - start) * 1000)
result.provenance.execution_ms = execution_ms
```

**Impact**: tools_used.total_ms populated correctly, enables performance monitoring.

---

**P2-2: Link Citations to Itinerary Items**
- **Effort**: 6 hours
- **Files**: 2 modified
- **Deliverable**: `ItineraryDayItem.citation_ids` field

```python
# Modified: backend/app/models/answer.py
class ItineraryDayItem(BaseModel):
    ...
    citation_ids: list[str] = Field(default_factory=list)  # NEW

# Modified: build_qa_plan_response_from_state()
# Map choice.provenance.ref_id → citation_id
item.citation_ids = [find_citation_id(choice.provenance)]
```

**Impact**: UI can show source links directly on itinerary items.

---

**P2-3: Add Cost Breakdown by Category**
- **Effort**: 3 hours
- **Files**: 1 modified
- **Deliverable**: `ItinerarySummary.cost_breakdown` field

```python
# Modified: backend/app/models/answer.py
class ItinerarySummary(BaseModel):
    ...
    cost_breakdown: dict[str, int] = Field(default_factory=dict)  # NEW
    # {"flights": 500, "lodging": 150, "attractions": 20}
```

**Impact**: Users see where money is spent, can optimize budget allocation.

---

### F.4 Summary Table: Recommendations

| Priority | Task | Effort | Files | Impact | Blocks |
|----------|------|--------|-------|--------|--------|
| **P0-1** | RAG Retrieval | 16h | 5 | High - Core feature | Production deployment |
| **P0-2** | Fix What-If Bug | 30m | 1 | Critical - Currently broken | What-if scenarios |
| **P0-3** | Knowledge Ingestion | 24h | 5 | High - Enables RAG | RAG system |
| **P1-1** | Multi-Day Scheduling | 20h | 3 | High - Production quality | Demo → Production |
| **P1-2** | MCP Integration | 8h | 5 | Medium - SPEC requirement | External tools |
| **P1-3** | Intent Parsing | 12h | 2 | Medium - POST /runs works | Natural language input |
| **P2-1** | Latency Tracking | 4h | 2 | Low - Observability | Performance monitoring |
| **P2-2** | Citation Linking | 6h | 2 | Low - UX polish | UI enhancement |
| **P2-3** | Cost Breakdown | 3h | 1 | Low - Budget insights | Analytics |

**Total P0 Effort**: 40.5 hours (1 week)
**Total P1 Effort**: 40 hours (1 week)
**Total P2 Effort**: 13 hours (2 days)

---

### F.5 Technical Debt Items

1. **pgvector Column Type**: Change `ARRAY(Numeric)` → `Vector(1536)` in migration
2. **Embedding Content**: Add `content` and `chunk_idx` fields to Embedding table
3. **Fixture Path**: Use `destination.fixture_path` from DB instead of hardcoded paths
4. **Query Embedding Cache**: Implement TTL cache for repeated query embeddings
5. **Day Cost Attribution**: Add `ItineraryDay.cost_usd` field
6. **Health Check for MCP**: Add MCP status to `/healthz` endpoint
7. **Intent Validation**: Add validation for budget vs. date_window duration (too low budget for trip length)
8. **Tool Error Logging**: Add structured logging for tool failures (currently only circuit breaker metrics)

---

## Conclusion

**Current Maturity**:
- **Infrastructure**: 85% (DB, auth, tenancy, orchestration all solid)
- **RAG**: 20% (schema exists, runtime missing)
- **MCP**: 0% (nothing implemented)
- **Structured Outputs**: 70% (core works, scheduling stub)
- **What-If**: 95% (fully implemented, one critical bug)

**Immediate Action Items**:
1. Fix what-if derived intent bug (30 min) → unblock feature testing
2. Implement RAG retrieval (16h) → core differentiator
3. Add knowledge ingestion (24h) → enable RAG data pipeline
4. Implement multi-day scheduling (20h) → production-ready itineraries

**Post-MVP**:
- MCP integration (8h) → SPEC compliance
- Intent parsing (12h) → natural language support
- Latency tracking (4h) → observability
- Citation linking (6h) → UX polish

**Assessment**: The codebase is **well-architected but incomplete**. Foundation is production-grade (multi-tenancy, tool executor, what-if threading). RAG and MCP are specified but not implemented. Structured outputs work but need scheduling polish. With ~80 hours of focused work (2 weeks), this system could go from "impressive demo" to "production-ready SaaS".

---

**End of Audit**
