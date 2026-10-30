# Data format — the on-disk contract

The write side of `.learnharness/`. Consult this when you write a plan, a check, a problem, a
proposal, or when a script refuses something and you need to know why. It is a reference, not a
tutorial: `references/plan.md`, `references/practice.md`, and `references/graph.md` describe the
procedures that produce these artifacts.

The read side is `graph.py` and `session.py state`. Nothing here is derived by hand when a
script can derive it.

## Directory tree

```
.learnharness/
├── graph/
│   ├── nodes.jsonl        # propositions, one JSON object per line
│   ├── chains.jsonl       # arguments, one JSON object per line
│   └── format.json        # the format stamp
└── sessions/
    └── <session-id>/
        ├── session.jsonl  # the event log — canonical, append-only
        └── session.md     # rendered by `session.py render --write`
```

- The record root is the `.learnharness` directory itself. Scripts find it by walking up from
  the project; they never resolve paths from the current directory of the script.
- One learner per record. Everything lives under the project root and is committed to git.
- `session.jsonl` and the two ledgers are append-only. Nothing rewrites them.
- `session.md` is generated output. Regenerate it freely; never treat it as the source of
  truth, and never hand-edit it.

## `format.json`

```json
{
	"version": 1,
	"writer": "learnharness-teach/0.1"
}
```

| key | type | rule |
|---|---|---|
| `version` | int | must be written. The only version this skill writes is `1`. |
| `writer` | string | emitted for provenance; readers ignore it |

- A reader refuses `version > 1`: exit 1, no writes. The refusal is central (every script reads
  the stamp through the same helper), so there is no path that skips it.
- An absent or unreadable stamp reads as version 1. An existing stamp is never rewritten.
- Do not hand-edit the stamp, and do not delete it to get past a refusal. A newer stamp means
  newer data: stop and say so.
- `graph.py export` writes the stamp into its destination with `version` alone; `writer` is
  informational and no reader requires it.

## Session ids

Format: `lh_` + 8 lowercase base36 characters, for example `lh_k3m9x2qp`.

- Validated against `^lh_[a-z0-9]{8}$` before any path is built.
- Minted by `session.py init`, never by hand. Uniqueness is checked against the existing
  session directories.
- A session id is also the `chatId` used in graph provenance; see below.

## The event log

`session.jsonl` — one JSON object per line.

| rule | detail |
|---|---|
| encoding | UTF-8, one compact object per line, each line terminated by `\n` |
| append-only | never rewrite, reorder, truncate, or delete a line. A correction is a new event |
| `seq` | assigned by `session.py`: 1-based, strictly increasing, no gaps |
| `at` | assigned by `session.py`: ISO-8601 UTC to the second, e.g. `2026-01-14T09:31:07Z` |
| order | `seq` and `at` are written first, then the event's own fields. Readers must not depend on key order |
| numbers | JSON numbers only; non-finite values (`NaN`, `Infinity`) are rejected by the reader |
| event types | exactly the nine below. There is no extension field and no extra event type |

Common to every event:

| field | type | meaning |
|---|---|---|
| `seq` | int ≥ 1 | 1-based position in the log; strictly increasing, no gaps |
| `at` | string | ISO-8601 UTC timestamp |
| `type` | string | one of the nine event type names |

### 1. `session_start`

```jsonc
// 1. session_start — always seq 1, always exactly one
{"seq":1,"at":"…","type":"session_start","kind":"teach","goal":"understand why entropy always increases"}
```

| field | type | required | meaning |
|---|---|---|---|
| `kind` | string, `"teach"` or `"practice"` | yes | the session kind; nothing else may appear |
| `goal` | string | yes | the learner's goal in their own words |

Exactly one per session, always `seq` 1.

### 2. `check_posed`

```jsonc
// 2. check_posed — the key is committed here, before the learner sees the question
{"seq":2,"at":"…","type":"check_posed","node":null,"question":"What does 'reversible' mean for a process?",
 "options":["It can be run backwards with no net change to the universe","It happens slowly","It is isothermal"],
 "correct":[0],"key":"A reversible process leaves no net change in the universe; that is the definition, not a rate property."}
```

| field | type | required | meaning |
|---|---|---|---|
| `node` | string or null | yes | plan node id; `null` during the probe phase |
| `question` | string | yes | the question as the learner saw it |
| `options` | array of string | when offered | the answer options, in display order |
| `correct` | array of int | when offered | 0-based indices into `options` |
| `key` | string | yes | the answer key in full prose, committed here, before the learner answers |

