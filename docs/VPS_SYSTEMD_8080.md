# VPS systemd operations on port 8080

This note records the current long-running VPS operation mode for `ranobelib-epub`.

Current runtime facts:

- repository: `/srv/repos/ranobelib-epub`;
- virtual environment: `/srv/repos/ranobelib-epub/.venv`;
- Linux user: `vlad`;
- service manager: `systemd`;
- service name: `ranobelib-epub`;
- HTTP port: `8080`.

The current UI/operator workflow is documented in [OPERATOR_WORKFLOW.md](OPERATOR_WORKFLOW.md).

The systemd unit itself lives on the VPS at:

```text
/etc/systemd/system/ranobelib-epub.service
```

The service should run Uvicorn for `ranobelib_epub.app:app` from the repository checkout and use port `8080`.

## Start and enable

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now ranobelib-epub
```

## Status

```sh
systemctl status ranobelib-epub --no-pager
```

The service should be `active (running)`.

## Health check

```sh
curl -sS http://127.0.0.1:8080/health
```

Expected response:

```json
{"status":"ok"}
```

## Update after merge

```sh
cd /srv/repos/ranobelib-epub
git status --short
git pull --ff-only
source .venv/bin/activate
python -m pip install -e .
sudo systemctl restart ranobelib-epub
systemctl status ranobelib-epub --no-pager
curl -sS http://127.0.0.1:8080/health
```

Always restart the service after pulling new code so Uvicorn loads the updated Python modules.

## Logs

Follow logs:

```sh
journalctl -u ranobelib-epub -f
```

Recent logs:

```sh
journalctl -u ranobelib-epub -n 100 --no-pager
```

## Stop and restart

```sh
sudo systemctl restart ranobelib-epub
sudo systemctl stop ranobelib-epub
sudo systemctl start ranobelib-epub
```

## Manual troubleshooting run

Use manual foreground run only for short debugging. Stop the service first:

```sh
sudo systemctl stop ranobelib-epub
cd /srv/repos/ranobelib-epub
source .venv/bin/activate
uvicorn ranobelib_epub.app:app --port 8080
```

Stop the foreground process, then start systemd again:

```sh
sudo systemctl start ranobelib-epub
```

## Smoke checklist

After an update, check:

- the health endpoint responds on port `8080`;
- the web UI opens;
- a title URL opens the Russian build page;
- a single-volume branch shows quick range actions such as `Собрать главы 1–100` and `Собрать главы 101–200`;
- ordinary single-volume branches do not show confusing primary `Том от` / `Том до` filters;
- a small chapter range builds and downloads;
- the `Остановить` button cancels an active build and the page recovers;
- a cancelled job does not download an EPUB;
- a newly built EPUB table of contents does not append `.1` to unnamed ordinary chapters;
- a second simultaneous build attempt shows the Russian busy message;
- generated EPUBs, temporary files, logs, screenshots, and local debugging artifacts are not left in the repository checkout.

## Notes

The service is intentionally lightweight and uses one active build by default. If more parallelism is needed later, make that a separate code/configuration change and test it carefully on the VPS.
