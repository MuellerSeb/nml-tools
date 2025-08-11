# AGENTS.md — nmlschema

## Project goals
- JSON-Schema–like spec with `x-fortran-kind` extension.
- Validate namelists (via `f90nml`), apply defaults, enforce `required`.
- Codegen: Fortran module, Markdown docs, template namelist.

## Build & test
- Python 3.12
- Install: `pip install -e ".[dev]" f90nml ruff mypy pytest coverage hatch`
- Quick checks:
  - Lint: `ruff check .`
  - Types: `mypy src`
  - Tests: `pytest -q`
  - Coverage: `coverage run -m pytest -q && coverage report`

## Conventions
- Style: ruff/black; type hints required in `src/nmlschema`.
- Tests first for bugs; add failing test, then fix.
- No new global deps without updating `pyproject.toml`.
- Use Conventional Commits in messages.

## What to do when I say “Code”
- Create minimal, reviewable patches.
- Always run ruff+mypy+pytest before presenting a diff.
- Include a short summary of what changed and why.
- Prefer small PRs per issue.

## What to do when I say “Ask”
- Scan the schema design, current code, and tests.
- Summarize tradeoffs, risks, and propose a plan.

## Useful tasks to start
- Implement `x-fortran-kind` validation + tests.
- Defaults for logicals: warn if missing, set `.false.` at load time.
- Generate Fortran module for nested objects/arrays (reader + type).
- Markdown docs generator: types, defaults, required, enums.