A free-recall check omits `options` and `correct`. `key` is never omitted: a check without a
key is a refusal, and `verify.py` reports one that got in.

### 3. `answer`

```jsonc
// 3. answer — closes the check named by check_seq
{"seq":3,"at":"…","type":"answer","check_seq":2,"selection":[0],"correct":true,
 "confidence":4,"trace":"No net change anywhere means it can be undone exactly."}
```

| field | type | required | meaning |
|---|---|---|---|
| `check_seq` | int | yes | `seq` of the `check_posed` this closes |
| `selection` | array of int, or array holding one string | yes | option indices for an option check; a free-recall check (`answer --text`) stores the learner's words as the single element |
| `correct` | bool | yes | correctness, computed by the agent — no script grades |
| `confidence` | int 1–5 | yes | the learner's stated confidence |
| `trace` | string | yes | the learner's thinking as they gave it |

For a free-recall check the learner's words are the single element of `selection`; there is no
separate text field. An `answer` whose `check_seq` does not exist, or which answers an
already-answered check, is a defect `verify.py` reports.

### 4. `probe_concluded`

```jsonc
// 4. probe_concluded — at most one per session, refused while a check is open
{"seq":4,"at":"…","type":"probe_concluded",
 "strands":[{"strand":"entropy as counting","assessment":"holds; can explain multiplicity without prompting"}],
 "summary":"Strong on counting, no working notion of irreversibility."}
```

| field | type | required | meaning |
|---|---|---|---|
| `strands` | array of object | yes | one entry per dependency strand examined |
| `strands[].strand` | string | yes | the strand's name |
| `strands[].assessment` | string | yes | what was measured on that strand |
| `summary` | string | no | one-line verdict for the whole probe |

At most one per session. Refused while a check is open.

### 5. `plan_set`

```jsonc
// 5. plan_set — revision 1 is the initial plan, 2+ are revisions
{"seq":5,"at":"…","type":"plan_set","revision":1,
 "nodes":[{"id":"irreversible","title":"Irreversibility","summary":"why some processes have a direction"}],
 "edges":[{"from":"counting","to":"irreversible"}]}
```

| field | type | required | meaning |
|---|---|---|---|
| `revision` | int ≥ 1 | yes | 1 for the initial plan, 2 and up for revisions |
| `nodes` | array of object | yes | non-empty; validated by `plan.py` |
| `nodes[].id` | string | yes | matches `^[a-z0-9]+([_-][a-z0-9]+)*$` |
| `nodes[].title` | string | yes | non-empty short label |
| `nodes[].summary` | string | no | one line of what the node asserts |
| `edges` | array of object | yes | may be empty |
| `edges[].from` | string | yes | the prerequisite node id |
| `edges[].to` | string | yes | the node id that depends on `from` |

Validated by `plan.py` before it is appended; an invalid plan is refused, never recorded.
That includes an unknown key at any level and a `summary` that is not a string. The plan in
force is the `plan_set` with the highest `revision`.

### 6. `step_closed`

```jsonc
// 6. step_closed — a teaching step finished
{"seq":6,"at":"…","type":"step_closed","node":"irreversible","outcome":"held"}
```

| field | type | required | meaning |
|---|---|---|---|
| `node` | string | yes | plan node id; must be in the current plan, or the script refuses |
| `outcome` | string, `held` / `partial` / `missed` | no | written on every event; `held` when the flag is omitted |

`verify.py` reports a `step_closed` whose node is absent from the current plan. If a revision
drops a node that was already taught, that finding is expected — do not resolve it by deleting
history.

### 7. `practice_problem`

```jsonc
// 7. practice_problem — practice sessions only; modelSolution is committed up front
{"seq":2,"at":"…","type":"practice_problem","statement":"…","mode":"recall",
 "target":["irreversible"],"modelSolution":"…"}
```

| field | type | required | meaning |
|---|---|---|---|
| `statement` | string | yes | the problem exactly as the learner sees it |
| `mode` | string, `recall` / `discrimination` / `composition` | yes | the demand mode |
| `target` | array of string | yes | the ids the problem exercises: graph node ids when sampled from the graph, plan node ids when the material came from the plan fallback |
| `modelSolution` | string | yes | the full solution, committed before the learner works; revealed at conclusion, never re-authored |

Practice sessions only. `modelSolution` is the pre-committed answer key: it is written here,
before the problem is posed, and it is what `practice_concluded` reveals.

