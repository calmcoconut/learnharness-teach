# Close: extraction, audit, merge

The session is over. Turn what the learner demonstrated into propositions and reasoning chains,
audit them, merge them into the knowledge graph, verify the result, and report.

This is the most safety-critical step in the skill. The app reads the ledgers and **drops
malformed lines silently** — a bad write does not error, it disappears, and the graph quietly
loses evidence. Write only through `graph_write.py`; it validates before it writes.

## When it runs

- Prompt once, at the end of a teach session: the session is complete, do you want to record
  what you established?
- Run only on an explicit yes. Extraction is never automatic: no confirmation, no writes.
- If the learner declines, stop. Do not write, do not defer a write to a later turn without a
  fresh confirmation.
- Practice sessions are not extracted at all. See `references/practice.md`.

## Tree-blind by design — read this twice

The close runs in a **fresh invocation whose only inputs are the session log**:

1. `python3 <skill>/scripts/session.py state --session ID` for the derived summary.
2. The rendered transcript without the plan:
   `python3 <skill>/scripts/session.py render --session ID --no-plan`, or the `session.md`
   already written by `render --write --no-plan`.

`--no-plan` is required here: the plan is what you intended to teach, the graph must record
what the learner established.

**Do not read the plan.** Not `plan_set` node or edge payloads in the log, not a scratch plan
file, not a plan outline from earlier in the conversation. The `state` output's `plan` line
gives counts — counts are harmless. Anything with content is contamination.

Why: the plan describes *intended* teaching. The ledgers record what was *actually
established*. Those are different facts, and the difference is the entire value of the graph.
An extractor that can see the plan writes nodes because they were planned, not because the
learner showed them; the record then claims understanding nobody demonstrated. Tree-blind is
not a convenience — it is what keeps intent out of the evidence.

The test, applied to every candidate: **what line of the transcript is the evidence?** If the
only reason to believe the learner holds it is that the plan says it should have been taught,
drop it.

The log does contain `plan_set` events, but the rendered transcript excludes them. A tagged
check still names its node id; that is position evidence, not the plan. Extract from
`check_posed`, `answer`, `step_closed`, `probe_concluded`, and the learner's own words.

## Three roles, one pass

| role | asks | produces |
|---|---|---|
| extract | what did the learner state or use? | candidate propositions and chains |
| audit | is each one true, stated, and established? | keep or drop, with a reason |
| merge | how does this enter the graph? | one `graph_write.py merge` run |

Do all three before merging. The audit is judgement; no script performs it, and
`verify.py` checks structure only.

### Extract

**Propositions** — atomic claims the learner stated or correctly used.

- One claim per proposition. Split conjunctions: "entropy is a count and it never decreases" is
  two propositions, and probably one chain.
- `statement` is the claim in one sentence. `name` is a short display label.
  `aliases` are other phrasings the learner used for the same claim.
- Include only what the learner demonstrated. Your own explanation is not evidence.

**Chains** — a premise set and the conclusion the learner drew from it.

- A chain is the learner's own reasoning as it appears in the transcript: premises first,
  conclusion second, in the order they were used.
- Do not assemble a chain out of propositions that are individually held. That is inference,
  not evidence of the learner's inference.
- A chain needs at least one premise. A proposition with no argument rides the node ledger
  alone.
- A conclusion equal to the sole premise is refused by the writer.

**Volume** — as many as the evidence supports. There is no target count. Do not pad toward a
number, do not mirror the plan's size, and do not invent a proposition to give a chain an
endpoint.

### Audit

Apply all five tests to every candidate before writing anything.

| test | question | drop when |
|---|---|---|
| true | would you assert this yourself, without qualification? | it is false, or only true under conditions the learner has not got |
| established | did the learner produce it, use it correctly, or restate it? | it was mentioned in passing, asked about, gestured at, or only said by you |
| stated | is the chain visible as the learner's own sequence of moves? | you assembled it from propositions that are held separately |
| novel | is it already in the graph under another phrasing? | an existing node already says it — reuse instead of minting a near-duplicate |
| distinct | is it the same claim as another candidate in this batch? | two refs would mint two nodes for one claim |

Two rules the audit exists to enforce:

- **A misconception is not a proposition.** If the learner said something wrong and you
  corrected it, write only what was established *after* the correction — and only if it was.
  Writing the wrong version poisons the graph; the ledgers are append-only and the app has no
  correction path.
- **Mentioned is not established.** A term named in passing, an aside, an example the learner
  did not work, a question they asked: none of these are evidence of understanding.

Check the existing graph before merging, so reuse happens at the writer instead of by luck:
`python3 <skill>/scripts/graph.py propositions`, and `python3 <skill>/scripts/graph.py find QUERY` for a
phrasing you are unsure about. Reuse matches on `statement` or an alias.

Drop rather than soften. A dropped true proposition costs one future re-teach. A written false
one corrupts the record silently and permanently.

### Merge

Proposal input uses **local refs** so you never invent global ids:

