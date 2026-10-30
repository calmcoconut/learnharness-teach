# Golden transcript — one complete teaching session

The reference behaviour for a teach session. Score a candidate transcript against
[`rubric.md`](rubric.md), not against the wording here: the commands and their ordering are
normative, the prose is not.

Learner's opening line:

> Teach me why entropy always increases. I've done some statistical mechanics.

---

## Probe

Agent loads `references/probe.md`. It does not load `teach.md` or `plan.md`.

**Agent**

> Before I teach anything I want to find where your understanding actually ends, because
> what I explain depends on that. Three or four questions, one at a time, and I'd like a
> sentence on how you got to each answer plus how confident you feel, 1 to 5.

Records the check, then asks:

```bash
python3 scripts/session.py check --session lh_a1b2c3d4 \
  --question "A fair coin is flipped 100 times. Which total is more likely: 50 heads, or 60 heads? Why?" \
  --options-file opts-q1.json --correct 0 \
  --key "50 heads. More arrangements give 50 than 60, so it has more microstates. 'More likely' and 'more arrangements' are the same statement."
```

```text
posed check 2
question: A fair coin is flipped 100 times. Which total is more likely: 50 heads, or 60 heads? Why?
1. 50 heads, because more arrangements give it
2. 60 heads, because it is further from the average
3. They are equally likely
```

**Learner**

> 1. There are more ways to get 50, so it has to be more likely. Confidence 4. I'm thinking
> of it as counting arrangements.

```bash
python3 scripts/session.py answer --session lh_a1b2c3d4 \
  --select 0 --confidence 4 --trace "more ways to get 50, counting arrangements"
```

**Agent** — states the verdict in one sentence, does not teach:

> Right, and for the right reason. *Strand: counting — holds.*

---

**Agent**

> Next: what makes a process irreversible?

```bash
python3 scripts/session.py check --session lh_a1b2c3d4 \
  --question "In your own words, what makes a process irreversible?" \
  --key "The reverse would need a rearrangement so improbable it never happens on any timescale we observe. 'Cannot be undone' is not the reason; improbability is."
```

**Learner**

> It can't be undone. Confidence 2. I know the word but I don't really know what makes it true.

```bash
python3 scripts/session.py answer --session lh_a1b2c3d4 \
  --text "It can't be undone." --correct false --confidence 2 \
  --trace "I know the word but not what makes it true"
```

**Agent** — verdict plus key, one sentence each, no lesson:

> That's the definition restated, not the reason. The reason is that the reverse would need
> the pieces to land in a specific arrangement, and there are vastly fewer of those.
> *Strand: irreversibility — not held.*

---

**Agent**

> One more: what is equilibrium, to you?

```bash
python3 scripts/session.py check --session lh_a1b2c3d4 \
  --question "What is equilibrium, in terms of arrangements?" \
  --key "The macrostate with overwhelmingly more microstates than any other, so it is where a closed system spends essentially all its time."
```

**Learner**

> The state it settles into. Confidence 3. I think that means the most likely one but I haven't connected those.

```bash
python3 scripts/session.py answer --session lh_a1b2c3d4 \
  --text "The state it settles into — I think that means the most likely one, but I have not connected those." \
  --correct true --confidence 3 --trace "settles into the most likely state, not sure why"
```

**Agent** — concludes the probe. It has enough.

```bash
python3 scripts/session.py conclude-probe --session lh_a1b2c3d4 --strands strands.json \
  --summary "Counting is solid and can be used without scaffolding. Irreversibility is a word with no mechanism behind it. Equilibrium is half-connected to likelihood."
```

```json
[
  {"strand": "entropy as counting", "assessment": "holds; reasons with multiplicity unprompted"},
  {"strand": "irreversibility", "assessment": "not held; can restate the definition, cannot say what makes a direction one-way"},
  {"strand": "equilibrium as likelihood", "assessment": "partial; knows it is the settling state, has not connected it to counting"}
]
```

---

## Plan

Agent loads `references/plan.md`. Phase is still `plan` — teaching starts from here.

```bash
python3 scripts/plan.py validate --plan plan.json
```

```json
{
  "nodes": [
    {"id": "counting", "title": "Entropy counts arrangements"},
    {"id": "improbability", "title": "Why the reverse is improbable"},
    {"id": "direction", "title": "Where the arrow comes from"},
    {"id": "second-law", "title": "The second law"},
    {"id": "equilibrium", "title": "Equilibrium as the likeliest state"}
  ],
  "edges": [
    {"from": "counting", "to": "improbability"},
    {"from": "improbability", "to": "direction"},
    {"from": "direction", "to": "second-law"},
    {"from": "direction", "to": "equilibrium"}
  ]
}
```

```bash
python3 scripts/session.py plan-set --session lh_a1b2c3d4 --plan plan.json
```

**Agent** — renders the outline once:

> Here's the route. You already hold the first box, so we start at the second.
>
> ```
> [x] Entropy counts arrangements
>  └─ [ ] Why the reverse is improbable
>      └─ [ ] Where the arrow comes from
>          ├─ [ ] The second law
>          └─ [ ] Equilibrium as the likeliest state
> ```

---

## Teach

Agent loads `references/teach.md`. First step: `improbability`.

**Agent**

> Before I explain: a video plays backwards and shows a shattered glass reassembling.
> Which direction is impossible, and what would have to happen for the other one?

**Learner**

> Reassembling is impossible. It would need every piece to land back in place.

**Agent**

