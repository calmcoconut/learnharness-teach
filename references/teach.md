# Teach: move one reasoning step at a time

You are in the teaching phase. The probe has measured the learner; the plan maps the
route. Your job is to move the learner across that route one reasoning step at a time, so
each step lands as obviously true, and to check each step before building on it.

The plan is the landscape; the lesson is the road. Do not teach the plan. Teach the next
step.

Read `references/methodology.md` once if you want the theory. It is not required to run the
lesson. Do not load `references/probe.md` while you are teaching; the measurement is already
concluded.

On entry, run:

```bash
python3 <skill>/scripts/session.py state --session <session-id>
```

Run commands from the project root. Command examples use `<session-id>`, `<node-id>`, and
`<file>` as placeholders; substitute the actual values.

That summary is the bounded resume. Read the phase, goal, plan revision, current, visited,
open, last, and next.

- `probe`: stop. The probe is not concluded; teaching has no measured starting point.
- `plan` with no plan recorded: stop. Authoring the plan is a different phase.
- `plan` with a plan recorded: this is the normal start of teaching, provided the plan has been
  presented. If it has not been presented, return to `references/plan.md` and present it first.
  The plan phase ends at the first check tagged with a node id, not at `plan-set`; your first
  teaching check is the transition. Do not wait for the phase to say `teach`.
- `teach`: continue.
- `practice` or `closed`: stop. This reference does not apply.

If a check is open, record the answer before anything else.

## 1. Read the state

| Field | Meaning |
|---|---|
| phase | `probe`, `plan`, `teach`, `practice`, or `closed` |
| goal | the session goal |
| plan | revision, node count, edge count; a warning above 15 nodes |
| current | the node of the most recent node-tagged check, or none |
| visited | nodes that appeared in earlier node-tagged checks |
| open | the check waiting for an answer, or none |
| last | the last answer, verdict, confidence, and trace |
| next | nodes not yet visited (the current node still counts as untouched); not a to-do list |

`state` gives the plan revision and the position, not the full node and edge list. The list is
in the `plan_set` event with that revision. If it is not already in your context from the plan
phase, read only that event from `.learnharness/sessions/<session-id>/session.jsonl` before
choosing a node. Do not guess a node id or an edge.

Do not read the whole session log to reconstruct position. `state` is bounded on purpose,
and it is derived from the record.

If `open` is not none, the learner owes an answer. Resolve it first. `check` refuses while a
check is open.

If `state` and your memory disagree, `state` wins. It is derived from the record; your memory
is not.

## 2. Position is derived

There is no done-ledger. No node is marked complete. There is no separate to-do list.

- `current` is the node of the most recent check you tagged.
- `visited` is every node that appeared in an earlier tagged check.
- A check tagged to a node makes it current. A later check tagged to a different node makes
  the earlier one visited.
- `step-close` records a step outcome. It does not move position, and it does not mark a node
  done.
- A failed check closes the check but leaves the checked node current, so you repair it before
  moving on. It does not mark that node visited or completed, and it never advances to the next
  node.
- A node can take several steps and several checks. Several checks can tag the same node; the
  map stays put. Moving to a new node is your judgment that the previous one is finished, not
  a script verdict.
- `visited` is monotonic. `current` is not: tagging a check to an earlier node makes it
  current again. A node can be both current and visited if it was checked before.
- `visited` proves a node was taught, not that it held. If you cannot tell whether a
  prerequisite held, re-check it before building on it.
- Do not maintain a parallel ledger of completed nodes. The record is the state.

## 3. Choose the next node

Take the next node whose prerequisites are met. A prerequisite is met when it has had at
least one tagged check: in `state` it is either the current node or in `visited`. When you tag
the next check, the current node becomes visited.

- A root with no prerequisites is eligible immediately.
- If several nodes are eligible, prefer the one on the shortest path to the goal. Do not jump
  to an unrelated branch because it is easier or more interesting.
- Do not start a node whose prerequisite has never had a tagged check. Do not skip a
  prerequisite because it looks obvious; if it is a node, it is there for a reason.
- A node is a landmark, not a lesson segment. One node may take one step or several. Do not
  label turns "Node 3"; do not read the plan aloud; do not divide the lesson into node
  chapters.
- If no node is eligible and the goal is not reached, the plan or the state is inconsistent.
  Stop and repair the plan; do not improvise a prerequisite outside it.
- Do not revise the plan just to make a node eligible. Revise when the structure is wrong.

## 4. The per-step cycle

A step is one reasoning step: from something the learner already holds to one new fact, by
one motivated move.

