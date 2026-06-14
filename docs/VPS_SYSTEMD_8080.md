# VPS systemd operations on port 8080

This note records the current long-running VPS operation mode for `ranobelib-epub`.

Current runtime facts:

- repository: `/srv/repos/ranobelib-epub`;
- virtual environment: `/srv/repos/ranobelib-epub/.venv`;
- Linux user: `vlad`;
- service manager: `systemd`;
- service name: `ranobelib-epub`;
- HTTP port: `8080`.

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
- a small chapter range builds and downloads;
- a second simultaneous build attempt shows the Russian busy message;
- generated EPUBs, temporary files, logs, screenshots, and local debugging artifacts are not left in the repository checkout.

## Notes

The service is intentionally lightweight and uses one active build by default. If more parallelism is needed later, make that a separate code/configuration change and test it carefully on the VPS.
