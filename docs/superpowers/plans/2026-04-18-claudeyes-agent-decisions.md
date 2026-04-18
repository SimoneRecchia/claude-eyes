# claude-eyes Agent Autonomous Decisions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the main agent pick the right capture parameters first-time and recover from failures with a structured retry protocol — without changing MCP tool shapes.

**Architecture:** Pure prompt engineering across `CLAUDE.md`, the three skills (`analyze-screen`, `analyze-page-animation`, `review-recent-activity`), and the `frame-analyzer` subagent prompt. One Python default change (`DEFAULT_FPS: 3 → 10`) plus its unit-test update. No runtime behaviour changes in tools.

**Tech Stack:** Python 3.13, Markdown, pytest. No new dependencies.

**Prerequisite:** Spec 6 design at `docs/superpowers/specs/2026-04-18-claudeyes-agent-decisions-design.md`. Branch `feat/agent-decisions-spec6` already created with the design commit.

---

## File structure

```
src/claude_eyes/
└── config.py                 # Task 1 — DEFAULT_FPS 3 -> 10

tests/
└── test_config.py            # Task 1 — update assert

.claude/
├── agents/frame-analyzer.md  # Task 2 — coord contract, preview-is-scan
├── skills/
│   ├── analyze-screen/SKILL.md           # Task 4 — step 0, retry, drill-mandatory
│   ├── analyze-page-animation/SKILL.md   # Task 5 — retry ref, fps table
│   └── review-recent-activity/SKILL.md   # Task 6 — buffer-insufficient escalation

CLAUDE.md                    # Task 3 — decision tree, new fps table, retry protocol
```

---

## Task 1: `DEFAULT_FPS` 3 → 10 + test update

**Files:**
- Modify: `src/claude_eyes/config.py:11`
- Modify: `tests/test_config.py:25`

