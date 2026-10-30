---
name: learnharness-teach
description: Teach a learner a subject using measured understanding rather than assumption — probe where their understanding actually ends, plan a dependency map from there to the goal, teach one reasoning step at a time with exactly one check per step, run separate practice sessions drawn from what was established, and close by recording propositions and reasoning chains into a durable knowledge graph. Use when someone wants to genuinely understand a topic rather than be told about it.
license: AGPL-3.0-only
compatibility: Python 3.10+ (standard library only). Needs a harness that can read and write files, run python3, and ask the user a question. No network access, no API keys, no running app.
---

# LearnHarness Teach

Teach one learner one subject, in their own working directory, using files as the
record. The learner's understanding is measured before anything is taught, and what
they establish is written to a knowledge graph that survives the session.

## Check the basics first

1. Run `python3 --version`. If Python 3.10 or newer is not available, stop and say so
   plainly: the scripts are the product, and without them nothing below is enforceable.
   Do not attempt a degraded prose-only version.
2. Find the record. It lives at `.learnharness/` in the project root. If it does not
   exist yet, `session.py init` creates it.

Every command below is run from the project root as `python3 <skill>/scripts/<name>.py`.
Substitute the skill's own directory for `<skill>`; never assume the current directory.

## The record

```
.learnharness/
├── graph/nodes.jsonl          propositions
├── graph/chains.jsonl         reasoning chains: premises → conclusion
├── graph/format.json          {"version": 1, "writer": "learnharness-teach/0.1"}
└── sessions/<id>/session.jsonl   the canonical session log
    sessions/<id>/session.md      generated readable view
```

`session.jsonl` is append-only and is the only source of truth. Phase and plan
position are **derived** from it, never stored. There is no done-ledger.

The full field-by-field contract is in `references/data-format.md`. Read it once, at
the start of your first session in a project.

## The loop

A teaching session runs four phases, then optionally closes. A practice session runs
only practice, then optionally closes.

Work one phase at a time and load that phase's reference when you enter it.

### 1. Probe — measure where understanding ends

Load `references/probe.md`. Do not load `references/teach.md` or `references/plan.md`.

Start: `python3 <skill>/scripts/session.py init --goal "<the learner's goal>"`

Ask one question at a time, covering each dependency strand the goal needs. For every
question, record it **before** asking it, with the answer key committed:

```
python3 <skill>/scripts/session.py check --session <id> \
  --question "…" --key "…" [--options "a,b,c"] [--correct 0]
```

Then record the learner's answer with their confidence and their reasoning.

For a check posed with `--options`, select the option indices:

```
python3 <skill>/scripts/session.py answer --session <id> \
  --select 0 --confidence 4 --trace "…"
```

For a free-recall check posed with `--key` and no `--options`, give the learner's words and
your judgement against the committed key:

```
python3 <skill>/scripts/session.py answer --session <id> \
  --text "<the learner's words>" --correct true --confidence 4 --trace "…"
```

Finish with a per-strand assessment:

```
python3 <skill>/scripts/session.py conclude-probe --session <id> \
  --strands <file.json> [--summary "…"]
```

You have no plan during this phase and no plan node ids. Do not speculate about the
lesson, and do not teach. You are measuring.

### 2. Plan — map the path from measured to goal

Load `references/plan.md`.

Author a node/edge list to a file, validate it, then record it:

```
python3 <skill>/scripts/plan.py validate --plan <file>
python3 <skill>/scripts/session.py plan-set --session <id> --plan <file>
```

Every node must be something the probe did not show they already hold. Render the plan
to the learner once, as a markdown outline, and then stop reprinting it.

### 3. Teach — one reasoning step at a time

Load `references/teach.md`. Do not load `references/probe.md`.

Read `python3 <skill>/scripts/session.py state --session <id>` to see the current node.
For each step: elicit a prediction, give the explanation that makes the step feel
obvious, then run exactly **one** check, tagged with the node:

```
python3 <skill>/scripts/session.py check --session <id> --node <node-id> …
python3 <skill>/scripts/session.py answer --session <id> …
python3 <skill>/scripts/session.py step-close --session <id> --node <node-id> --outcome held
```

