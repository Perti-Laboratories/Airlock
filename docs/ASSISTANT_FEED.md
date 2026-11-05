# One local assistant feed — 0.5.1

This component replaces conversation switching
with one durable command thread and acknowledgement controls.

## Behavior

- Chat opens the same thread across browser sessions and app restarts. There is no New conversation
  button or conversation list. Existing conversations remain readable as provenance; their messages
  appear in the feed without changing their original IDs or associations.
- Ask questions, retrieve document/memory context, maintain explicit memories, and create or edit
  calendar events, to-dos, contacts and interactions through the existing validated local actions.
  No workflow builder or new autonomous execution is added.
- Replies, completed/failed/interrupted/cancelled local agent runs, pending high-impact memory reviews,
  and pending company-memory suggestions appear together. Notifications use persisted source IDs,
  not a new copy on every poll. Company suggestion text stays in the review screen.
- **Acknowledge** removes a reply and its associated request from the active feed. Acknowledging a
  notification only dismisses it: it never approves/publishes a memory, changes a task's status,
  releases data or changes sharing permissions. **Acknowledge all** acts on the current page's IDs;
  newly arriving items cannot be silently acknowledged by that request.
- **History** shows acknowledged items. Records and reports remain locally stored. Acknowledgement
  excludes turns from recent conversational context but does not forget canonical memory or delete
  ordinary searchable message sources. Use Memory's Forget or the source controls for those actions.
- The active feed checks for updates every ten seconds while visible and idle. Identical responses
  do not redraw it. Pagination uses a stable timestamp/key cursor, 60 items per page. Browsing older
  pages pauses background replacement; **Latest** returns to live updates.

## Company evidence boundary

A company lookup or explicitly attached company-marked source makes the current **unacknowledged
exchange** read-only. Follow-ups stay read-only until those company replies (or all shown items) are
acknowledged. An acknowledgement ends that exchange; it does not mark its contents safe to release.

Company-marked turns, including failed turns, remain permanently excluded from normal model history
and automatic message indexing. A new local request after acknowledgement uses fresh local context
without the old company answer. Company sources still require an explicit attachment or fresh company
query. As of 0.5.2, the composer uses [automatic company research](AUTOMATIC_COMPANY_RESEARCH.md)
and a Local only override; there is no separate company-query input. State changes still run through existing typed validation and the Curator.

This is a bounded context rule, not semantic DLP. Manual copying into a title or local source remains
possible; the allowed-title exception and [prototype limits](COMPANY_MEMORY_PROTOTYPE.md) still apply.
Acknowledgements are not an external protocol field. Neither company notifications nor conversation
history is added to connector releases. Existing title rules and task reviews remain authoritative.

## Acceptance test

1. Open Chat. Send “Create a local to-do titled Synthetic feed check with private notes Keep this local.”
   Verify the to-do and its private details in To-dos. Do not approve its title for sharing.
2. Acknowledge the assistant reply. The reply/request disappear. Refresh the browser: they stay hidden.
   Open History to see them; the to-do itself must still exist.
3. Return to Chat and ask to mark that to-do done. Verify the same record updates in the one thread.
   Ask Airlock to remember a harmless synthetic preference, then retrieve it after acknowledgement.
4. Finish a small existing local agent run, or create a memory requiring approval. Leave Chat visible:
   its notification appears within the next idle poll. Acknowledge it; confirm the result remains in
   Agents or the pending proposal remains in Memory, with no implicit approval.
5. Search the published synthetic Cedar company memory. Try a record mutation in the next message:
   it must remain read-only. Acknowledge the company exchange, then explicitly request an unrelated
   local to-do. That action works in the same thread; the previous company answer is absent from
   ordinary model context and ordinary message-source indexing.
6. Inspect Sharing and the reference harness: no new chat, private notes, company candidates, or
   acknowledgement fields have entered its permitted calendar/task projections.

Automated verification covers a single thread, retained provenance, persistent/idempotent receipts,
notification deduplication, acknowledgement without approval, atomic bulk acknowledgement, new-arrival
races, CSRF, equal-timestamp pagination, company isolation and subsequent ordinary actions. UI checks
cover unchanged polls, in-progress messages, stale responses, durable acknowledgements and older pages.

## Recorded local verification — October 27, 2026

- All 103 backend tests and 15 UI checks passed; the source-message endpoint checks were also rerun
  after the final bounded-history lookup change. Existing test tooling reports a Starlette/httpx
  deprecation warning, with no test failures.
- Installed 0.5.1, applied migration 0007, and restarted the managed local app.
- Real `llama3.1:8b` created **Synthetic feed acceptance** with private notes. Acknowledged its reply
  through the browser. The request/reply stayed hidden across browser reload and app restart, remained
  available in History, and the to-do/notes remained intact. This synthetic to-do is retained for testing.
- The running reference harness returned successfully and contained neither the unapproved test title,
  its private notes, nor the synthetic company code. Existing sharing permissions were unchanged.
