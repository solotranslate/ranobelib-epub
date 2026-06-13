# ranobelib-epub

Lightweight DB-less RanobeLib EPUB builder.

## Goal

A small web service where a user can paste a public RanobeLib title URL, select translation branches and chapters, build an EPUB, and download it.

## MVP boundaries

- No database.
- No user accounts.
- No persistent EPUB library.
- No cookies, auth, sessions, or tokens.
- No POST/PATCH/DELETE requests to RanobeLib.
- No browser automation.
- One active build at a time.
- Runtime artifacts stay outside the repository.

## Runtime paths

Recommended VPS paths:

- /srv/repos/ranobelib-epub
- /var/lib/ranobelib-epub/tmp
- /var/lib/ranobelib-epub/jobs
- /var/log/ranobelib-epub

## Local run

Create and activate venv, then install dependencies:

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements-dev.txt

Run the app:

    uvicorn ranobelib_epub.app:app --reload

Open:

    http://127.0.0.1:8000/

## Checks

    pytest
    ruff check .