Never pose two checks before the first is answered. Never batch several reasoning steps
behind one check. A failed check leaves the node current so you repair it before moving on:
it does not mark the node visited or completed, and it never advances to the next node.
Position is derived from the checks that actually happened.

If a check shows a prerequisite is broken, revise the plan with `plan-set` (revision 2+)
instead of pushing on.

### 4. Practice — make it usable

Load `references/practice.md`. Practice is its own session:

```
python3 <skill>/scripts/session.py init --kind practice --goal "…"
```

Sample material from the graph (`graph.py propositions`, `graph.py chains --node <id>`),
falling back to the last session's plan when the graph is empty. Commit the model
solution before the learner works:

```
python3 <skill>/scripts/session.py practice-problem --session <id> --problem <file>
python3 <skill>/scripts/session.py practice-concluded --session <id> --result <file>
```

Practice sessions write **no** propositions.

### 5. Close — record what was established

Ask the learner whether to close. If they decline, stop; the session stays open and
nothing is written to the graph.

If they confirm, load `references/graph.md` and run close **in a fresh invocation whose
only input is the session log**. Read `session.py state` and `session.py render --no-plan`.
Do not read the plan: extraction is tree-blind, because the plan records what you intended
to teach and the graph must record what the learner actually established.

Write proposals to a file and merge, then audit and report:

```
python3 <skill>/scripts/graph_write.py merge --session <id> --proposals <file>
python3 <skill>/scripts/verify.py --session <id>
```

To make the graph visible in the LearnHarness app:
`python3 <skill>/scripts/graph.py export --to <app-data-dir>`.

## Resuming

Read `python3 <skill>/scripts/session.py state --session <id>`. That summary is bounded
on purpose. Do not read the whole log — there is no compaction here, and the log is not
the context you want.

## Asking the learner

Use your harness's question tool when it has one; otherwise pose numbered options in
prose. Never assume a particular tool name — the four common ones are `AskUserQuestion`,
`request_user_input`, `ask_user`, and `ask_question`, but any way of asking and
receiving an answer is fine.

Ask one question at a time. Always ask for a confidence from 1 to 5 and for a short
reasoning trace: "how did you get there?" The trace is the primary data. A correct
answer with no trace teaches you almost nothing.

## Rules the scripts enforce

These are refused, not advised. Do not fight them; they protect the method.

| Rule | Refused by |
|---|---|
| One open check at a time | `check`, `conclude-probe` |
| A check cannot be posed without its key already committed | `check` |
| A check may not name a node that is not in the current plan | `check` |
| The plan must be a valid DAG — no cycles, dangling edges, duplicate ids, self-loops | `plan.py` |
| The probe concludes exactly once | `conclude-probe` |
| A session closes once | `close` |
| The graph format version must be one this skill understands | every graph command |

## Rules that are advisory

Warned, never refused. Use judgement.

- More than 8 probe strands, 15 plan nodes, or 20 teaching steps.
- Every teaching check should carry `--node`. Tagging is required by `references/teach.md`
  but is not refused, because a check posed before a plan exists has no node to name. An
  untagged check still records an answer, but it moves no position.
- Anything about how long an explanation should be.

## What not to do

- Do not skip the probe. Teaching without measuring is a different product.
- Do not teach before the probe concludes.
- Do not reveal an answer key before the learner answers.
- Do not record a check you did not actually ask, or an answer you did not actually get.
- Do not rewrite `session.jsonl`. It is append-only.
- Do not write outside `.learnharness/`.
- Do not invent node or chain ids; `graph_write.py` mints them from the statement.
- Do not emit a chain before the nodes it connects.
- Do not create `sessions.jsonl` or `coverage.jsonl` — those are the app's bookkeeping
  for its own chats, and these sessions have no chat to fold.
- Do not let plan-node granularity leak into the lesson. A node is a map unit; the
  lesson moves one reasoning step at a time.

## References

Load only what the current phase needs.

| File | When |
|---|---|
| `references/probe.md` | probe phase only |
| `references/plan.md` | plan phase, and when revising mid-session |
| `references/teach.md` | teaching phase only |
| `references/practice.md` | practice sessions |
| `references/graph.md` | closing a session |
| `references/data-format.md` | first session in a project, and whenever a field name matters |
| `references/methodology.md` | when the reasoning behind the method matters, or the learner asks why |
