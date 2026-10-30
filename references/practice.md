# Practice

Practice is its own session kind, not a phase of a teach session. It exercises propositions the
learner already holds. It does not establish new ones.

## The session kind

```
python3 <skill>/scripts/session.py init --goal TEXT --kind practice
```

- A practice session **writes no propositions**. It records `practice_problem` and
  `practice_concluded` events and nothing else. It never appends to `nodes.jsonl` or
  `chains.jsonl`.
- It is not extracted at close: there is nothing to audit and nothing to merge (see
  `references/graph.md`). A practice session contributes nothing to the graph.
- `practice-problem` and `practice-concluded` are practice-kind only; they refuse on a teach
  session. Practice events never appear in a teach session, and teach events never appear in a
  practice session.
- Why the split: the graph records what was established under instruction. Practice measures
  what the learner can produce unaided. Writing practice output into the graph would let a
  drill masquerade as evidence of understanding.

## Material

**Primary source: the knowledge graph.**

| command | use |
|---|---|
| `python3 <skill>/scripts/graph.py propositions` | the propositions available to target |
| `python3 <skill>/scripts/graph.py chains --node ID` | chains containing a node — the material for composition problems |
| `python3 <skill>/scripts/graph.py find QUERY` | substring search; `*` is the only wildcard |
| `python3 <skill>/scripts/graph.py sessions` | which sessions contributed what, when you need the birth context |

**Fallback when the graph is empty: the most recent session's plan.**

1. `python3 <skill>/scripts/session.py list` — find the most recent teach session.
2. Read its plan: `python3 <skill>/scripts/session.py render --session ID` (or the `session.md`
   already written), or read the latest `plan_set` event in the session log.
3. Use the plan's node ids and titles as targets, and its edges as the chain structure.

The id space recorded in `practice_problem.target` follows the source: graph node ids when the
material came from the graph, plan node ids when it came from the plan fallback.

If the graph is empty and no teach session exists, there is no material. Say so and stop. Do not
invent a syllabus — practice on material the learner was never taught is a teaching session in
disguise, and a bad one.

## What a problem must do

- **Require the right knowledge to come to mind without naming it.** The statement never
  announces its target. If the situation makes the applicable proposition unmistakable, that is
  a deliberate low-difficulty recall problem, not an accident.
- **Be solvable from the material and nothing beyond it.** No requirement the learner has not
  met.
- **Be solved, then shortcut-hunted, before it is posed.** A problem solvable by a route that
  skips the target teaches that route instead; fix it or discard it.
- **Vary.** Different target, different surface, or different mode from the previous problem.
  Never a block of same-target problems in the same shape — that is repetition, not retrieval.
  Spread targets across the session, weakest and most-served first.
- **Be short enough to be about retrieval.** Density beats length: decision points where a
  not-yet-active proposition must be chosen, not pages of search.

## The three modes

| mode | what it trains | shape | difficulty knob |
|---|---|---|---|
| `recall` | the proposition deploys from a weak or unfamiliar cue | one or two decision points, a situation class not yet used for this target, short | cue distance |
| `discrimination` | the right proposition wins against a live confusable | near-twin situations where the separating feature carries all the signal | surface similarity |
| `composition` | the chain runs as a held whole under load | length follows the chain, decision points at the junctions, distractors present | length and interference |

Order matters: recall before discrimination before composition. What cannot be retrieved cannot
be discriminated, and steps that do not come to mind cannot be composed. When a later layer
fails, suspect the earlier one and drop back to test it.

## Commit the model solution first

The model solution is committed **before the learner works**. It is the practice analogue of the
pre-committed answer key: a solution authored after seeing the attempt is a verdict fitted to the
answer.

1. Write the problem to a scratch file outside `.learnharness/`, for example `problem.json`:

```json
{
  "statement": "A gas expands into a vacuum inside an insulated box. Does its entropy change, and why?",
  "mode": "recall",
  "target": ["n_a1b2c3d4e5f6"],
  "modelSolution": "1. The box is insulated, so Q = 0. 2. No work is done against anything (free expansion), so W = 0. 3. ΔU = 0, so T is unchanged. 4. Entropy counts arrangements: the gas now has access to more microstates, so S increases."
}
```

2. Record it, then show the statement:

```
python3 <skill>/scripts/session.py practice-problem --session ID --problem problem.json
```

- `statement` is self-contained, exactly as the learner will see it (treat the displayed text as
  the record).
- `modelSolution` is complete, with the moves in order. It is revealed at conclusion and never
  re-authored: revising it after the attempt destroys the only honest record of what you
  expected.
- `target` names the ids the problem exercises — graph node ids, or plan node ids from the
  fallback.
- The learner does not see the statement until the event is recorded.

## Hints

The rung ladder, least to most revealing. One line each:

| rung | name | what you do |
|---|---|---|
| `R0` | attention redirect | point the learner back at a specific given or clause they already have. Zero informational cost. |
| `R1` | pattern re-description | restate the shape of the problem without naming the relevant proposition. |
| `R2` | candidate class | name the kind of thing that applies, not the thing itself. |
| `R3` | proposition named | state the proposition that applies, without applying it. |
| `R4` | move outlined | sketch the step, without executing it. |
| `R5` | worked step | perform the step for them. |

`rung: null` means **the learner needed no hint at all**. `null` is not `R0` and must never be
used to mean "hinted at zero cost". `R0` is a real hint — a redirect — and it is recorded as
`R0`.

Rules:

- **Escalate one rung at a time, and only on evidence the learner is actually stuck.** Never
  pre-emptively: difficulty is the point, and help given before the struggle removes the
  retrieval that the problem exists to produce. Never two rungs at once.
