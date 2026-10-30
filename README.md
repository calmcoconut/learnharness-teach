# learnharness-teach

A portable [Agent Skill](https://agentskills.io) that runs the LearnHarness teaching loop
inside whatever agent harness you already use — Claude Code, Codex CLI, Antigravity or pi.

It measures what you actually understand before teaching anything, plans a dependency map
from there to your goal, teaches one reasoning step at a time with exactly one check per
step, and records what you established into a knowledge graph you keep.

No app. No server. No API keys. A folder and `python3`.

---

## Requirements

- **Python 3.10+** with the standard library only. Nothing to install.
- A harness that can read and write files, run `python3`, and ask you a question.
  Any of the four below qualify.

If `python3` is missing the skill refuses rather than degrading, because the scripts are
what enforce the method.

---

## Install

Copy this directory into your harness's skill directory. The folder name must stay
`learnharness-teach` — a skill's `name:` must equal its folder.

### Claude Code

```bash
mkdir -p .claude/skills
cp -R learnharness-teach .claude/skills/
```

Use `~/.claude/skills/` instead for a skill available in every project.

### Codex CLI, Antigravity and pi — one directory

All three read `.agents/skills/`, so a single copy serves all of them:

```bash
mkdir -p .agents/skills
cp -R learnharness-teach .agents/skills/
```

For a user-level install, `~/.agents/skills/` works for Codex and pi. Antigravity also
accepts `~/.gemini/antigravity-cli/skills/`; pi additionally reads `~/.pi/agent/skills/`.

### Verify

Ask your harness to *"teach me something with learnharness-teach"*. It should load
`SKILL.md` and start a probe session. If it instead tries to answer directly, the skill
was not discovered — check the folder name and that `SKILL.md` is at its root.

---

## Using it

Say what you want to understand:

> Teach me why entropy always increases. I know some statistical mechanics.

The agent runs five phases:

1. **Probe** — asks one question at a time to find where your understanding actually ends
   on each strand the goal depends on. Each question's answer key is committed before you
   see the question.
2. **Plan** — builds a dependency map from what you hold to the goal, shows it to you once.
3. **Teach** — one reasoning step at a time: you predict, it explains, you get checked.
   One check per step, never a lecture followed by a single test.
4. **Practice** — separate sessions with problems drawn from your graph, hints that
   escalate only when you are actually stuck.
5. **Close** — if you agree, it extracts the propositions and reasoning chains you
   established and merges them into the graph.

Everything is recorded in `.learnharness/` at your project root. Commit it if you want the
record to travel with the project.

### Asking for things directly

| You want | Say |
|---|---|
| resume | *"resume my learnharness session"* |
| practice only | *"give me practice problems from my graph"* |
| review | *"show me what I've established"* |
| close | *"close this session"* |

---

## What gets written

```
.learnharness/
├── graph/nodes.jsonl      propositions
├── graph/chains.jsonl     reasoning chains: premises → conclusion
├── graph/format.json      format stamp
└── sessions/<id>/
    ├── session.jsonl      append-only event log (the source of truth)
    └── session.md         readable lesson document
```

`session.md` is generated — read it, don't edit it. `session.jsonl` is append-only and is
what phase and position are derived from. There is no done-ledger: a step is complete when
a check for it happened, and a failed check moves nothing.

The full contract is in [`references/data-format.md`](references/data-format.md).

---

## Interop with the LearnHarness app

The graph format is byte-compatible with the [LearnHarness](https://learnharness.ai)
desktop app, so a graph built in your terminal can be viewed there:

```bash
python3 scripts/graph.py export --to "$HOME/Library/Application Support/LearnHarness/data"
```

It copies only `nodes.jsonl` and `chains.jsonl` and writes a format stamp. It never
deletes or rewrites the app's other files. Point `--to` at your platform's data directory;
on Linux and Windows see the app's documentation for the exact path.

Skill sessions are *not* app chats. The app's `sessions.jsonl` and `coverage.jsonl`
bookkeeping is deliberately not written, because these sessions have no chat to fold.

---

## What is enforced, and what is not

Enforced by the scripts, refused if violated:

- one open check at a time
- a check cannot be posed without its answer key already committed
- a check may not name a node that is not in the current plan
- the plan must be a valid DAG
- the probe concludes exactly once
- a session closes once

Advisory only — warned, never refused:

- whether every teaching check is tagged with `--node` — required by the teach reference,
  but not refused, since a check posed before a plan exists has no node to name
- more than 8 probe strands, 15 plan nodes, or 20 teaching steps

Deliberately absent: there is no path guard and no sandbox. The scripts write where they
are told. Treat the skill as you would any other tool you install.

---

## Development

```bash
python3 -m unittest discover -s tests -v   # the full suite
python3 tests/check_stdlib_only.py         # the zero-dependency guarantee
```

The shipped scripts import the standard library only and parse under Python 3.10; the test
suite enforces both. Tests themselves have no third-party dependencies.

`PLAN.md` is the build contract: the record format, the script CLI surface, the
enforcement rules and the risks carried into the design.

---

## License

AGPL-3.0-only. See [LICENSE](LICENSE).