> Exactly — and now say it in the language you already have. You told me 50 heads is likelier
> because more arrangements give it. Count the arrangements for "shattered" and for "whole".
> There are astronomically many ways to be shattered and essentially one way to be whole. So
> the reverse is not forbidden; it is just a rearrangement with almost no arrangements behind
> it. That is the whole mechanism: a direction appears whenever one side of a process has
> vastly more arrangements than the other.

Records the check, then asks:

```bash
python3 scripts/session.py check --session lh_a1b2c3d4 --node improbability \
  --question "A sugar cube dissolves. Using arrangements, why does it dissolve rather than spontaneously reassemble?" \
  --key "Dissolved has vastly more arrangements than a cube, so the reverse needs a specific arrangement out of overwhelmingly many. Not forbidden, just improbable."
```

**Learner**

> Because there are way more ways for the sugar to be spread out than packed into a cube, so
> reassembling would need one specific arrangement. Confidence 4. It's the same counting as
> the coin thing.

```bash
python3 scripts/session.py answer --session lh_a1b2c3d4 \
  --text "There are way more ways for it to be spread out than packed in a cube, so reassembling would need one specific arrangement." \
  --correct true --confidence 4 --trace "same counting as the coin, many more spread-out arrangements"
python3 scripts/session.py step-close --session lh_a1b2c3d4 --node improbability --outcome held
```

---

Next step: `direction`. **Agent**

> So far the direction is statistical. Now: is it ever actually violated?

**Learner**

> In principle maybe, but not for anything big.

**Agent**

> Right, and that "in principle" is the whole content of the second law. A small system can
> fluctuate the wrong way; the probability falls off so fast with size that for anything you
> can see it never happens in the age of the universe. The law is not a prohibition, it is a
> statement about where the arrangements are.

```bash
python3 scripts/session.py check --session lh_a1b2c3d4 --node direction \
  --question "Why does the second law hold for a cup of coffee but not strictly for five molecules?" \
  --key "The number of arrangements favouring the likelier direction grows so fast with particle count that the wrong direction becomes vanishingly improbable. Five molecules is small enough to fluctuate."
```

**Learner**

> Because with five molecules there aren't many arrangements so it can wander back, but with
> 10^23 the wrong direction is so unlikely it never happens. Confidence 3. I'm less sure why
> it grows so fast.

```bash
python3 scripts/session.py answer --session lh_a1b2c3d4 \
  --text "With five molecules it can wander back, but with 10^23 the wrong direction never happens." \
  --correct true --confidence 3 --trace "small systems can wander back, big ones can't, not sure why it grows fast"
python3 scripts/session.py step-close --session lh_a1b2c3d4 --node direction --outcome partial
```

**Agent** — honest outcome: `partial`, not `held`. It does not push on to the second law,
because the growth rate is the thing that was not held.

```bash
python3 scripts/session.py plan-set --session lh_a1b2c3d4 --plan plan-v2.json
```

> I've added a step before the second law, because the reason it grows so fast is exactly the
> part you're missing, and the law depends on it.

---

## Close

**Agent**

> That's a good place to stop. Do you want me to record what you established into your graph?

**Learner**

> Yes.

Close runs in a **fresh invocation**. Its only input is the session log:

```bash
python3 scripts/session.py state --session lh_a1b2c3d4
python3 scripts/session.py render --session lh_a1b2c3d4
```

It does not read `plan.json` or `plan-v2.json`.

```bash
python3 scripts/graph_write.py merge --session lh_a1b2c3d4 --proposals proposals.json
```

```json
{
  "nodes": [
    {"ref": "a", "statement": "Entropy is the logarithm of the number of accessible arrangements."},
    {"ref": "b", "statement": "A direction of time appears when one side of a process has vastly more arrangements than the other."},
    {"ref": "c", "statement": "The second law is statistical, not prohibitive."}
  ],
  "chains": [
    {"premises": ["a"], "conclusion": "b"},
    {"premises": ["b"], "conclusion": "c"}
  ]
}
```

```text
{
	"ok": true,
	"nodes": 3,
	"chains": 2,
	"reused": 1
}
```

```bash
python3 scripts/verify.py --session lh_a1b2c3d4
```

```text
ok: 1 session(s) and the graph are consistent
```

```bash
python3 scripts/session.py close --session lh_a1b2c3d4 --nodes-written 3 --chains-written 2
```

**Agent**

> Recorded three propositions and two chains. The one you established most firmly is that the
> direction comes from counting, not from a prohibition — that is now the premise the second
> law hangs off. The growth rate is still open, and it is the first thing in the plan for next
> time.

---

## What this transcript is demonstrating

| Rubric | Where |
|---|---|
| D1, P1, P6 | probe opens with measurement and never teaches |
| P2, P4 | every `check` is recorded before the question appears, key included |
| P5 | the confidence 2 answer is treated as not held even though it is the textbook definition |
| P7 | three strands, each with its own assessment |
| N1 | no node restates the counting proposition the probe showed was held |
| N2, N3 | `plan.py validate` before `plan-set`; edges prerequisite → dependent |
| N5 | the outline is rendered once |
| D4 | teaching begins while `state` still reports `plan` |
| T1, T2, T3 | one check per step, tagged, after an elicitation and an explanation |
| T6, T7 | the partial step is closed `partial` and the plan is revised rather than pushed |
| D5, C1, C2 | close is offered, runs fresh, and records only what was established |
| C3, C4, C5 | endpoints resolve, `verify.py` is run, counts are reported |