### 8. `practice_concluded`

```jsonc
// 8. practice_concluded — practice sessions only
{"seq":3,"at":"…","type":"practice_concluded","outcome":"solvedWithHints","verdict":"…",
 "rung":"R2","missClass":"cue","retest":true}
```

| field | type | required | meaning |
|---|---|---|---|
| `outcome` | string, `solved` / `solvedWithHints` / `movedOn` / `surrendered` / `dismissed` | yes | how the problem ended |
| `verdict` | string | yes | what was credited and where it broke |
| `rung` | string `R0`–`R5`, or null | yes | the hint rung the problem needed; `null` when no rung applies |
| `missClass` | string `cue` / `discrimination` / `execution` / `careless` / `structural`, or null | yes | the miss classification; `null` when there was no miss |
| `retest` | bool | yes | marks the problem for a fresh-surface retest before the session ends |

Practice sessions only. Supply all five fields. `rung` and `missClass` may be null when nothing
applies; the event then carries no key for them, which is the record's way of saying "not
applicable" — a legitimate value, never a gap to fill with a guess. See `references/practice.md`
for what each value means.

### 9. `session_closed`

```jsonc
// 9. session_closed — terminal; at most one
{"seq":7,"at":"…","type":"session_closed","nodes_written":12,"chains_written":4}
```

| field | type | required | meaning |
|---|---|---|---|
| `nodes_written` | int ≥ 0 | no | node lines this session contributed to the graph |
| `chains_written` | int ≥ 0 | no | chain lines this session contributed |

Both counts are optional; `close` accepts neither, one, or both. A practice session
legitimately closes with no counts because it writes no propositions.

Terminal: nothing follows it, and at most one exists. A second `close` refuses.

## Derivations

All derived from the log, never stored. `session.py state` prints these.

| value | rule |
|---|---|
| `phase` | a `session_closed` exists → `closed` (this overrides the rest). Otherwise: `kind` is `practice` → `practice`; no `probe_concluded` → `probe`; no `check_posed` with a non-null `node` → `plan`; else `teach` |
| `open check` | the last `check_posed` whose `seq` is not referenced by any `answer.check_seq`. At most one may be open |
| `current node` | `node` of the most recent `check_posed` with a non-null `node`, else `null` |
| `visited nodes` | every distinct non-null `node` in a `check_posed` earlier than the most recent node-tagged one |
| `plan` | the `plan_set` with the highest `revision` |
| `closed` | a `session_closed` event exists |

The plan phase ends at the first **node-tagged check**, not at `plan_set`. Authoring a plan
does not by itself leave the plan phase; only `session.py check --node ID` does.

`state` reads the log only. It is the bounded resume surface: read it instead of the log, and
read the log only when you need an event's payload (a probe summary, a plan, a transcript).

## Graph ledgers

One JSON object per line, append-only, in `graph/`. These are the files the app reads, so their
shape is not negotiable.

```jsonc
// nodes.jsonl
{"id":"n_a1b2c3d4e5f6","name":"Entropy is a count","statement":"Entropy is the logarithm of the number of microstates.",
 "aliases":[],"createdAt":"…","provenance":[{"chatId":"lh_k3m9x2qp","messageId":"4"}]}

// chains.jsonl
{"id":"arg_a1b2c3d4e5f6","premises":["n_…"],"conclusion":"n_…",
 "provenance":[{"chatId":"lh_k3m9x2qp","messageId":"4"}],"createdAt":"…"}
```

Node line:

| field | type | required | meaning |
|---|---|---|---|
| `id` | string, `n_` + 12 lowercase hex | yes | derived from the statement; never chosen |
| `name` | string | yes | short display label, set by the first line for this id |
| `statement` | string | yes | the proposition as a sentence |
| `aliases` | array of string | yes, may be empty | other phrasings; the list the merge appends to |
| `createdAt` | string | yes | ISO-8601 UTC |
| `provenance` | array of object | yes, may be empty | `{chatId: string, messageId: string}` points |
| `provenance[].chatId` | string | yes | the session id, e.g. `lh_k3m9x2qp` |
| `provenance[].messageId` | string | yes | the originating event's `seq`, as a decimal string |

Chain line:

| field | type | required | meaning |
|---|---|---|---|
| `id` | string, `arg_` + 12 lowercase hex | yes | derived from the chain key; never chosen |
| `premises` | array of string, at least 1 | yes | node ids |
| `conclusion` | string | yes | a node id |
| `provenance` | array of object | yes, may be empty | same shape as a node's |
| `createdAt` | string | yes | ISO-8601 UTC |