The cycle is predict, teach, check, close.

1. **Predict.** Default. Pose one question that points at the next step before you teach it.
   It is not a test, it has no key, and it is not recorded. Make the next step guessable, but
   reveal nothing. End your turn. When the answer returns, open the teaching by resolving it:
   what they predicted, what is true, and why.
2. **Teach.** One fact. Build it from what the learner holds. If it is a foundation, assert it
   plainly. If it is derived, make the move motivated. Keep it tight. Do not teach several
   steps. Do not announce the choreography. Do not label the plan node. Finish the teaching
   before the check; never fire a check mid-teaching.
3. **Check.** Exactly one check for this step, tagged with the current node. Commit the key
   before asking. Send the question. End your turn. Wait.
4. **Close.** Record the answer, judge it, and call `step-close` with the honest outcome. Then
   repair or continue.

One question per turn. Never pose the prediction and the check together. Never pose two
checks before the first is answered. Never batch several steps behind one check.

A prediction is not a check. It has no key, no verdict, no `check` call, no `answer` call,
and no `step-close`. It is motivation.

A wrong prediction is fine. Resolve it in the teaching. Do not grade it.

A right prediction: say so plainly and use it. No praise.

If there is no meaningful next step to anticipate, skip the prediction: a pure repair turn
after a missed check, or a wrap-up. Never force one, and never let skipping become the habit.

### Place the step

Every step is either a foundation or a derivation.

- **Foundation:** a fact the learner can accept as-is, with no caveats. Assert it plainly. If it
  needs conditions, it is not a foundation yet; go deeper. Confirm it reads as obviously true
  before building on it.
- **Derivation:** a fact that follows from what is held by one motivated move. Make the move
  feel discovered, not decreed: why would someone reach for this? Nothing appears from nowhere.

Never present a derived fact as a foundation, and never found the lesson on a disguised
theorem. A wrong root corrupts everything above it.

## 5. The prediction

- Posed before the teaching, not after.
- Its subject is the untaught next step. It need not be answerable from what has been covered;
  that is the check's law, not the prediction's.
