# ranobelib-epub

Lightweight DB-less RanobeLib EPUB builder.

## Goal

A small web service where a user can paste a public RanobeLib title URL, select translation branches and chapters, build an EPUB, and download it.

## MVP boundaries

- No database.
- No user accounts.
- No persistent EPUB library.
- No browser automation.
- One active build at a time by default.
- Runtime artifacts stay outside the repository.

## Current operator workflow

See [docs/OPERATOR_WORKFLOW.md](docs/OPERATOR_WORKFLOW.md) for the current UI workflow: quick range actions, custom range behavior, manual selection, build cancellation, EPUB TOC expectations, and post-update smoke checks.

## VPS operations

The current VPS run mode uses a long-running `systemd` service on port `8080`.

For VPS update, operation, smoke-check, troubleshooting, and safety-boundary guidance, see [docs/VPS_SYSTEMD_8080.md](docs/VPS_SYSTEMD_8080.md).

The older [docs/VPS_OPERATOR_RUNBOOK.md](docs/VPS_OPERATOR_RUNBOOK.md) is kept only as a compatibility pointer.

## Runtime paths

Recommended VPS paths:

- `/srv/repos/ranobelib-epub` — repository checkout.
- `/srv/repos/ranobelib-epub/.venv` — Python virtual environment.

Generated EPUBs, temporary files, logs, and other runtime artifacts should not be stored in the repository checkout.

## Local run

Create and activate venv, then install dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Run the app locally:

```sh
uvicorn ranobelib_epub.app:app --host 127.0.0.1 --port 8080
```

Open:

```text
http://127.0.0.1:8080/
```

## Checks

```sh
pytest
ruff check .
```
