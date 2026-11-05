# Automatic company research — 0.5.2

This component. Chat no longer needs a second
company-query field. When a company connection is enabled, automatic research is on by default.
Disable it in **Company memory**, or select **Local only** for a message.

## Turn flow

1. Retrieve local canonical memory using the existing Ollama embeddings and local retrieval service.
2. Read the bounded current calendar/to-do context, retrieve local document/message passages, and
   look up matching contacts and interactions. These remain on the laptop.
3. Fetch a fresh, authenticated company topic catalog: up to 80 distinct titles of published company
   records, scoped to the connection's company. Pending/withdrawn records are excluded.
4. A local Ollama planning call chooses zero to three topic/search-angle pairs. Its inputs are the
   current message and the company topic catalog, not private memory, documents, item details or
   earlier conversation history. Simple local edits and unrelated questions can select zero searches.
5. Application code constructs each query from the exact company-owned title plus a fixed angle:
   overview, dates/timeline, owners/responsibilities, decisions, process/policy, or status/blockers.
   Ollama embeds each query locally; the company API returns published, tenant-scoped RAG evidence.
6. Deduplicate evidence by company record ID and combine at most 12 records / 14,000 excerpt characters
   across all searches. Individual searches retain the existing vector/keyword ranking and 64-candidate
   bound. The company topic catalog and result limits are explicit, not an exhaustive research claim.
7. The main local Ollama call receives the combined company evidence alongside local memory, source
   passages, contacts, tasks and calendar context. Read-only research uses a small answer-only schema.
   It gets company source filenames and excerpts; record IDs/titles stay in provenance metadata instead
   of competing with filenames as citations. An explicit calendar-window summary and matching task
   titles help ground the answer. When task titles match the request, unrelated tasks are omitted from
   read-only synthesis. Normal local editing keeps its existing action context and validation.

The visible progress panel reports actual stage state, actual constructed queries and result counts.
It does not display model chain of thought. Completed replies retain **Research & actions** details;
progress also survives acknowledgement in local History. The live polling channel is ephemeral and
bounded (64 turns, 30-minute idle expiry); persisted reply/report traces provide the lasting record.
Reloading during a turn loses its live panel; the eventual reply is still persisted and appears in the
feed. Duplicate request IDs are rejected while present in the progress registry; this is not durable
idempotency across server restarts.

## What crosses each boundary

- The company receives a request for its own topic catalog, then only selected company titles with
  fixed search-angle words and embeddings of those constructed queries. Neither the normal message
  nor its vector, private memory, local source text, calendar/task details or history is forwarded.
- A strict schema restricts the planner to catalog indices and enumerated angles. The whole plan is
  validated before any search; arbitrary query strings, extra fields, invalid indices and more than
  three searches fail closed. Queries are deduplicated. No model-generated free-form text is accepted
  on the automatic company search path.
- Topic selection, timing and search angles reveal what company subjects the user is researching.
  This is intentional metadata disclosure. These controls are not a guarantee against every semantic
  inference, malicious catalog instruction, manual copying, or an already compromised endpoint.
- A selected company lookup protects the turn before receiving evidence. Company-backed exchanges
  remain read-only until acknowledged and are never indexed into ordinary message memory. Choosing
  Local only does not erase an already active protected exchange; acknowledge it before local edits.
- Acknowledgement does not authorize export. Company answers, progress traces, candidate facts and
  embeddings remain absent from external connector projections. Calendar/task title exceptions and
  individual task-release review are unchanged.
- The previous explicit `company_query` API field remains for compatible callers who deliberately
  supply a query; the UI no longer uses it. Local only takes precedence over that field too.

Company topic reads, query planning, embedding and searches are audited using operation names and
IDs/counts. Progress traces containing company topic titles are sensitive local data, just like answers.

## Failure and scope limits

A paused/missing connection, automatic-research opt-out, or Local only skips company access. An empty
published catalog produces no search. Invalid plans, unavailable services or incompatible embeddings
produce visible failed steps; local synthesis continues with the available local evidence. Partial
search failure retains successful evidence and explicitly warns that some searches failed. No silent
cloud-model fallback, unlimited search loop, SQL access or canonical-memory writes are introduced.

Answer completeness and grounding still depend on the selected local model; retrieved evidence does
not guarantee a correct answer. Progress and citations make the inputs reviewable.

The topic catalog is a safe initial query vocabulary, not a complete semantic index of a large company.
The 80-title cap, title quality and local planner accuracy can limit recall. A future company-managed
search-topic hierarchy or approved richer query contract can broaden this without forwarding private
prompt fragments. Local memory already uses semantic retrieval; calendar/tasks are still bounded
structured context (next 30 days / up to 32 each), and contact lookup returns up to four matches.

## Acceptance test

1. Publish the synthetic Cedar launch-date candidate in the company console. In Airlock, confirm
   **Company memory → Automatically research company memory in chat** is enabled.
2. In the normal chat box, ask: “According to company memory, when does Project Cedar launch? Compare
   that with my local calendar coverage and any Cedar preparation to-dos. Cite the source.” No second
   query is needed. Watch local retrieval, topic loading, local query planning, query embedding,
   company searches, and local synthesis. Expand **Research & actions** on the reply afterward.
3. Expect the published December 3, 2026 date and its company citation, with an honest calendar-window
   limitation if the date lies outside local coverage. Multiple queries may return the same fact;
   the final company evidence list must not duplicate its ID.
4. Select Local only and ask an ordinary local question. The trace should show company research
   skipped. A previous company exchange remains read-only until acknowledged.
5. Disable automatic research in Company memory and repeat. Re-enable it afterward if desired.
   Disconnect the company service to exercise visible failure and local-only fallback.
6. Check the reference harness: no company answer, research trace, private notes or embedding should
   appear in its approved calendar/task projection.

## Verification notes

Automated checks cover private text absent from company requests, strict planner validation, company
identity and publication scope, withdrawn topics, both opt-outs, continued local editing when no
research is needed, partial failures, result deduplication and a shared evidence budget. They also
cover progress while inference is blocked, stale UI polls, the answer-only schema, and persistent
company protection if final synthesis fails. Failure testing exposed and fixed replay of already
committed audit rows during rollback; completed earlier tool audits are now preserved without duplicates.

The live Mac/Ollama test exercised two automatic Project Cedar searches, embeddings, company retrieval,
combined local context and visible progress. Earlier diagnostic replies showed small-model grounding
errors, prompting the smaller synthesis schema, explicit coverage summary, named-task filtering and
filename citations. Those intermediate synthetic exchanges were acknowledged and retained in History.
The reference harness remained available and excluded the company code, company launch fact, private
test notes and research traces. Existing external release rules were unchanged.

Final live acceptance on October 27 used `llama3.1:8b` with two generated Project Cedar searches.
The answer cited **Synthetic-company-memory.txt**, gave **December 3, 2026**, correctly identified
that as outside the **October 27–November 25** calendar window, and named only the matching open
**Synthetic: prepare Cedar launch** to-do. The expanded trace showed all retrieval/embedding/search/
synthesis stages. The successful reply remains in the active feed for user review.
