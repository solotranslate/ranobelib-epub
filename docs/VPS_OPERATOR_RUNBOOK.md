# VPS Operator Runbook for the Web EPUB Service

This runbook is for operating the `ranobelib-epub` web service on a VPS after it has already been deployed.

## Service scope and safety model

`ranobelib-epub` is a lightweight, DB-less FastAPI EPUB builder for public RanobeLib titles. It is intended to let an operator paste a public title URL, inspect available inventory, choose chapters, set EPUB metadata, build an EPUB, and download it.

The service stays within these boundaries:

- It has no database and no persistent user library.
- It performs read-only inventory, content, and image fetching.
- It does not use user accounts, authentication, cookies, sessions, tokens, or auth headers.
- It must not send `POST`, `PATCH`, or `DELETE` requests to RanobeLib.
- It does not perform browser automation.
- It does not upload, delete, or write data to RanobeLib.
- Runtime artifacts must stay outside the repository.

## Manual start

Start the service from the repository checkout on the VPS:

```sh
cd /srv/repos/ranobelib-epub
source .venv/bin/activate
uvicorn ranobelib_epub.app:app --host 127.0.0.1 --port 8000
```

## Health check

Check the local health endpoint:

```sh
curl -sS http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

## Operator workflow

1. Open the web interface.
2. Paste a public RanobeLib title URL.
3. Inspect the inventory preview before building.
4. Choose the desired translation branch and chapter range, or use chapter checkboxes where available.
5. Set EPUB metadata deliberately before starting the build.
6. Keep images off unless they are needed.
7. Use images knowingly: image-enabled builds can be slower and produce larger EPUB files.
8. Respect the synchronous build limit. Split large titles into smaller ranges instead of attempting one very large build.
9. Download the generated EPUB after the build completes.
10. Confirm generated files, logs, and raw payloads are not left in the repository checkout.

Inventory preview should be triggered manually by the operator. Do not add automated live inventory checks or smoke tests that request RanobeLib from CI.

## Update after merge

After a change is merged, update the VPS checkout with a fast-forward-only pull:

```sh
cd /srv/repos/ranobelib-epub
git status --short
git pull --ff-only
source .venv/bin/activate
python -m pip install -e .
```

Review `git status --short` before pulling. If the repository contains generated EPUBs, images, logs, raw API payloads, HAR files, screenshots, secrets, or other runtime artifacts, move them outside the repository before updating.

## Post-update smoke checklist

Run only operator-controlled, local/manual checks:

- `/health` returns `{"status":"ok"}`.
- The index page loads in the operator's browser.
- An invalid URL returns a controlled validation error, not a stack trace.
- Manual inventory preview is performed only by the operator when needed.
- Generated EPUBs, images, logs, raw payloads, HAR files, screenshots, and other runtime artifacts do not appear in the repository.

Do not add automated live HTTP tests, browser tests, real RanobeLib requests, image downloads, or EPUB generation against real data to CI for this smoke checklist.

## Troubleshooting

### Virtual environment is not activated

Symptoms can include missing commands, imports failing, or packages resolving from the system Python. Activate the expected virtual environment before starting or updating:

```sh
cd /srv/repos/ranobelib-epub
source .venv/bin/activate
```

### Missing dependencies

If the service cannot import installed packages after an update, reinstall the project inside the activated virtual environment:

```sh
python -m pip install -e .
```

### Port already in use

If startup fails because port `8000` is already in use, another process is already bound to `127.0.0.1:8000`. Stop the old process or choose an operator-approved local port. Do not add deployment automation as part of this runbook.

### 400 validation errors

HTTP `400` validation errors are expected for unsupported or malformed input. Re-check that the pasted URL is a public RanobeLib title URL and that selected branches or chapter ranges are valid.

### Long builds

Large titles can take a long time, especially when images are enabled. Split large titles into smaller chapter ranges and avoid image downloads unless they are needed.

### Image builds are slower or partially missing images

Image-enabled builds may be slower and produce larger EPUBs. In non-strict image handling, failed images can be skipped so the EPUB build can continue. Use images knowingly and verify the result before distributing it.

## Safety boundaries

Operators must keep the following out of the repository:

- generated EPUB files;
- downloaded images;
- logs;
- raw API payloads;
- HAR files;
- screenshots;
- secrets;
- cookies, tokens, sessions, auth headers, or other credentials.

Runtime artifacts belong outside the repository, for example under the VPS runtime paths documented in the README. Do not introduce automated live HTTP checks in CI, browser automation, upload/delete/write behavior, systemd units, nginx/caddy configuration, deployment automation, database/session/job/background-worker infrastructure, runtime directory creation scripts, generated artifacts, or FastAPI feature changes as part of this runbook.
