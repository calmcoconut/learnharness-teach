# Harness notes

Per-harness facts that affect how `learnharness-teach` is discovered, how it asks
questions, and where the pedagogy is weakened. Sourced from each vendor's documentation
during design; the *Validation* row records whether the loop has actually been run there,
which is the only evidence that counts.

**Status: none of the four has been validated end to end yet.** These are the conditions
P7 has to satisfy, not claims that it does.

---

## Discovery and install

| Harness | Project path | User path | Notes |
|---|---|---|---|
| Claude Code | `.claude/skills/learnharness-teach/` | `~/.claude/skills/` | Also reads `.claude/commands/*.md` as legacy commands; a skill and a command of the same name collide. Skills load on demand and can run in a forked context. |
| Codex CLI | `.agents/skills/learnharness-teach/` | `~/.agents/skills/` | Reads `.agents/skills` from the working directory upward to the repo root. It does **not** read `~/.codex/skills`. |
| Antigravity | `.agents/skills/learnharness-teach/` | `~/.gemini/antigravity-cli/skills/`, `~/.gemini/config/skills/`, `~/.gemini/antigravity/skills/` | Legacy `.agent/skills/` (singular) still works. |
| pi | `.agents/skills/learnharness-teach/` | `~/.agents/skills/`, `~/.pi/agent/skills/` | Also reads `.pi/skills/`. |

Three of four share `.agents/skills/`, so one copy serves Codex, Antigravity and pi.

---

## Asking the learner a question

The skill deliberately does not name a tool. It says "use your question tool if you have
one, otherwise pose numbered options in prose". These are the tools each harness actually
provides:

| Harness | Tool | Shape | Reliability |
|---|---|---|---|
| Claude Code | `AskUserQuestion` | `questions[]` with `options[{label, description}]`, plus an "Other" row and a notes field | Reliable. `disallowed-tools` in skill frontmatter can strip it — do not add that field. |
| Codex CLI | `request_user_input` | `questions[]` with `options[{label, description}]` | **Weakest.** Reported as mode-gated and prone to drifting to free text. Expect prose fallback. |
| Antigravity | `ask_question` | `questions[]` with `options`, `is_multi_select` | Reliable. |
| pi | none built in | — | Requires an installed extension (`ctx.ui.select` / `ctx.ui.custom`). In JSON/print mode there is no UI, so the tool must degrade to prose. |

Consequence for the design: confidence and the reasoning trace are always asked in prose,
never as a structured field, because the structured channel is not uniformly available and
its shape differs everywhere.

---

## System-prompt injection

The pedagogy lives in `SKILL.md` and `references/`, not in a system prompt, because the
channel is not portable.

| Harness | Channel | Usable? |
|---|---|---|
| Claude Code | `--append-system-prompt`, `--system-prompt-file`, SDK preset + append | Yes |
| Codex CLI | `developer_instructions`, `model_instructions_file` | Yes |
| pi | `.pi/APPEND_SYSTEM.md`, `--append-system-prompt`, `before_agent_start` hook | Yes, richest |
| Antigravity | **none** — `AGENTS.md`, `.agents/rules/*.md` only | No |

Antigravity is the constraint that forces `SKILL.md` to be self-sufficient. Do not move
load-bearing rules out of it into an assumed system prompt.

---

## Headless and non-interactive use

All four can run non-interactively, which matters if anyone later wants an automated
validation run:

| Harness | Command | Stream |
|---|---|---|
| Claude Code | `claude -p --output-format stream-json` | stream-json events |
| Codex CLI | `codex exec --json` | JSONL (`thread.started`, `turn.completed`, …) |
| Antigravity | `agy -p --output-format stream-json` | NDJSON with a closed `step_type` vocabulary. Verify the reported non-TTY stdout bug first. |
| pi | `pi --print`, `pi --mode json` | JSONL; `agent_settled` is the real idle signal |

---

## P7 validation checklist

Run each of these and record the outcome, including failures. A harness that cannot
complete the loop should be documented as unsupported rather than assumed working.

For each harness:

1. Copy the skill into the correct directory for that harness.
2. Ask it to teach a small topic. Confirm it loads `SKILL.md` and starts a **probe**, not
   an explanation. Failing this means the skill was not discovered.
3. Confirm a question is asked one at a time and that the check is recorded *before* the
   question is visible: `session.py state` should show an open check while the question is
   on screen.
4. Answer with a confidence and a trace. Confirm `session.py answer` records both.
5. Confirm `conclude-probe` succeeds and the phase moves to `plan`.
6. Confirm a plan is authored, validated, and rendered once.
7. Teach one step and confirm the check is tagged with a node id and `step-close` accepts it.
8. Close the session and confirm `graph_write.py merge` writes nodes and chains, and
   `verify.py` reports clean.
9. Record every divergence below.

### Divergence log

| Harness | Date | Loop completed | Question channel used | Divergences |
|---|---|---|---|---|
| Claude Code | — | not yet run | — | — |
| Codex CLI | — | not yet run | — | — |
| Antigravity | — | not yet run | — | — |
| pi | — | not yet run | — | — |

---

## Known weaknesses by harness

- **Antigravity** — no system-prompt channel, so every load-bearing instruction must be in
  `SKILL.md`. Also the docs are JS-rendered, so several capability claims in this file rest
  on `.md` variants and search snippets rather than first-party prose.
- **Codex** — the structured question channel is the least dependable, which is exactly
  where the method needs a clean answer. Budget for prose.
- **pi** — no built-in question tool and no built-in subagents. Neither is required by this
  skill, but the close step cannot delegate extraction to a subagent there.
- **Claude Code** — the most capable host, and therefore the one most likely to hide a
  portability bug. Validate the others first.
