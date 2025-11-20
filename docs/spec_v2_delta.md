# keyveve travel planner – spec v2 (delta over v1)

## 0. purpose

this document *overrides and amends* the earlier `porNyanUpdatedSPEC`.  
source of truth is:

1. the original keyveve take-home project brief (pdf), and  
2. this v2 delta spec.

v1 spec is **legacy**: keep for historical context, but if v1 and v2 conflict, **v2 wins**.

goal: define the **minimal, high-leverage behavior** needed to demo a serious, non-toy “trip planning agent” that satisfies the take-home and shows strong agentic + RAG behavior.

---

## 1. scope: what “done” looks like

### 1.1 core hero flow

a complete hero run must support:

1. user enters **natural language** request, not JSON.
2. user can optionally **attach 1–2 documents** (e.g. PDF with hotel ideas, a markdown with personal constraints).
3. system:
   - extracts a structured `IntentV1` from the NL request,  
   - calls tools (incl. at least one MCP-shaped tool),  
   - uses **RAG over uploaded docs** to influence decisions,  
   - produces a **multi-day, time-slotted itinerary** with costs and citations,  
   - exposes the result via `/qa/plan` and the UI.
4. user can issue a **what-if** (e.g. “make it cheaper”, “no museums”, “more kid-friendly”) tied to a previous run id.
5. system creates a **new run threaded off the original**, with an updated intent and a new plan, and you can inspect both.

this is the “hero” we optimize for. everything else (nice dashboards, fancy UI chrome) is secondary.

---

## 2. things from v1 that still stand

the following design elements from v1 are **kept** and should be treated as stable unless this doc says otherwise:

- **graph + state architecture**
  - `GraphState` as the central context object.
  - nodes: intent, planner, selector, verifiers, synth, responder.
- **planner / selector / verifier layering**
  - tools → normalized `Choice` + `ChoiceFeatures`,
  - selector scores choices using only `ChoiceFeatures`,
  - verifiers produce typed `Violation`s (budget, prefs, feasibility, weather).
- **what-if threading**
  - `AgentRun.parent_run_id` + `scenario_label`,
  - `WhatIfPatch` + `derive_intent_from_what_if`.
- **synth + answer models**
  - `AnswerV1`, `QAPlanResponse`, `synthesis_source`,
  - citations from provenance,
  - LLM client seam with deterministic stub.
- **tool adapters**
  - weather, flights, lodging, attractions, transit, fx fixtures.

assume all of that is “already there” and only needs local tweaks to integrate the new requirements below.

---

## 3. gaps vs take-home (must add)

these are **hard gaps** in the current system that v2 must close.

### 3.1 natural-language → intent extractor

**problem:** today, `/qa/plan` and `/runs` assume the caller sends a ready-made `IntentV1`. a real user (and the take-home) expects to type a sentence.

**requirement:**

- add an **`intent_extractor` node** that:
  - input: raw user text (`str`) + optional previous intent (for what-ifs).
  - output: `IntentV1` (city, dates, budget, prefs, airports, etc.).
- implementation:
  - use LLM with **strict JSON schema** (pydantic / json schema),
  - reject or repair malformed outputs deterministically,
  - **never** free-form parse in the orchestrator; all textual interpretation happens inside this node.
- graph integration:
  - UI / `/qa/plan` should accept a body like:
    - `{"query": "...", "files": [...file ids...]}`  
    - internally: `query -> intent_extractor -> intent` then rest of graph.

### 3.2 real RAG over user docs

**problem:** current “citations” are only from tools, not from user files. there is no ingestion, no embeddings, no retrieval.

**requirements:**

1. **ingestion path**
   - minimal, but real:
     - accept file upload(s) via HTTP (pdf/md/txt),
     - chunk into passages,
     - embed passages,
     - store `(doc_id, chunk_id, text, embedding, metadata)` in DB (pgvector or equivalent).
   - metadata to store at minimum:
     - `doc_id`, `file_name`,
     - `city` / `country` tags if detectable,
     - `user_id` / `org_id`.

2. **retrieval node**
   - add a `rag_retriever` node to the graph:
     - input: `IntentV1` (city, dates, themes) + maybe a short query,
     - output: list of **RAGChunk** objects:
       - `id`, `text`, `source_doc`, `score`, `provenance`.
   - behavior:
     - performs vector search constrained by org/user and (if possible) city/theme filters,
     - returns top-k (e.g. 5–10) chunks.

3. **prompt wiring**
   - the synth node must:
     - include a **separate section** in the LLM context for RAG chunks, e.g.:

       ```text
       ## User Documents (RAG)
       [1] Title: ...
       Snippet: ...
       Source: file_name (doc_id)
       ...
       ```
     - instruct the LLM:
       - to **prefer** facts from this section when relevant,
       - to reference them via `[1]`, `[2]` etc. when used.

4. **citations from RAG**
   - extend citation extraction to also produce citations from **RAGChunk** provenance, not just tools:
     - `claim`: some stable reference (`"rag_chunk: <chunk_id>"`),
     - `provenance.source`: e.g. `"rag.user_docs"`,
     - `provenance.ref_id`: e.g. `"<doc_id>#<chunk_id>"`.

5. **constraints:**
   - no complex multi-vector indexes; a single embeddings table is enough.
   - deterministic, testable with a “tiny” corpus.

### 3.3 MCP-shaped tool abstraction