A chain with no premises is not a chain: a proposition asserted on its own rides the node
ledger alone.

## Writer obligations

These are not stylistic. Each one exists because the app drops or corrupts a line that misses
it, and it drops it silently.

1. **`aliases` and `provenance` are always present arrays**, even when empty. The app drops any
   node line missing either one.
2. **Every chain premise and conclusion resolves to a node id that exists** in `nodes.jsonl`
   after the merge. The app drops a chain whose endpoints do not resolve.
3. **`provenance.chatId` is the session id** (`lh_` + 8 characters) and
   **`provenance.messageId` is the `seq` of the originating event, as a string**. `"4"`, not
   `4`.
4. **Node ids are `n_` + 12 lowercase hex; chain ids are `arg_` + 12 lowercase hex.** They are
   derived deterministically from the statement and from the chain key, so a re-run mints the
   same ids and is idempotent. Never invent, hand-compute, or reuse an id.
5. **Merging follows the app's law:** a later line with an existing id appends its `statement`
   and `aliases` to the accumulated `aliases` and unions `provenance`; `name` and `createdAt`
   from later lines are ignored.
6. **Malformed lines are skipped by the app silently.** `graph_write.py` therefore validates
   every record it writes and refuses rather than emitting something that would vanish. Never
   write a ledger line by hand to work around a refusal.

The app's node guard also requires `id`, `name`, `statement`, and `createdAt` to be strings; a
line missing any of them is dropped the same way. `graph_write.py` emits all of them, which is
why it is the only writer.

## Ids

| object | format | example | source |
|---|---|---|---|
| session | `lh_` + 8 lowercase base36 | `lh_k3m9x2qp` | random, checked for uniqueness, validated by `^lh_[a-z0-9]{8}$` |
| graph node | `n_` + 12 lowercase hex | `n_a1b2c3d4e5f6` | sha256 of `node\0` + the trimmed statement, first 12 hex; a collision with a different statement is disambiguated by the writer |
| graph chain | `arg_` + 12 lowercase hex | `arg_a1b2c3d4e5f6` | sha256 of `chain\0` + sorted premises joined by `\0` + `\x01` + conclusion, first 12 hex |
| plan node | slug | `irreversible` | author-chosen; `^[a-z0-9]+([_-][a-z0-9]+)*$` |

Plan node ids and graph node ids are different namespaces. A plan id appears only in `plan_set`,
`check_posed.node`, `step_closed.node`, and — when practice fell back to a plan —
`practice_problem.target`. A graph id appears only in the ledgers and in
`practice_problem.target` when the material was sampled from the graph. Never put a plan id in
a ledger or a graph id in a plan.

The exact hash derivation lives in `scripts/_data.py` (`mint_node_id`, `mint_chain_id`). Do not
reimplement it; call the writer.

## Provenance encoding

- `chatId` is the session id itself — the `lh_` prefix is already part of it.
- `messageId` is the `seq` of the event that established the claim, as a decimal string.
- One point per establishing event. A node established by two checks carries two points; the
  merge unions them.
- Provenance is evidence, not decoration: it is how a later reader finds the session and the
  line that produced the claim. Never fabricate a point, and never leave the array out.

## What not to do

1. **Do not rewrite the log.** `session.jsonl` is append-only, in order, with no gaps. Do not
   edit a line, delete a line, renumber, or regenerate the file.
2. **Do not invent ids.** No hand-minted `n_…` or `arg_…`, no reused id for a different claim,
   no plan id in a ledger.
3. **Do not emit a chain before its nodes.** Node lines are written first; a chain that points
   at a node written later is a chain the app drops.
4. **Do not write outside `.learnharness/`.** Working files (`plan.json`, `proposals.json`) are
   scratch and belong outside the record; the record holds only what the scripts write.
5. **Do not create `sessions.jsonl` or `coverage.jsonl`.** Those are the app's bookkeeping for
   its own chats. Skill sessions have no chat to fold, and the skill does not emit session
   checkpoints or per-message coverage.
6. Do not hand-edit `session.md` or `format.json`. The first is generated; the second is a
   version stamp, and a wrong one makes every reader refuse.
7. Do not emit non-finite numbers, BOMs, or multi-line JSON objects. One compact object per
   line, UTF-8, newline-terminated.
