# Company memory prototype — 0.5.2

Implements the local prototype slice of the project roadmap.
This is synthetic/local acceptance infrastructure, not a company production deployment.

## What is running

- Airlock: `http://127.0.0.1:8741`, its existing local Postgres on port 55433.
- External Airlock Connector: port 8742, reference harness on port 8743. Its protocol is unchanged.
- Company memory service and Curator console: `http://127.0.0.1:8744`.
- Company Postgres/pgvector: separate Docker project `airlock-company-demo`, separate volume, database
  `airlock_company_demo`, role `company_demo`, loopback port 55434. Never connected planner or Airlock's live DB.

Airlock connects to a bounded company API, not an unrestricted SQL tool. The company service alone
holds its Postgres credential. The API token is distinct from connector credentials and stored by
Airlock in macOS Keychain under `Airlock.CompanyMemory.v1`. Demo provisioning files are ignored by Git
and have mode 0600. All inference/embedding stays on the dedicated local Ollama instance.

Start after installing this branch and applying local migrations:

```sh
.venv/bin/python scripts/company_demo.py start
```

This provisions the separate database and service, pins the installed embedding model digest and
vector dimensions, and writes a local invitation. In Airlock choose **Company memory → Connect local
demo**. The suggestion toggle can be selected at connection time or changed afterward. The drill-down
shows model details, processing timestamps, failures and a manual **Process next passage** action.
`stop` retains data; `status` reports the managed service. Re-running `start` preserves existing keys
and stored memories. The current prototype intentionally accepts only the literal loopback endpoint
on port 8744. Arbitrary cloud addresses and database URLs are not supported by this prototype.

## Extraction, review and publication

1. Upload a synthetic document with the plus in Chat. Ordinary new user-message sources can also be
   selected; no existing sources are opted in automatically.
2. In **Company memory → Select sources for suggestions**, select the original company-eligible source.
   Only ready document/message sources qualify. Calendar overlays, contacts and company-generated
   answers are not automatic contribution sources. A personal source must never be selected casually.
3. Enable **Suggest memories from selected sources**, then save. A local worker processes one passage
   per iteration: exact text chunks of approximately 1,600 characters, 160-character overlap, with
   paragraph/sentence boundaries where available. Pending work resumes after roughly ten seconds;
   idle/error checks retry after five minutes. The existing compute lock serializes this with local
   inference; heavy model work can delay background sync. The manual action processes one passage.
4. Ollama suggests at most three facts/decisions per passage. Each suggestion includes a title,
   content and supporting quote. Code verifies the quote is an exact substring of the passage.
   This does not prove the summary is correct: user review remains necessary. Unsupported evidence
   fails visibly. All vectors for a passage must validate before its candidates are added.
5. Airlock embeds the candidate's title plus content locally. Model name, digest and dimensions must
   match the company service's pinned specification. Finite, nonzero vectors are validated; no model
   mismatch is silently tolerated. Changing the chat model does not change the embedding model.
6. Review the exact title, content, evidence and source label in the suggestion card. **Send reviewed
   candidate** sends only those fields, source hash/passage number, candidate ID, model specification
   and its embedding. The raw file, complete source, local IDs and conversation history are absent.
   A source change, removal or unselection prevents sending an old candidate. Repeated submission
   uses the same ID and content fingerprint; it does not create duplicate company records.
7. The company console receives a **pending** candidate. Choose **Publish memory** there to make it
   searchable. `CompanyCurator` is the only publication path; the device API cannot write canonical
   status. Rejection keeps a candidate unsearchable; withdrawal immediately excludes published data
   from subsequent searches. Airlock can refresh the candidate's receipt. This two-review flow makes
   the laptop-versus-company boundary visible; later company policy can choose a different review UX.

The suggestion engine never automatically submits candidates. Extracted facts are not implicitly
written into Airlock's canonical memories either. Local rejection and source selection are audited.
Company submission, retrieval and Curator decisions have their own company-side audit records.

## Company retrieval inside chat

Ask your question in the normal chat box. With automatic company research enabled, Airlock plans
up to three topic-based searches locally, embeds each constructed query, retrieves company evidence,
and combines it with local memory and stored items for the local answer. Progress and exact queries
are visible in chat. **Local only** skips company retrieval for that message. Details and security
boundaries are in [Automatic company research](AUTOMATIC_COMPANY_RESEARCH.md).

