<!-- Thanks for contributing. Fill in what's relevant, delete the rest. -->

## Summary

<!-- 1-3 bullet points: what changes and why. -->

-
-

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor / cleanup
- [ ] Docs / tooling only
- [ ] Breaking change (explain below)

## Linked issue / spec

<!-- Reference the issue, spec, or plan this PR implements. -->

- Issue: #
- Spec: `docs/superpowers/specs/...` (if applicable)
- Plan: `docs/superpowers/plans/...` (if applicable)

## Test plan

- [ ] `pytest -q` passes locally
- [ ] `mypy src/claude_eyes` clean
- [ ] `ruff check src tests` clean
- [ ] Manual verification (describe below if relevant)

## Architectural check

- [ ] No AI reasoning moved into the Python package
- [ ] No deterministic logic moved into the subagent prompt
- [ ] MCP tools return structured errors, never raise
- [ ] Skills in `.claude/skills/` updated if any MCP tool response changed

## Breaking-change notes

<!-- Only if the PR changes MCP tool names, response shapes, or env-var
semantics. Explain the migration path. -->
