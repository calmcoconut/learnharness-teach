# Golden transcript rubric

No script test can tell whether a prompt edit made the teaching better or merely
different. This rubric is the judgement layer: a human reads a transcript, scores each
criterion, and records failures.

Use it two ways:

- **Regression** — re-run a recorded session after changing `SKILL.md` or a reference, and
  compare against `teach-session.md`. Any criterion that was passing and now fails is a
  regression, regardless of how much better the prose reads.
- **Adjudication** — when two transcripts disagree, this decides which one is correct.

Score each criterion **pass / partial / fail** and quote the line that decides it. Do not
score a criterion you cannot point at.

---

## Phase discipline

| # | Criterion | Fails when |
|---|---|---|
| D1 | The session starts with a probe, never with an explanation | the first substantive message teaches |
| D2 | `references/probe.md` is not loaded during teaching, and `teach.md` is not loaded during the probe | both phases' vocabulary appears in one turn |
| D3 | The plan phase begins only after `conclude-probe` succeeds | a plan is authored mid-probe |
| D4 | Teaching begins while `state` still reports phase `plan`, and the first node-tagged check moves it to `teach` | the agent stalls waiting for a `teach` phase that has not happened |
| D5 | Close is offered, not assumed | the graph is written without the learner agreeing |

## Probe

| # | Criterion | Fails when |
|---|---|---|
| P1 | One question at a time | two questions in one turn |
| P2 | The check is recorded **before** the question is visible, so `state` shows it open while the learner is answering | the question is asked first and recorded after |
| P3 | Each strand the goal depends on is probed, and the probe stops when it knows enough | the probe continues past the point of knowing, or skips a strand |
| P4 | The answer key is never visible before the answer | the key leaks into the question text |
| P5 | The learner's reasoning trace is asked for, and a correct answer with a confused trace is treated as not held | a bare "correct" is accepted as evidence of understanding |
| P6 | The probe does not teach, hint, or anticipate the lesson | the agent explains while measuring |
| P7 | The conclusion names per-strand assessments, not a single score | `conclude-probe` is called with one vague strand |
| P8 | After the answer, the verdict and key are stated in a sentence or two and the probe does not become a lesson | the correction turns into a mini-lecture |

## Plan

| # | Criterion | Fails when |
|---|---|---|
| N1 | Every node is something the probe did **not** show the learner already holds | a node restates a held proposition |
| N2 | The plan is validated before it is recorded | `plan-set` is attempted with an unvalidated document |
| N3 | Prerequisite edges point from prerequisite to dependent, and the graph is acyclic | edges are reversed or cyclic |
| N4 | The deepest nodes are single reasoning steps; upper nodes may span several | a leaf node is itself a multi-step argument |
| N5 | The plan is rendered once, as an outline | the plan is reprinted every turn, or never shown |
| N6 | Node granularity does not leak into the lesson | the agent teaches "a node" as a chunk rather than one reasoning step |

## Teach

| # | Criterion | Fails when |
|---|---|---|
| T1 | Exactly one check per reasoning step | several steps are taught and then checked once |
| T2 | Each check is tagged with the plan node it belongs to | the check carries no `--node` |
| T3 | The step follows predict → explain → check | the explanation arrives with no elicitation |
| T4 | The explanation makes the step feel obvious from something already held, rather than asserting it | the step is justified by appeal to authority or by "it follows from the maths" |
| T5 | A failed check is repaired as a smaller step with its own check, never re-asked identically | the same question is posed again |
| T6 | A failed check leaves the node current for repair and never advances to the next node | `step-close --outcome held` is recorded for a step the learner did not get, or position moves past the failed node |
| T7 | A broken prerequisite triggers a `plan-set` revision rather than pushing on | the agent continues past a revealed gap |
| T8 | Steps are closed with an honest outcome | every step is `held` |

## Practice

| # | Criterion | Fails when |
|---|---|---|
| R1 | Practice is its own session, and writes no propositions | propositions are written from a practice session |
| R2 | The model solution is committed before the learner works | the solution is produced after seeing the attempt |
| R3 | The problem requires the knowledge to come to mind without being named first | the problem names the proposition it is testing |
| R4 | Hints escalate one rung at a time, only on evidence of being stuck | a hint is offered pre-emptively, or two rungs at once |
| R5 | `missClass` is a real classification with a consequence, not a label | every miss is classified `execution`, or the next problem ignores the classification |

## Close

| # | Criterion | Fails when |
|---|---|---|
| C1 | Close runs in a fresh invocation whose input is the session log | the closing turn has the plan in context |
| C2 | Every extracted proposition is something the learner actually established, not something the agent said | a merely-mentioned idea becomes a node |
| C3 | Every chain's premises and conclusion resolve to nodes that exist | a chain is written to a node that was not created |
| C4 | `verify.py` is run and its findings are reported | close ends without an audit |
| C5 | The learner is told what was recorded, in counts and in substance | close ends silently |

---

## Recording a run

Append one row per transcript to the table below. A transcript that fails any criterion
marked **critical** (D1, P2, P4, T2, T6, C1, C2) is not a passing run regardless of the
rest.

| Date | Reference changed | Harness | Critical failures | Other failures | Verdict |
|---|---|---|---|---|---|
| — | baseline `teach-session.md` | — | — | — | reference |

---

## What this rubric deliberately does not score

- **Model quality.** Whether an explanation was good is not the same question as whether
  the protocol was followed. Judge the protocol here; judge the teaching in review.
- **Prose style.** Verbosity is a separate concern, and `SKILL.md` already says brevity
  over performing the method.
- **Whether the learner learned.** That is what the checks are for, and scoring it here
  would mean scoring the learner rather than the skill.