```json
{
  "nodes": [
    {"ref": "a", "statement": "Entropy is the logarithm of the number of microstates.", "name": "Entropy is a count", "aliases": ["entropy counts arrangements"]},
    {"ref": "b", "statement": "A reversible process leaves no net change in the universe.", "name": "Reversibility", "aliases": []}
  ],
  "chains": [
    {"premises": ["a"], "conclusion": "b"}
  ]
}
```

1. Write the proposals to a scratch file outside `.learnharness/`, for example
   `proposals.json`.
2. Run `python3 <skill>/scripts/graph_write.py merge --session ID --proposals proposals.json`.
3. Read the result: `{"ok":true,"nodes":N,"chains":M,"reused":R}`.

`nodes` counts node writes, `chains` counts chain writes, `reused` counts nodes matched to an
existing statement or alias instead of minted.

The writer refuses, and writes nothing, on: a ref used but not defined, an empty premise list,
a duplicate chain key, or a chain whose conclusion equals its sole premise. Fix the proposals
and re-run. Re-running is safe: the writer is idempotent and appends only new provenance links
and new chains.

Never write a ledger line by hand and never compute an id. `graph_write.py` is the sole writer
to `nodes.jsonl` and `chains.jsonl`.

## What the writer guarantees — and what it cannot

| guarantee | why it matters |
|---|---|
| `aliases` and `provenance` always emitted, even when empty | the app drops any node line missing either |
| every chain endpoint resolves after the merge | the app drops a chain whose endpoints do not resolve |
| deterministic ids, so a re-run is idempotent | the same statement or chain key mints the same id, so a re-run adds provenance instead of duplicates |
| app merge law applied | a later line with an existing id appends `statement` and `aliases` to the accumulated aliases and unions provenance |

**Not guaranteed: that a proposition is true.** Nothing checks truth. The writer validates
shape, resolves endpoints, and merges; it cannot tell a fact from a fluent misconception. That
is the audit's job, and it is the only thing standing between the learner's error and a
permanent graph node.

Also not guaranteed: completeness. The graph holds what the transcript shows, nothing more.

## Verify

Run `python3 <skill>/scripts/verify.py` after merging. Add `--session ID` to scope the audit to this
session. It exits 1 when it finds anything wrong, and it checks the whole record, not only what
you just wrote: open checks, missing keys, bad answer references, duplicate probe conclusions,
invalid plans, `step_closed` for a node absent from the current plan, dangling chain endpoints,
node lines missing `aliases` or `provenance`, and a `format.json` version above 1.

- Report the findings to the learner, including the clean case.
- Do not repair findings by rewriting ledger lines. The ledgers are append-only.
- A structural finding in data this writer produced means a proposal was malformed in a way
  validation missed. Report it and stop rather than patching the file.

## Record the close

After the merge and the verify:

```
python3 <skill>/scripts/session.py close --session ID
```

This appends the terminal `session_closed` event; nothing may be written to the session after
it. At most one exists; a second call refuses.

Order: extract → audit → merge → verify → close → report. Take the counts from the merge result
and report them, so the report matches the graph rather than a stale plan.

## Export into the app

```
python3 <skill>/scripts/graph.py export --to DEST
```

`DEST` is the destination **graph directory** — the directory that holds `nodes.jsonl` and
`chains.jsonl`. You may also pass the app's data directory: unless `DEST` already contains
those two ledgers or is itself named `graph`, the ledgers are written into `DEST/graph`, which
is the usual case.

Export refuses rather than damages:

- it refuses if the destination's `format.json` is newer than this skill understands, and
  writes nothing;
- it refuses if the destination already holds a non-empty `nodes.jsonl` or `chains.jsonl`,
  naming the files, unless you pass `--replace`;
- it refuses if the source record has no graph directory, so a wrong `--data-dir` cannot
  stamp an unrelated destination;
- it refuses if any source ledger line is malformed, naming `file:line` and the reason,
  because the app would drop that line silently.

Copies are staged and swapped into place, so an interrupted export cannot leave a torn file.
It reports whether it created or replaced, and how many records it wrote.

- Export is the supported route into the app. Never copy or edit the app's data files by hand.
- Export after `verify.py` passes.
- Export must not delete or rewrite the app's `sessions.jsonl`, `coverage.jsonl`,
  `sources.json`, or `positions.json`. Those are the app's bookkeeping for its own chats; this
  skill does not produce them and has no business touching them.
- Export only when the learner wants the graph in the app. A session that stays in
  `.learnharness/` is a complete record.

## Report back

A closing session reports counts, not a narrative:

- propositions written, and how many were reused rather than minted
- chains written
- what the audit dropped, one line each, with the reason (not established, misconception,
  duplicate, assembled)
- any `verify.py` findings
- whether the export ran

## Do not extract

- plan nodes as such, or anything whose only evidence is the plan
- practice problems, model solutions, rung or miss data (practice writes no propositions)
- misconceptions, even corrected ones, unless the corrected claim was then demonstrated
- bare vocabulary: a term the learner used without a claim attached
- the goal statement, the probe's assessments, or your own summaries of the session
- chains you constructed rather than observed