The retrieval tool searches published records inside the authenticated company's scope. It selects
up to 64 nearest vector candidates, applies cosine/keyword ranking and a basic relevance filter, and
returns at most 12 memories within a 14,000-character evidence budget. This is a bounded first tool,
not an unlimited agent search loop. When the limit is reached, chat exposes truncation and asks for a
narrower query. Similarity thresholds are initial defaults, not a calibrated relevance guarantee.

Airlock supplies retrieved evidence and citations to the same local model context as current calendar
and to-do records. The company service does not receive that assembled context. A missing/disabled/
unavailable company service leaves local functionality intact and explicitly marks lookup failure.
Searches are live: there is no downloaded company corpus or periodic company cache hydration in this
slice. The periodic job here is the **local suggestion engine**, not a company cache refresher.

Company query/results are not automatically embedded back into local searchable message memory.
Company source titles appear with the answer. Historical answers remain visible in the local UI,
but company-marked turns are excluded from future model history; fresh lookup is required to use
company facts again. There is no offline company retrieval or silent use of revoked cached evidence.

## Implemented security boundary

| Boundary | Enforcement in this prototype |
| --- | --- |
| Ordinary private data → company | Sources require explicit selection. Candidates require exact payload review. Automatic queries contain company-owned titles plus fixed search angles; no free-form prompt fragments. No raw chat-history or background personal-data export. |
| Company canonical write | Authenticated device API inserts pending candidates only. Separate local Curator console controls publication/withdrawal. |
| Cross-company retrieval | Token maps to server-side company identity. Search and candidate identity are scoped to it. Extra client identity/SQL/tool fields are rejected. All published records within this demo company are visible to that identity. |
| Company evidence → external harness | Company tables/chunks/vectors are absent from the external protocol. Unacknowledged company-evidence exchanges are code-enforced read-only, including follow-ups; model-suggested record/memory/agent actions are discarded. |
| Company source → ordinary chat | Selected sources retain a company-restricted marker even if later unselected. Ordinary semantic retrieval excludes them; explicit attachment makes that exchange read-only until acknowledged. |
| Model output laundering | Company-marked conversation messages are not indexed, and the read-only marker persists on the user turn before inference. Acknowledging the exchange never makes those turns eligible for retrieval or indexing. |
| Permitted calendar/to-do releases | Existing user-controlled event rules and individually reviewed to-do titles remain unchanged. Event title/time/busy fields and to-do title/status/optional approved due date may leave. Descriptions, local notes, evidence, vectors and company records may not. |
| Connection independence | Pausing company retrieval or suggestions does not pause/resume external exchange or broaden either connection's permissions. |
| Transport/browser | Loopback-only endpoints, no proxy or redirects for company API calls, separate bearer token, bounded strict payloads, local-host/origin and CSRF checks for mutating browser actions. |
| Logs | Local tool logs use IDs/counts/status rather than queries/snippets. Company audit records use operation/identity/record IDs. Historical chat, reports and candidate evidence remain sensitive local stored content. |

Company-context exchanges can reason about calendar and tasks but cannot mutate them. Acknowledge
their replies to finish the protected exchange, then make a separate explicit local request in the
same running feed. The old company answer is never included in that request's model history. You can
also use the calendar/to-do editor for an independently chosen title and private details. Review
sharing as usual. See [the assistant feed](ASSISTANT_FEED.md) for acknowledgement and history behavior.

## Limits: do not claim stronger guarantees

- Meeting/task titles are **allowed disclosures**, not semantically inspected safe text. A user can
  deliberately or accidentally type confidential information into a title and approve it. No semantic
  DLP, prevention of manual copying or OS-level noninterference is claimed. Time/status metadata also
  discloses activity. The user's requested title exception does not authorize whole memories or notes.
- Selecting an original source is an explicit contribution-scope decision; this prototype cannot
  prove its organizational eligibility or retroactively label every earlier paraphrase of that source.
  Use only the synthetic fixture for this pilot. Mixed personal/company documents need careful review.
- The read-only boundary applies to company-marked sources/turns. It is not universal data-flow tracking
  across every manually entered local record, file, operating-system process or previous model output.
- The Curator console trusts the current local desktop user, uses a browser-session CSRF token, and
  is strictly loopback-only. It is not a deployable employee/admin authentication system. There is no
  SSO, per-employee document ACL, corporate policy administration, encryption-at-rest configuration,
  device attestation, per-user retention policy or production key rotation in this slice.
