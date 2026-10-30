# Plan phase

The learner has been measured. Author the dependency map from where their understanding
actually ends to the goal, record it, present it once, then hand off to teaching.

The plan is a node/edge list. It is never prose.

`references/teach.md` owns step size, check phrasing, and the teaching loop. This document
owns the map only. `references/graph.md` owns the knowledge graph written after the session;
the plan is not that graph.

## Entry condition

1. Run `python3 <skill>/scripts/session.py state --session ID`.
2. Confirm `phase plan` and `open none`. The phase is `probe` until `probe_concluded` exists;
   the probe is never skipped, and a plan authored without it has no measured starting point.
3. Read the probe's strands and summary from the session log: `state` carries derived
   position, not payloads. The probe's measurement is the pruning input for every decision
   below.

## The artifact

```json
{
  "nodes": [
    {"id": "counting", "title": "Entropy as counting", "summary": "Entropy counts the arrangements that look the same."},
    {"id": "second-law", "title": "Why entropy increases"}
  ],
  "edges": [
    {"from": "counting", "to": "second-law"}
  ]
}
```

| field | type | required | rule |
|---|---|---|---|
| `nodes[].id` | string | yes | matches `^[a-z0-9]+([_-][a-z0-9]+)*$` |
| `nodes[].title` | string | yes | short, non-empty; a label on the map, not a sentence |
| `nodes[].summary` | string | no | one line stating what the node asserts |
| `edges[].from` | string | yes | the prerequisite node id |
| `edges[].to` | string | yes | the node id that requires `from` |
| `edges` | array | yes | `from` is always the prerequisite; `to` always depends on it |

No other keys at any level. Ids are lowercase slugs; they are not graph node ids (`n_…`) and
never appear in the ledgers.

A node carries one claim the learner can hold. If you cannot state the node's claim in one
sentence, it is several nodes.

## Commit sequence

1. Write the plan to a scratch file outside `.learnharness/`, for example `plan.json`.
2. Run `python3 <skill>/scripts/plan.py validate --plan plan.json`.
3. Run `python3 <skill>/scripts/session.py plan-set --session ID --plan plan.json`.

`plan-set` validates again and refuses an invalid plan. A plan that is not recorded in a
`plan_set` event does not exist: the scratch file is not the record, and the session log is
the durable copy.

Success from `plan.py` is exit 0 with `{"ok":true,"nodeIds":[…],"warnings":[…]}`. Warnings do
not block.

## Refusals

`plan.py` and `plan-set` refuse with exit 1 and `{"ok":false,"error":…}`. A refusal writes
nothing.

| refusal | trigger | fix |
|---|---|---|
| empty plan | `nodes` is empty or missing | author at least one node |
| bad id | an id does not match `^[a-z0-9]+([_-][a-z0-9]+)*$` | rewrite the id as a lowercase slug |
| duplicate id | two nodes share an id | merge them or rename one |
| empty title | `title` is empty or missing | give the node a short label |
| unknown key | the plan, a node, or an edge carries a key not listed above | remove it; there are no extension fields |
| non-string summary | `summary` is present but is not a string | write it as one line of text, or omit it |
| unknown edge endpoint | `from` or `to` names no node | add the node or fix the reference |
| self-loop | `from` equals `to` | remove the edge |
| duplicate edge | the same `from`/`to` pair appears twice | keep one |
| cycle | the edges close a loop | break the loop by reordering the dependency |

`plan.py` collects every problem it finds and returns them all at once, one per line,
newline-joined in `error`. Read the whole list and fix all of them in one pass; re-running after
each single fix wastes the learner's time and can surface a later problem that changes the
shape of the plan.

`session.py check --node ID` also refuses an id that is not in the current plan. A node must
be recorded before any check can be tagged with it.

## Resolution

Two granularities are in play and they must not be confused:

| level | unit | owner |
|---|---|---|
| visible plan | node — a landmark on the map | this document |
| lesson | reasoning step — one move from something held to the next fact | `teach.md` |

The plan is a lower-resolution map than the reasoning-step path. One node may take one
teaching step or five. A node is not a step budget, and a step is not a node.

Rules:

- Do not let plan-node granularity leak into the lesson. Never teach a node title as if it
  were the next thing to say; the title tells you where the lesson is, not what the next move
  is.
- Do not split a node because a step ended, and do not merge nodes because a step covered
  two of them. Steps are evidence about the learner; nodes are structure.
- At the deepest level — the roots of the map — a node must be small enough to be taught in a
  single reasoning step from what the learner already holds. If a root needs several steps,
  it is not a root: split it and push the prerequisite below it.
- A root must be an unconditional truth for this learner, not a disguised theorem. A wrong
  root corrupts everything hung off it.
- Above the roots, a node may legitimately span several steps. That is the resolution
  difference, not an error.

## Pruning by what the probe measured

| probe assessment | plan treatment |
|---|---|
| holds | not a node; build above it without re-teaching |
| partial | a node at the boundary, or a node above it if the remainder is only fluency |
| missing | a node, at the depth the dependency requires |

- Anything the learner already holds is not a node. Re-teaching it is a cost with no return.
- Nothing off the path to the goal is a node, however interesting.
- The derivation to the goal is as short as the subject allows. Node count is not a quality
  metric; correct structure is.
- Prune above 15 nodes. Above 15 nodes `plan.py` warns and does not refuse — the limit is
  **advisory only**. Treat the warning as a prompt to re-check for re-taught material and
  off-path nodes, not as an instruction to compress.

## Render once

When the plan is built — and only then — present it in your reply as a markdown outline:

```
- counting — Entropy as counting
  - second-law — Why entropy increases
```

- One line per node, `id — title`, nested under its prerequisites. The nesting is the edge
  list flattened for reading; it is not a second artifact.
- No script renders this outline. It is prose in your message, and it is the learner's only
  view of the map.
- Present it once. Do not reprint it every step, and do not restate it in prose elsewhere —
  the teaching loop reads the plan; the learner does not need it repeated.
- On revision, report the change (added, removed, reordered) instead of reprinting the whole
  outline, unless the structure changed enough that the old outline is misleading.

## Exit condition

The plan phase ends at the first check tagged with a node id
(`session.py check --session ID --node ID …`), not at `plan-set`. Recording a plan does not by
itself leave the plan phase.

## Revision

Mid-session revision is allowed and expected.

- Call `plan-set` again. `session.py` assigns the next revision: 1 for the initial plan, 2, 3,
  … for revisions. The plan in force is the `plan_set` with the highest revision.
- Revise when a check shows a prerequisite is missing, when a node turns out to be already
  held, or when the goal moves.
- Never silently change course. Record the revision first, then say what changed and why. An
  unrecorded detour leaves the record claiming a map the lesson abandoned.
- Keep an id stable for as long as the node exists. Never reassign an id to a different node:
  earlier `check_posed` and `step_closed` events reference it.
- Do not drop a node that already has a `step_closed`. `verify.py` reports a `step_closed` for
  a node absent from the current plan. If the taught node was wrong, keep it and add the
  missing prerequisite rather than deleting the evidence.
- A revision may add, remove, or re-edge nodes. It may not be used to erase what was taught.