- [ ] **Step 1: Update the failing test first (it's a constant-value assert)**

Edit `tests/test_config.py` line 25:

```python
# before
assert DEFAULT_FPS == 3

# after
assert DEFAULT_FPS == 10
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/c/Users/recch/PycharmProjects/claude-eyes" && .venv/Scripts/python.exe -m pytest tests/test_config.py -v
```

Expected: the assertion fails because `DEFAULT_FPS` is still `3`.

- [ ] **Step 3: Update config.py to match**

Edit `src/claude_eyes/config.py` line 11:

```python
# before
DEFAULT_FPS: int = 3

# after
DEFAULT_FPS: int = 10
```

- [ ] **Step 4: Run full suite**

```bash
cd "/c/Users/recch/PycharmProjects/claude-eyes" && .venv/Scripts/python.exe -m pytest -q
```

Expected: **113 passed**. Other tests that used `fps=3` as a literal test value (not the default) are unaffected.

- [ ] **Step 5: mypy + ruff**

```bash
cd "/c/Users/recch/PycharmProjects/claude-eyes" && .venv/Scripts/python.exe -m mypy src/claude_eyes && .venv/Scripts/python.exe -m ruff check src tests
```

Expected: both clean.

- [ ] **Step 6: Commit**

```bash
cd "/c/Users/recch/PycharmProjects/claude-eyes" && git add src/claude_eyes/config.py tests/test_config.py && git commit -m "feat(config): raise DEFAULT_FPS from 3 to 10

The previous default was too conservative: every meaningful analysis
required the agent to override it, and it often didn't (picking 5-15
fps for motion tasks where 25+ was needed). 10 fps matches what the
dogfood tests showed as the real working floor."
```

---

## Task 2: Subagent prompt — coordinate contract + preview-is-scan

**File:** `.claude/agents/frame-analyzer.md`

Two changes: (a) add a coordinate contract before the output format, (b) add one more principle after the existing ones.

- [ ] **Step 1: Read current file**

The file is short (~55 lines). Read it once before editing.

- [ ] **Step 2: Insert the coordinate contract**

After the `## Method` section and before `## Output format`, insert:

```markdown
## Coordinate contract

When images are presented to you, you see them at their actual pixel dimensions (Claude Code's viewer does not rescale the raw image data you receive). If the main agent asks for pixel coordinates:

- Use the actual image dimensions as the coordinate system.
- In the first sentence of your answer, state the dimensions you are using (e.g., "Frames are 1720×1320 pixels.").
- Do not invent a "viewer" scale.

If pixel coordinates are not explicitly requested, prefer qualitative positions ("top-left quadrant", "center", "row 2 column 3").
```

- [ ] **Step 3: Add a principle about scan-vs-answer**

Append to the `## Principles` section, as a new bullet after the existing five:

```markdown
- **The preview image is never the final answer for motion, trail, or timing questions.** When the main agent passes you a single composited preview image and asks about motion shape, trail, smoothness, or timing, your job is ONLY to identify which temporal bucket(s) contain the motion — do NOT describe the shape, trail, or smoothness from the preview. Return bucket indices only. The main agent will drill to raw frames for the real answer.
```

- [ ] **Step 4: Commit**

```bash
cd "/c/Users/recch/PycharmProjects/claude-eyes" && git add .claude/agents/frame-analyzer.md && git commit -m "docs(subagent): coordinate contract + preview-is-scan rule

Two root causes from the 2026-04-18 dogfood: (1) subagent invented
viewer-scaled coordinates for pixel-precise tasks, (2) subagent
answered motion/trail questions from a single preview image instead
of deferring to the drill pass.

Coordinate contract states the subagent sees images at their actual
pixel dimensions and must either use those dimensions or prefer
qualitative positions.

Preview-is-scan principle scopes the subagent's response to 'bucket
indices only' when it receives a preview image and a motion-class
question."
```

---

## Task 3: `CLAUDE.md` — decision tree, new fps table, retry protocol

**File:** `CLAUDE.md`

This is the largest edit. Three sections added/replaced: decision tree (new), fps heuristics (rewritten), retry protocol (new). Plus three additions to "Hard rules".

- [ ] **Step 1: Re-read the file**

Read `CLAUDE.md` end-to-end once so the subsequent edits target the right line spans.

- [ ] **Step 2: Replace the `## Parameter heuristics` section**

Find the existing section starting at `## Parameter heuristics (for \`start_recording\`)` and replace **from that heading through the `### session_name` sub-section** (inclusive) with the block below:

```markdown
## Decision tree: how to pick the right approach

Claude makes three decisions in sequence before starting any recording:

### 1. Categorize the question

| Category | Examples | Drill mandatory? | fps target |
|---|---|---|---|
| **Motion / gesture / trail** | "che forma sto facendo", "traccia il percorso", "cursor path" | **yes** | 25–30 |
| **Timing / transition** | "is it smooth", "when does X appear", "flicker" | **yes** | 20–25 |
| **Existence / layout** | "cosa c'era sul menu", "which buttons are visible" | no | 10–15 |
| **Long recall** | "cosa ho fatto negli ultimi 5 minuti" | no | 2–3 (buffer OK) |

The category drives the next two decisions. Motion and timing questions require the drill pass — the preview is never a valid final answer for them.

### 2. Pick `fps` and `resolution_scale`

| Situation | `fps` | `resolution_scale` |
|---|---|---|
| Mouse gesture / drag / cursor path | 25–30 | 0.75 |
| OS animation / Chrome transition | 20–25 | 1.0 |
| Normal UI animation | 15–20 | 1.0 |
| UI walkthrough / multi-step | 10 | 0.75 |
| **Default (no clear hint)** | **10** | **0.75** |
| Layout-only check | 5 | 0.5 |
| Long recall / "what did I do" | 2–3 | 0.75 |

Hard ceiling: **60 fps** (monitor refresh rate; above that is wasted disk).

### 3. Pick `region`

- For localized UI (a button, a widget, a menu): tight bounding box. Saves disk and focuses the subagent.
- For multi-monitor setups (`CLAUDE_EYES_MONITOR=0`, i.e. virtual screen): if the action is on one monitor, narrow `region` to that monitor's bounds. Full virtual-screen captures on multi-monitor hit I/O ceilings fast.
- If unsure, ask the user "which monitor is the action on?" once before starting the recording.

### Session name

`session_name` is an optional human-readable label for your own tracking. Defaults to auto-generated.

## Retry protocol

If the first analysis attempt fails or hedges, retry ONCE with different parameters. Do not re-run the same capture with the same settings.

**Retry triggers** (retry if any apply):

- Subagent response contains hedge words: "I think", "probably", "could be", "hard to tell", "perhaps".
- Response is shorter than ~20 words for a qualitative question.
- Response contradicts a specific hint the user provided.
- User explicitly says "wrong" / "riprova" / "no, try again".

**Retry tactics** (apply in this priority order, pick the first that fits):

1. **I/O-first.** If `fps_effective < 50% × fps_nominal`, lower `resolution_scale` to 0.5 OR narrow `region` to a single monitor before touching fps. Raising fps under I/O bottleneck is wasted.
2. **Preview mode.** For motion/trail with a vague answer, switch `compose_timeline_preview(mode="max")` and re-run the drill. For timing, switch to `mode="motion"`.
3. **Drill scope.** If the first drill used the whole `active_range`, narrow to a single bucket and drill that alone (higher frame density on the moment that matters).
4. **fps bump.** Only after 1–3 have been applied, bump `fps` by +5 (cap at 30).

Always call `cleanup_session` on the first recording before starting the second. If the second attempt also fails, tell the user what you tried and ask for a specific hint — do not loop.
```

- [ ] **Step 3: Update `## Hard rules` — add three new bullets**

Find the `## Hard rules` section and append these three bullets to the list (keep the existing ones):

```markdown
- **Preview images are a SCAN tool, never an ANSWER.** After the scan pass identifies relevant buckets, the drill pass is MANDATORY for motion-, timing-, or trail-category questions. Answering from a composited preview is a bug.
- **For motion- or timing-category questions, never rely on the 2 fps continuous buffer.** Start an on-demand recording at `fps >= 20` — the buffer coexists with on-demand recordings, no need to stop it.
- **Under I/O bottleneck (`fps_effective < 50% × fps_nominal`), the retry MUST lower `resolution_scale` or narrow `region` before raising `fps`.** Raising fps when I/O is the bottleneck is wasted compute.
```

- [ ] **Step 4: Verify the file flows**

Read the modified file top-to-bottom once. Check:
- `## Decision tree` appears before `## Standard workflow`.
- `## Retry protocol` appears immediately after `## Scan-then-drill workflow`.
- The three new `Hard rules` bullets are in `## Hard rules`, not somewhere else.
- No dangling references to the old `## Parameter heuristics` heading.

- [ ] **Step 5: Commit**

```bash
cd "/c/Users/recch/PycharmProjects/claude-eyes" && git add CLAUDE.md && git commit -m "docs(claude): decision tree, new fps table, retry protocol

Top-level rewrite of how Claude chooses capture parameters:

- New 'Decision tree' section splits the choice into three sequential
  steps: categorize, parameters, region. Categories drive whether the
  drill pass is mandatory.
- Replaced fps heuristic table: adds a motion/gesture/trail tier at
  25-30 fps that was missing, moves the default from 3 to 10.
- New 'Retry protocol' section with triggers and tactic priority.
  I/O-first (lower res_scale before raising fps) is rule #1.
- Three new 'Hard rules' bullets reify the spec's non-negotiables."
```

---

## Task 4: `analyze-screen` skill — step 0, retry, drill-mandatory

**File:** `.claude/skills/analyze-screen/SKILL.md`

- [ ] **Step 1: Read the file**

Read current state end-to-end.

- [ ] **Step 2: Replace Step 1 "Pick parameters" with a two-step structure (0 + 1)**

The current workflow begins:

```markdown
1. **Pick parameters.** Read the heuristics in `CLAUDE.md` and choose `fps`, ...
```

Replace that line with:

```markdown
1. **Categorize the question.** Follow the decision tree in `CLAUDE.md` — motion/gesture/trail, timing/transition, existence/layout, or long-recall. Motion and timing categories require the drill pass and higher fps.

2. **Pick parameters.** Read the heuristics in `CLAUDE.md` and choose `fps`, `resolution_scale`, and `region` for the task. Start with the defaults from the decision tree; only deviate if you have specific reason.
```

And renumber the subsequent steps accordingly: old 2 → new 3, old 3 → new 4, etc.

- [ ] **Step 3: Strengthen the "Scan then drill" step (old 5, new 6)**

Find the existing step 5 `Scan then drill`. Replace its intro paragraph (the one that says "optimise token spend on the subagent") with:

```markdown
6. **Scan then drill** — optimise token spend on the subagent.

   **The drill pass is MANDATORY for motion/gesture/trail and timing/transition categories.** The preview image compresses time and cannot reveal order, smoothness, or shape evolution — answering from it is a bug. Even when the preview "seems to show" the answer, dispatch the drill pass on raw frames.

   For existence/layout and long-recall categories, the drill pass is recommended but optional if the preview is unambiguous.
```

Keep the rest of the step (the `frames_count < 30` branch, the Scan pass, the Drill pass subsections) unchanged.

- [ ] **Step 4: Add a new step "Retry once if needed" after "Cleanup"**

The current step 6 is Cleanup, step 7 is Answer. Insert a new step between them:

Find `7. **Answer the user.**` and replace the block from `6. **Cleanup.**` through `7. **Answer the user.**` with:

```markdown
7. **Cleanup.** Call `mcp__claude_eyes__cleanup_session(session_id)`. **Always.** Even if the analysis failed, even if the user interrupted, even if the subagent returned nothing useful.

8. **Retry once if the answer is uncertain.** If the subagent's response hedges ("I think", "probably", "hard to tell"), is under ~20 words for a qualitative question, or conflicts with a hint the user gave, retry with different parameters using the tactic priority in `CLAUDE.md § Retry protocol`. Cleanup the first session before starting the second. If the second attempt also fails, tell the user what you tried and ask for a specific hint.

9. **Answer the user.** Synthesize the subagent's report into a direct, concise answer. Do not paste the whole report — extract what matters for the question.
```

- [ ] **Step 5: Update the "Parameter selection quick reference" table**

Find the table that starts `| Situation | \`fps\` | \`resolution_scale\` | \`region\` |`. Replace the whole table with:

```markdown
| Situation | `fps` | `resolution_scale` | `region` |
|---|---|---|---|
| Mouse gesture / cursor path | 25–30 | 0.75 | full or single monitor |
| OS / Chrome animation | 20–25 | 1.0 | tight bbox |
| Normal UI animation | 15–20 | 1.0 | tight bbox |
| UI walkthrough | 10 | 0.75 | tight bbox |
| Default | 10 | 0.75 | full |
| Layout-only check | 5 | 0.5 | full |
| Long recall | 2–3 | 0.75 | full |
```

- [ ] **Step 6: Update "Common mistakes to avoid"**

Find the `## Common mistakes to avoid` list and make these three targeted changes:

Replace the bullet `- **Asking the scan subagent for a final answer.**...` (whole bullet) with:

```markdown
- **Treating the preview as the answer.** The preview is always a scan tool. For motion/timing/trail questions, the drill pass is NOT OPTIONAL — even when the preview looks like it shows the answer.
```

Append two new bullets to the same list:

```markdown
- **Retrying with identical parameters after a failure.** If the first pass failed, change something meaningful (res_scale, region, preview mode) before retrying. Running the same capture again won't help.
- **Raising fps when `fps_effective < 50%`.** Under I/O bottleneck, raising fps trades disk thrash for zero extra frames. Lower `resolution_scale` or narrow `region` first.
```

- [ ] **Step 7: Commit**

```bash
cd "/c/Users/recch/PycharmProjects/claude-eyes" && git add .claude/skills/analyze-screen/SKILL.md && git commit -m "docs(skill): analyze-screen gets step 0 'categorize' + retry step

Four changes aligning the skill with Spec 6's decision tree:

- New step 1 'Categorize the question' before picking parameters.
- Step 6 'Scan then drill' now explicitly states the drill pass is
  mandatory for motion/timing/trail categories.
- New step 8 'Retry once if needed' with hedge-word/short-answer
  triggers and the I/O-first tactic priority.
- Parameter quick-reference table rewritten with the motion tier.
- Common mistakes list reifies the preview-as-scan rule, the
  'change something on retry' rule, and the I/O-first rule."
```

---

## Task 5: `analyze-page-animation` skill — retry cross-reference, fps table

**File:** `.claude/skills/analyze-page-animation/SKILL.md`

- [ ] **Step 1: Read the file**

- [ ] **Step 2: Update the FPS heuristics table**

Find the existing table under `## FPS heuristics` (by expected duration). Replace it with the decision-tree-aligned version:

```markdown
| Expected animation duration | `fps` | Category |
|---|---|---|
| < 1 s (snap, flash, click feedback) | 25–30 | motion/timing |
| 1–3 s (normal CSS transition) | 20–25 | timing |
| 3–8 s (fluid UI, multi-step) | 15–20 | timing |
| 8+ s (page reveal, long form) | 10–12 | timing |

If the question is about a trail or cursor path on a Chrome page (rare — Chrome usually drives the action via `computer` or `javascript_tool`), follow the motion tier from `CLAUDE.md`: fps 25–30.

Do NOT drop below 10 fps for animation analysis. The previous 5-8 fps floor was too low.
```

- [ ] **Step 3: Add retry protocol cross-reference**

After the `## FPS heuristics` section and before `## Error handling`, add a new section:

```markdown
## Retry protocol

If the subagent's answer hedges or conflicts with the user's description, retry ONCE using the tactic priority in `CLAUDE.md § Retry protocol`. For Chrome contexts specifically:

- First retry tactic is usually to **narrow `region`** to the element's bounding box (DPR-converted from `getBoundingClientRect()`) instead of re-recording the whole tab.
- If `fps_effective < 50% × fps_nominal`, lower `resolution_scale` to 0.5 before raising fps.
- For animations on a page that's also running heavy JS (React dev server, live-reload), close DevTools and unrelated tabs before re-recording.

Cleanup the first session before starting the second.
```

- [ ] **Step 4: Commit**

```bash
cd "/c/Users/recch/PycharmProjects/claude-eyes" && git add .claude/skills/analyze-page-animation/SKILL.md && git commit -m "docs(skill): analyze-page-animation gets retry protocol + fps table

FPS heuristics table aligned with the decision tree (motion tier,
no values below 10). New 'Retry protocol' section cross-references
CLAUDE.md and adds Chrome-specific tactics (narrow region from DOM
bbox, close DevTools for React dev servers)."
```

---

## Task 6: `review-recent-activity` skill — buffer insufficiency escalation

**File:** `.claude/skills/review-recent-activity/SKILL.md`

- [ ] **Step 1: Read the file**

- [ ] **Step 2: Insert Step 1.5 "Check if the buffer is the right tool"**

Find the line:

```markdown
2. **Pick `time_range_s` from phrasing.** Defaults:
```

Immediately before that line, insert:

```markdown
1.5. **Check if the buffer is the right tool.** If the user's question involves motion quality (gestures, trails, smoothness, or a shape the cursor is drawing), the 2 fps buffer is **insufficient**. Do not attempt to answer from it. Tell the user:

   > "The continuous buffer is sampled at 2 fps — for motion-quality questions we need an on-demand recording at a higher frame rate. Should I start one?"

   If the user agrees, switch to the `analyze-screen` skill with fps ≥ 20. The continuous buffer can keep running — it coexists with on-demand recordings.

   For existence/layout questions ("what was on the menu", "which apps were open") and long-recall questions ("what did I do in the last 10 minutes"), the buffer is the right tool — continue with the workflow below.

```

- [ ] **Step 3: Add a `Common mistakes` entry**

Find the `## Common mistakes to avoid` list. Append:

```markdown
- **Answering a motion-quality question from the 2 fps buffer.** The buffer is for coarse recall ("what did I do") — never for fine motion analysis. Escalate to `analyze-screen` with higher fps instead.
```

- [ ] **Step 4: Commit**

```bash
cd "/c/Users/recch/PycharmProjects/claude-eyes" && git add .claude/skills/review-recent-activity/SKILL.md && git commit -m "docs(skill): review-recent-activity escalates motion questions

New step 1.5 catches motion/gesture/smoothness questions before
the workflow queries the 2-fps buffer. Tells the user the buffer
is insufficient for motion analysis and offers to start an
on-demand recording at higher fps (the two don't conflict — they
run in parallel)."
```

---

## Task 7: Full verification + push

**Files:** none (CI-style checks + push)

- [ ] **Step 1: Full suite**

```bash
cd "/c/Users/recch/PycharmProjects/claude-eyes" && .venv/Scripts/python.exe -m pytest -q
```

Expected: **113 passed**. Only one test (`test_config.py::test_default_fps`) changed assertion, already committed in Task 1.

- [ ] **Step 2: mypy**

```bash
cd "/c/Users/recch/PycharmProjects/claude-eyes" && .venv/Scripts/python.exe -m mypy src/claude_eyes
```

Expected: `Success: no issues found in 9 source files`.

- [ ] **Step 3: ruff**

```bash
cd "/c/Users/recch/PycharmProjects/claude-eyes" && .venv/Scripts/python.exe -m ruff check src tests
```

Expected: `All checks passed!`.

- [ ] **Step 4: Cross-file prompt consistency sanity-check**

Grep for phrases that should appear consistently across the modified files:

```bash
cd "/c/Users/recch/PycharmProjects/claude-eyes" && grep -rn "retry protocol\|drill pass\|preview is" CLAUDE.md .claude/ | head -40
```

Expected: references in CLAUDE.md + all three skills + the frame-analyzer prompt. No file is missing the concept.

- [ ] **Step 5: Push**

```bash
cd "/c/Users/recch/PycharmProjects/claude-eyes" && git push -u origin feat/agent-decisions-spec6
```

Expected: new remote branch created, PR URL printed.

---

## Self-Review

**1. Spec coverage.**

| Spec requirement | Task |
|---|---|
| `DEFAULT_FPS` 3 → 10 + test | 1 |
| Coordinate contract in subagent prompt | 2 |
| Preview-is-scan rule in subagent prompt | 2 |
| Decision tree in CLAUDE.md (categorize → params → region) | 3 |
| New fps table in CLAUDE.md | 3 |
| Retry protocol in CLAUDE.md | 3 |
| Three new "Hard rules" (preview-as-scan, buffer-vs-motion, I/O-first) | 3 |
| `analyze-screen`: step 0 "categorize" | 4 |
| `analyze-screen`: drill-mandatory for motion/timing | 4 |
| `analyze-screen`: retry step + updated mistakes list | 4 |
| `analyze-screen`: fps quick-reference update | 4 |
| `analyze-page-animation`: retry cross-ref + fps table | 5 |
| `review-recent-activity`: buffer-insufficient escalation | 6 |
| Verification (pytest + mypy + ruff + consistency grep) | 7 |

Every spec section maps to a task. No gaps.

**2. Placeholder scan.**

Re-read each task. No TBD, no "add appropriate", no "similar to Task N". Every step has either the exact code, the exact Markdown to insert, or the exact bash command. ✓

**3. Type consistency.**

Tasks 2–6 all reference the same concepts: "decision tree", "drill pass", "retry protocol", "preview is scan", "I/O-first". Names are identical across tasks. ✓

Task 1 uses `DEFAULT_FPS` (the actual constant name in `config.py`). ✓

---

## Ready to execute

Plan complete. Two execution options:

**1. Subagent-Driven (recommended for mechanical work)** — Each task dispatched to a fresh subagent with spec + code review loop.

**2. Inline Execution** — Execute tasks in this session with checkpoint commits.

Given that Tasks 2–6 are prompt engineering requiring holistic judgement across documentation, **inline execution is the better fit here**. Subagent dispatch is ideal for mechanical Python edits but can mis-interpret subtle prompt-engineering requirements.

Recommend inline execution.