**problem:** tools are currently “in-process adapters” only. nothing shows that this architecture can host external MCP tools.

**requirements:**

- define a **tool adapter interface** (even if not literally using the MCP runtime), e.g.:

  ```python
  class ToolInvocation(BaseModel):
      name: str
      args: dict[str, JsonValue]

  class ToolResultEnvelope(BaseModel):
      name: str
      duration_ms: int
      raw_result: JsonValue
      provenance: Provenance

  class ToolExecutor(Protocol):
      async def invoke(self, call: ToolInvocation) -> ToolResultEnvelope: ...

	•	implement one concrete adapter that is “MCP-flavored”:
	•	e.g. a “generic HTTP MCP tool” that:
	•	reads a tool manifest (name, url, input schema),
	•	does an HTTP call,
	•	returns a typed ToolResultEnvelope,
	•	gets wrapped into your existing domain models (FlightOption, etc.) by a mapper.
	•	integrate it into the planner for a single domain (e.g. lodging), so you can honestly say:
	•	“this system can call both internal and MCP-like tools via the same interface”.

3.4 real multi-day itinerary mapping

problem: the current ItinerarySummary mapping is effectively a stub: it often dumps all items into a single day and ignores time windows and locations.

requirements:
	•	implement a pure mapper:

def build_itinerary_from_choices(
    intent: IntentV1,
    choices: list[Choice],
) -> ItinerarySummary


	•	behavior:
	•	allocate days from intent.date_window.start to .end inclusive,
	•	for each Choice:
	•	infer which day(s) it belongs to:
	•	flights: departure day / arrival day,
	•	lodging: all nights between check-in and check-out,
	•	attractions: any day that fits, preferring non-travel days.
	•	assign approximate times if not provided (e.g. flights morning/afternoon, attractions morning/afternoon).
	•	compute:
	•	itinerary.days[*].items[*]: title, notes, time window, location if we have it,
	•	itinerary.total_cost_usd: sum from Choice.features.cost_usd_cents.
	•	constraints:
	•	deterministic, no randomness.
	•	tolerant of missing time/location (fall back to reasonable defaults).

⸻

4. what-if behavior (sanity requirements)

v1 already has what-if threading and WhatIfPatch. v2 adds explicit correctness constraints:
	•	applying a patch must change the derived IntentV1 in a visible way for:
	•	budget (absolute or delta),
	•	themes (add / remove),
	•	dates (shift).
	•	the new run:
	•	must reference parent_run_id,
	•	must store the applied patch / scenario label,
	•	must re-run the full graph using the derived intent.

we consider the what-if layer “good enough” if:
	•	you can:
	•	create a base trip,
	•	apply a “cheaper” patch,
	•	see a new run with:
	•	different choices (e.g. cheaper lodging/flight),
	•	changed budget fields,
	•	preserved original threading.

⸻

5. LLM synthesis: non-negotiable constraints

building on v1 + 8A-b, v2 requires:
	•	no hallucinated options:
	•	system prompt must say: only mention items present in Selected Options or User Documents.
	•	budget respect:
	•	if verifiers flag over-budget, the LLM must:
	•	acknowledge it,
	•	not pretend the trip is within budget.
	•	traceable grounding:
	•	answer must be compatible with:
	•	Choice contents (kinds, costs, themes),
	•	RAG chunks (no contradictory facts).
	•	synthesis_source is respected:
	•	if synthesis_source="stub", UI / logs must surface that somewhere (even if subtle) so we never demo stub output as real LLM.

no extra fancy formatting is required beyond this.

⸻

6. explicit “out of scope” for v2

to avoid scope-creep, the following are explicitly out of scope for this take-home:
	•	multi-user real auth, permissions, teams.
	•	rich analytics dashboards or telemetry UI.
	•	advanced RAG features (re-ranking, multi-hop reasoning, hybrid dense/sparse).
	•	supporting more than 2–3 document types beyond what’s needed to demo.
	•	multiple different MCP tools beyond the single example.

if an idea doesn’t directly improve:
	•	NL intent extraction,
	•	RAG grounding,
	•	tool orchestration,
	•	or the final itinerary quality,

it’s probably out of scope.

⸻

7. acceptance tests (conceptual)

we consider the system “take-home ready” if the following manual tests pass:
	1.	NL + doc RAG hero
	•	upload a simple PDF with a couple of recommended hotels + a must-see attraction.
	•	query: “4 days in lisbon in october, $2000, prefer that riverside hotel from the pdf, and outdoor walks.”
	•	expected:
	•	intent captures lisbon, dates, budget, outdoor theme,
	•	RAG picks the pdf hotel chunk,
	•	itinerary includes that hotel and references the doc in citations,
	•	answer acknowledges outdoor preference and doc-sourced info.
	2.	what-if cheaper
	•	from that run, call what-if: “make it 500 dollars cheaper”.
	•	expected:
	•	new run threaded to original,
	•	lower total cost and cheaper options selected,
	•	both runs inspectable.
	3.	stub vs openai
	•	with no api key: system clearly indicates synthesis_source stub, but still returns coherent stub markdown.
	•	with api key: synthesis_source=openai, and markdown uses real LLM content.
	4.	file-free baseline
	•	no doc uploads, plain “3 days in paris, art & food, $1500”.
	•	expected:
	•	intent ok,
	•	tools called,
	•	multi-day itinerary with reasonable allocation.
