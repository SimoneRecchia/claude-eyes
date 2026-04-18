# Contributing to claude-eyes

Thanks for your interest. This document captures the conventions the
project has kept across its first five specs so a new contributor can land
a change with as little friction as possible.

## Core architectural rule

**Python is deterministic. The subagent is where AI lives.**

- Any motion scoring, threshold, preview composition, session
  bookkeeping, or I/O belongs in the Python package.
- Any "look at these frames and tell me what happens" logic belongs in
  the `frame-analyzer` subagent prompt.
- The main agent orchestrates: it calls MCP tools, dispatches the
  subagent via the `Task` tool, then synthesizes. It never does vision
  reasoning directly.

If a change blurs this boundary, it will get pushed back in review.

## Development workflow

1. **Open an issue first for non-trivial work.** A five-minute design
   chat beats three days of wasted implementation.
2. **Branch off `main`.** Use `feat/<short-slug>` for features,
   `fix/<slug>` for bug fixes, `chore/<slug>` for tooling.
3. **Write a spec for anything that adds user-visible surface.**
   `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` — short is
   fine. A one-pager is better than no spec.
4. **Write a plan.** `docs/superpowers/plans/YYYY-MM-DD-<topic>.md`
   with bite-sized tasks. Existing plans in the repo show the style.
5. **Implement with TDD.** Write the failing test, see it fail, make
   it pass, commit. The `tests/` folder uses `_FakeMSS` so tests run
   without a real screen.
6. **Keep commits granular.** One logical change per commit, message
   in the form `area: imperative summary`. Look at `git log` for
   examples.
7. **Open a PR.** Reference the spec and plan, include the test plan,
   link to any issue.

## Quality gates (all must pass before merge)

```bash
.venv/Scripts/python.exe -m pytest -q          # all tests green
.venv/Scripts/python.exe -m mypy src/claude_eyes  # strict mode, no errors
.venv/Scripts/python.exe -m ruff check src tests  # no lint issues
```

CI runs the same three commands on every push and pull request. Don't
merge a red build.

## Coding style

- **Line length**: 100 (ruff-enforced).
- **Type hints**: required everywhere. `mypy --strict` must pass.
- **Lint set**: `E, F, W, I, UP, B, SIM, RUF` — the defaults the project
  ships with. No new lints without discussion.
- **Docstrings**: mandatory on public functions and MCP tools. Focus on
  *why* and on the response contract, not on restating types.
- **Imports**: `from __future__ import annotations` at the top of every
  module.
- **Python 3.13 features are allowed** — the project targets that
  version and will not accept back-porting.

## MCP tool changes

The MCP server is the public API of the project. Treat it that way:

- **Additive changes** (new tool, new response field) are easy.
- **Breaking changes** (renaming a tool, changing a return shape)
  require a spec, an open migration path, and a release note.
- **Every tool must return structured errors** (`{"error": "..."}`) —
  never raise. The agent loop depends on this.
- **Skills are part of the API.** If you touch an MCP tool, check the
  three skills in `.claude/skills/` for drift and update them in the
  same PR.

## Tests

- Use `tests/test_recorder.py::_FakeMSS` for any test that would
  otherwise need a real screen.
- Pure functions go in `tests/test_<module>.py` with direct imports.
- Server tool tests go in `tests/test_server.py` — use the
  `patched_server` fixture which reloads the module with a fake `mss`.
- Avoid timing-dependent assertions. If you need one, give it
  ≥50% slack.

## Reviewing

Pull requests go through two passes:

1. **Spec compliance.** Does the code implement what the spec / issue
   described? Anything extra, anything missing?
2. **Code quality.** Readability, tests, adherence to the
   architectural rule above.

Both happen before merge. Reviewers will leave explicit approvals or
request changes — no vague "looks fine".

## Community

Be patient, be specific, be kind. Assume good faith. No code of conduct
document is shipped yet; behave as if there were one.

Thanks for reading this far.