- Evidence of being stuck is in the response, not in the clock:
  - the trace shows the first question in the loop the learner cannot answer, or has answered
    wrongly — respond to exactly that question, at the coarsest grain that unblocks;
  - a bare "I'm stuck" with no trace gives nothing to diagnose, so start at `R0`;
  - a wrong claimed answer is localised first: name the first break, then give the smallest
    nudge that lets the learner make the next move, and wait.
- **Statement repair is free.** "I don't understand what is being asked" is a parse failure, not
  a stall on the material: repair the statement fully and immediately, and do not count it as a
  rung. Solution information is metered; wording is not.
- When a nudge does not land, reassess where the learner is stuck and offer only the next
  necessary piece. Never jump to the full solution.
- Record the highest rung the problem needed in `rung`. A problem that needed `R0`–`R1` was
  about right; `R3` and above means it was over the edge, and the next problem on that target
  comes down a notch.

## Concluding a problem

Conclude when the learner has solved it correctly or explicitly asks to end it. Never infer
permission to end from mistakes, elapsed time, attempts, or frustration. A claimed answer is not
a progress signal: the learner's reasoning is the evidence, and a wrong claim is worked through,
not concluded.

Write the result to a file and record it:

```json
{
  "outcome": "solvedWithHints",
  "verdict": "Retrieved the counting picture, but did not connect it to the free expansion until R2.",
  "rung": "R2",
  "missClass": "cue",
  "retest": true
}
```

```
python3 <skill>/scripts/session.py practice-concluded --session ID --result result.json
```

All five fields are required. `rung` and `missClass` are nullable: pass `null` when nothing
applies and the event records the absence rather than a value. `null` is a legitimate recorded
answer, not a gap to be filled with a guess — inventing a rung or a class corrupts the one
signal that sets the next problem's difficulty. When you record `null`, say why in the verdict.

### `outcome`

| value | when |
|---|---|
| `solved` | correct, unaided; `rung` is `null` |
| `solvedWithHints` | correct after at least one hint; `rung` is the highest rung used |
| `movedOn` | the learner ended the problem unfinished, by their own pacing decision rather than defeat |
| `surrendered` | the learner could not proceed and stopped without solving |
| `dismissed` | the learner skipped or declined the problem without working it |

`movedOn` is a pacing decision; `surrendered` is a capability signal. Do not record one as the
other.

### `verdict`

Free text. Name the load-bearing moves the learner made and the first place it broke. On a wrong
answer, localise the break — the correction itself is the model solution's reveal, not the
verdict's. Do not soften a wrong verdict or inflate a right one; calibration is a product of the
record, and a kind verdict destroys it.

### `missClass`

Classify every miss. The classification exists to change the next problem, so record the
observation that licenses it.

| value | what licenses it | what it changes about the next problem |
|---|---|---|
| `cue` | nothing came to mind: the trace shows searching, or the learner says they do not know; the proposition was absent, not wrong | same target, shorter cue distance and an easier situation class, stay in `recall`, do not raise difficulty, fresh surface |
| `discrimination` | the wrong candidate won: a specific confusable proposition was retrieved and used, or two were mixed | same target against that same confusable, `discrimination` mode, closer surface similarity, then re-test in `recall` |
| `execution` | the right proposition was chosen but run wrong: algebra, order, units, sign, or a step applied backwards | same proposition with the run as the demand — `composition`, or a shorter execution-focused item; lower interference; do not re-teach the proposition |
| `careless` | the trace is correct and the final answer contradicts it, or the learner corrects themselves on rereading | same difficulty, different surface, keep the demand; add the check-your-work expectation to the verdict, not to the problem. Do not lower difficulty |
| `structural` | the trace is coherent but rests on a false claim: the retrieved proposition itself is wrong | stop raising difficulty; drop back to `recall` on the premise underneath it, and mark the misconception for surgical repair. This is the one class that indicates a teaching failure, not a practice failure |
| `null` | there was no miss (a clean solve) | nothing; keep the difficulty or raise it one notch on this target |

Two misses in a row on the same target, both concluded: switch targets for the next problem.
Difficulty is adjusted in one notch at a time — up after a clean solve, hold after a
hints-assisted solve, down after a miss.

### `retest`

`true` marks the problem for a fresh-surface retest before the session ends. Set it for every
miss, every hints-assisted solve, and every surrendered problem. Set it `false` only for a clean
unaided solve. A retest never reuses the original surface, and a retest that also fails carries
`retest: true` again.

## Dismissal

If the learner dismisses a problem — skips it, declines it, or asks to drop it — record it as
`dismissed`. Do not silently drop it: an unrecorded problem leaves the record describing a
session that did not happen.

- `outcome: "dismissed"`, `rung: null`, `missClass: null`, `retest: false`.
- The verdict states why, in one line.
- Do not re-pose the same problem. Its target stays unexercised and belongs in a later problem
  in a different surface.
- A dismissal is not evidence about the learner. Do not let it lower the difficulty of the next
  problem, and do not treat it as a miss.

## Session flow

1. `session.py init --goal TEXT --kind practice`.
2. Load material: graph first, plan fallback.
3. Per problem: choose target, mode, and difficulty; commit the model solution; pose.
4. Per response: diagnose, hint one rung at a time, or work the wrong answer through.
5. Conclude: outcome, verdict, rung, missClass, retest.
6. Before ending: retest every miss, hint-heavy item, and surrender in a fresh surface.
7. `session.py close --session ID`. It writes no propositions; the practice record is the
   session log alone.