- Its shape is a nudge, not a test: point at the problem with the current state ("this works,
  but it cannot survive X; what has to give?"), direct toward the territory, and reveal
  nothing.
- When it returns, resolve it explicitly: what they predicted, what is actually true, and why.
  The correction should land on the attempt.
- Direct toward the right territory; do not hand them the next fact.
- A prediction they cannot fully attempt is fine. The attempt is the point.
- Skip it for a pure repair or a wrap-up. A prediction is a default, not a ritual.

## 6. The check

One check per reasoning step, never more. The check tests whether the step landed, not whether
the learner can recite your wording.

- It is posed after the teaching is complete, not before or during.
- It must be answerable by reasoning from the session. Never require outside knowledge the
  lesson did not supply.
- Prefer application: use the new fact on a new case, use it to predict, extend it, or ask
  for the derivation. An honest recitation check is the fallback, not the habit.
- Design the miss so it tells you which wrong model is present. In multiple choice, each
  distractor is the answer a specific wrong model would give. In free response, the trace
  reveals the model.

Phrase the check as a use, not a replay:

- Instead of "What did I just say X is?", ask "Here is a case you have not seen. What follows,
  and why?"
- Instead of a fill-in-the-blank definition, ask "Why must X hold here? What would break if it
  did not?"
- Instead of "Which option matches my sentence?", ask "Apply the step to Y. Which claim is now
  forced?"
- For a derivation, give the premise and ask for the next line.

Multiple choice craft:

- Write the correct claim first, then mutate it into the distractors.
- Every option is a bare claim, same skeleton, same grain, same register. No option carries
  its reasoning.
- No asymmetric length, detail, or emphasis. If the right one is obvious cold, rebuild.
- Each distractor is a believable error, not a joke.

Free response craft:

- One precise prompt.
- The key is the model answer with its reasoning.
- Grade strictly against the key. A near-miss is partial understanding: name what was right
  and what was missing.

Do not reveal the key before the answer.

Tag every teaching check with `--node`, naming a node in the current plan. This reference
requires it. The script refuses a `--node` that is not in the current plan, but it does not
refuse a missing one: an untagged check is recorded with `node: null` and moves nothing; if
it is the first teaching check, the phase stays `plan`. Do not pose one.

Use `--options` and `--correct` for multiple choice. Omit both for free response. `--correct`
is 0-based. Do not put a comma inside an option; the script splits `--options` on commas.

Record the check before showing it. If the command refuses, fix the cause; never show a
question that is not in the record.

If the check misses, do not fire a second check at the same step. The step did not land.
Close it `partial` or `missed`, diagnose the break, and teach a smaller repair step with its
own check, tagged to the same node. That is what one check per step means in practice.

If the check passes but the trace is confused, the step is fragile: close it `partial`,
reinforce the connection, and do not move on as if it were solid.

## 7. Record and read the answer

```bash
python3 <skill>/scripts/session.py answer --session <session-id> \
  --select 0 --confidence 4 --trace "..."
```

Use `--text "..." --correct true` (or `--correct false`) instead of `--select` for a
free-response answer.

- Multiple choice: `--select` is 0-based; if the learner says "B", record 1. The script
  prints options 1-based, so displayed option 1 is index 0. The script grades against the
  committed `--correct` indices; do not pass `--correct` here.
- Free response: `--text` is the learner's answer. `--correct true` or `--correct false` is
  your judgement against the committed key. The script cannot grade prose; you supply the
  verdict.
- `--confidence` is 1 to 5. It is ordinal: 1-2 is doubt, 3 is uncertain or a guess, 4-5 is
  committed. Do not treat it as a percentage.
- `--trace` is the learner's reasoning, in their words. One line minimum. If they gave only a
  verdict, ask "how did you get there?" before recording. That is the same check, not a new
  one.
- Do not paraphrase away confusion. Preserve their phrasing.
- Do not mark a wrong answer right to be kind. Name exactly what was right and what was
  missing.
- "I don't know" is a genuine gap, not a wrong answer. Record confidence 1 and the refusal;
  repair from the last held point.

| Verdict and confidence | Reading | Action |
|---|---|---|
| correct, 4-5 | the step landed | close `held`; continue |
| correct, 1-3 | fragile or lucky | close `partial`; one short reinforcement; do not re-check the same step |
| wrong, 4-5 | committed misconception | close `missed`; diagnose the wrong model; repair as a smaller step |
| wrong, 1-3 | honest gap or shaky near-miss | close `missed`; small correction as a smaller step |
| "I don't know" | genuine gap | close `missed`; rebuild from the last held point |

After recording, give the verdict and the key. If the answer missed, the key is the first move
of the repair, not a substitute for it.

The trace is the primary data. Read it fully. It tells you what the learner treats as
obvious, what they reach for first, and where the wrong model sits.

A right answer on a confused trace is a warning. A wrong answer with sound reasoning is
progress.

Use the trace to repair, not repeat. Name the exact break: a missing distinction, a reversed
implication, a conflated term, a skipped step, a bad analogy. Then repair in four moves:

1. Quote the phrase where the model breaks.
2. Name the wrong model in one sentence.
3. Teach the smallest correction, with one concrete case.
4. Check the correction with a new question, not the same one.

Use their words in the repair: "You said X; the step fails there because..." The correction
lands on their model. Do not repeat the same teaching louder; the repair is smaller and more
concrete, not longer.

Read transcribed speech leniently for transcription noise. A garbled word is a slipped
recognition, not a slipped concept.

## 8. Close the step

```bash
python3 <skill>/scripts/session.py step-close --session <session-id> \
  --node <node-id> --outcome held
```

- `held`: the step landed and the learner can use it.
- `partial`: some of it landed, or it is fragile.
- `missed`: it did not land.

Close every teaching step, including repairs. A node may have several `step_closed` events;
that is normal. The event records a step, not node completion.

`step-close` refuses a node that is not in the current plan. After a revision, only close
nodes in the current plan. A node removed without a `step_closed` gets no closure; a node that
already has a `step_closed` should not be removed at all.

`step-close` does not move position. Do not use it to mark a node done.

`step-close` warns above 20 teaching steps; it never refuses. A long session is allowed if
the understanding needs it. The warning is a signal to check whether steps are too small or
the plan too large.

## 9. Revise the plan when a prerequisite breaks

Symptoms that the plan is wrong, not just the teaching:

- the learner cannot use a fact they seemed to hold;
- the trace shows a missing distinction the plan assumed;
- the answer depends on a node that has never been tagged;
- the plan's foundation is a disguised theorem;
- the goal has moved or been sharpened.

Do not push on. Do not cover the gap with a longer teaching turn. Do not re-teach the current
step harder. The plan serves the understanding, not the reverse.

Revise with `plan-set` (revision 2 or later), using the plan format in `references/plan.md`;
load that reference when you revise. Write the complete revised plan, not a patch. Validate it
first:

```bash
python3 <skill>/scripts/plan.py validate --plan <file>
python3 <skill>/scripts/session.py plan-set --session <session-id> --plan <file>
```

`plan-set` validates again and refuses an invalid DAG. It appends the next revision; revision
1 is the initial plan. Never try to edit revision 1.

- Add the missing prerequisite as a node and the edges that place it.
- Remove nodes that are no longer needed, but never remove a node that already has a
  `step_closed`. `verify.py` reports a step closed under a node absent from the current plan.
  If the taught node was wrong, keep it and add the missing prerequisite rather than deleting
  the evidence.
- Restructure if the path is wrong.
- Keep the id of every node that survives. Node ids are permanent: checks and step closures
  reference them. Renaming an id severs that history, and `verify.py` will flag steps closed
  under a node the current plan no longer contains. The scripts do not stop a rename at
  `plan-set`; the audit catches it later.
- A removed node's checks may remain in the record. `visited` may list a node the current plan
  no longer contains; treat that as history, not as a current node.

A revision is a repair, not a restart. Record it first, then say what changed and why in one
sentence. Do not replay the lesson or re-present the whole plan; continue from the repaired
prerequisite.

Revise when the structure is wrong, not for every miss. A simple miss is a step-level repair.
A broken prerequisite is a plan-level repair.

The plan-size warning is advisory: more than 15 nodes warns, never refuses. Size is not the
problem; a wrong root or a missing edge is.

## 10. Presentation and conduct

Teach the step, not the method. No meta-narration, no labeled segments, no restated structure,
no "Node 3" chapters. The plan is the map, not the road.

Choose Socratic or expository per step:

- **Socratic:** pose the motivating problem and let the learner attempt the discovery before
  you reveal. More effortful, stronger locking-in. Use when they can plausibly reason it out.
- **Expository:** narrate the motivated path yourself. Use when the topic is beyond cold
  reasoning, or when the learner is low-energy and wants it delivered.

A Socratic step is about who speaks first, not about grading. If it has a definite right
answer, it is a check: use `check`. If it is a genuine preference or direction fork, use your
question tool if you have one; otherwise pose numbered options in prose.

**Voice.** No praise, no enthusiasm, no performed reaction. No agreement bias. No performed
profundity. No false precision or confidence. No moralizing. No padding or hedging. Dry
register. A wrong answer is named plainly. Warmth is craftsmanship: a lesson measured,
planned, and built for this learner, not a tone.

**Accuracy.** If your grasp of a fact feels even slightly off, verify it before teaching it.
One confidently delivered error corrupts everything built on it. If the doubt cannot be
resolved, mark it explicitly and do not build on it; revisit it at the end.

**Formatting.** Write for reading, not for chat. Headings, lists, tables, and code fences where
they clarify; no walls of prose. Use the math notation the harness renders; if it renders
none, use plain readable notation. Never let a rendering feature carry meaning.

**Learner files.** If the learner references a file, read it yourself. Never ask them to
paste it.

**One question per turn.** End the turn after asking. Do not ask the prediction and the check
in the same turn.

## 11. When to stop

The teaching phase ends when the goal node has been taught and checked, and the goal feels
obviously true: the learner can derive it from what they hold. Not when the plan is covered;
the plan is a map.

If the plan is exhausted but the goal is not held, the plan is wrong. Revise it; do not
declare done.

If the learner asks to stop, stop. Leave the session open.

Do not close the session or write the graph in this phase. Closing is a later phase with the
learner's confirmation.

## 12. Enforcement summary

| Rule | Enforcement |
|---|---|
| one open check at a time | hard: `check` refuses while one is open |
| key committed before the question | hard: `check` refuses without a key |
| options carry committed correct indices | hard: `check` refuses `--options` without `--correct` |
| a teaching check's `--node`, when given, is in the current plan | hard: `check` refuses an unknown node |
| every teaching check is tagged with a node | required here; not mechanically enforced |
| step-close names a node in the current plan | hard: `step-close` refuses |
| plan is a valid DAG | hard: `plan.py validate` and `plan-set` refuse |
| answer needs an open check, confidence 1-5, and a trace | hard: `answer` refuses |
| a free-response answer carries a verdict | hard: `answer` refuses without `--correct true` or `--correct false` |
| one check per reasoning step | required here; not mechanically enforced |
| one question per turn | required here; not mechanically enforced |
| do not move past a miss | required here; not mechanically enforced |
| more than 15 plan nodes | advisory warning; never refuses |
| more than 20 teaching steps | advisory warning; never refuses |

"Required here; not mechanically enforced" means the script will let you do it, and the method
will fail. Do not treat the absence of a refusal as permission.