- Client-generated embeddings are validated for shape/model compatibility, not mathematically proven
  to represent the submitted text. A production service should recompute them on company-approved
  infrastructure and treat compromised clients as hostile.
- Raw company excerpts/answers may persist in local chat history or reports. Withdrawal prevents new
  company searches from returning a memory; it cannot retract an answer already shown or erase local
  backups. There is no bulk company cache to hydrate or revoke here.
- Company candidates are bounded semantic summaries of source passages, not a graph with entity
  resolution or an original-document archive. Embedding-model migration/reindex, source-deletion
  propagation into already published company records and employee-level ACLs remain follow-up work.

## End-to-end test with both connections

Use only [`examples/Synthetic-company-memory.txt`](examples/Synthetic-company-memory.txt).

1. Start Airlock, the existing connector/harness, and the company prototype. Keep current external
   sharing rules; never broaden them simply for this test. Connect the company demo in the sidebar.
2. Upload the fixture; select only that source. Turn suggestions on. Inspect the drill-down and click
   **Process next passage** if needed. Expect suggestions with exact evidence and the pinned embedding
   specification. Before sending, the company console must have no new candidate from this source.
3. Send a reviewed candidate about Cedar's launch date. It appears as pending in the company console.
   Search before publication: it must not appear in company results. Publish it there; search again.
4. In Airlock Chat ask: “According to company memory, when does Project Cedar launch,
   and how does that fit with my upcoming calendar?” Expect the published fact with company
   citation and a read-only indicator. Chat's calendar window is currently the next 30 days; it must
   acknowledge coverage limits for dates outside that window.
5. Ask that same chat to create a to-do using company material. Expect no mutation, including on a
   follow-up with Local only selected. Existing company answers must not appear as ordinary
   searchable message sources.
6. In the To-dos editor create **Prepare Cedar launch**, with **CEDAR_INTERNAL_7429 — private planning
   notes** in Private details & notes. Review only the generic title for release. Create a synthetic
   future calendar event with a permitted title and private description. The harness should receive
   approved titles/status/times only, with no notes, rollout code, evidence, embeddings or company fact.
7. From the harness, send generic availability. It appears in Airlock through the existing return
   connection. It must not appear as a company suggestion/source. Nothing is written to Google.
8. Pause the company connection. After acknowledging company replies, ordinary chat and external calendar/to-do exchange still work;
   company lookup reports unavailable. Re-enable it. Withdraw the company memory in the Curator
   console; a new lookup must no longer return it. Historical display is intentionally retained.
9. Change/unselect the original source before submitting another pending candidate. Submission must
   be blocked. Repeatedly submitting an unchanged approved candidate must leave one company record.

Automated tests additionally cover forged identity, wrong model/dimensions, missing credentials,
CSRF protection, fabricated evidence, partial embedding failures, restricted attachments, and exact
external projection exclusions. The prototype does not imply approval to deploy on a work laptop.

## Recorded personal acceptance — October 27

- Airlock 0.5.0 and the company demo run with separate Postgres containers/volumes on 55433/55434.
- Real local Ollama produced three exact-evidence suggestions from the Cedar fixture, using
  `nomic-embed-text:latest` pinned by digest with 768 dimensions. Only that fixture was selected;
  existing personal sources remained unselected.
- The company console initially contained no candidates. Sending the launch-date candidate created
  one pending record. A real company search returned zero memories before Curator publication.
- After publication, the local `llama3.1:8b` chat retrieved and cited the December 3 launch date and
  identified the calendar coverage limitation. The conversation displayed its read-only indicator.
- The reference harness received an existing synthetic future calendar event and the reviewed title
  **Synthetic: prepare Cedar launch**. Its feed excluded `CEDAR_INTERNAL_7429`, the to-do description,
  and company memory content. A new generic availability block returned through automatic polling.
- Existing Google source refresh was unavailable during this later test and remained visibly stale;
  successful local company/connector exchange does not establish Google source freshness.
- The published launch-date memory, two unsent suggestions, synthetic source and synthetic to-do are
  retained for user acceptance. The return availability lease expires after 15 minutes unless renewed.
- Automated verification: 97 backend checks and 10 UI checks passed. Browser verification also covered
  connection setup, source selection, candidate submission/publication, citations and the smaller-screen
  **New conversation** control (subsequently replaced by the single feed in 0.5.1).
- A live follow-up asking to create `CEDAR_COMPANY_LEAK_TEST` in the company conversation produced
  no changes and left the to-do count unchanged, even with no company query on that follow-up.
