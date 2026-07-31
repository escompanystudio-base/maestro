# Contributing to Maestro

Thanks for helping improve Maestro. Keep changes focused, reproducible and safe for local project data.

## Before opening an issue

- Search existing issues.
- Include your operating system, Python version and the agent CLI involved.
- Remove tokens, prompts, source code and personal paths from logs.
- Provide the smallest workflow or command that reproduces the problem.

## Development setup

```bash
python -m venv .venv
pip install -e .[dev]
python -m pytest -q
python -m compileall -q .
```

## Pull requests

- Explain the user-facing problem and the chosen fix.
- Add or update tests for behavior changes.
- Preserve local-only defaults and path-safety checks.
- Do not commit `project/`, `.env`, logs, prompts, run history, snapshots or generated Graphify output.
- Keep documentation accurate about what was actually verified.

By submitting a contribution, you confirm that you have the right to provide it to this project. No license grant beyond applicable law is implied until the repository owner publishes an explicit license.
