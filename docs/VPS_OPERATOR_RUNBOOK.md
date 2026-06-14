# VPS Operator Runbook

This older operator runbook has been superseded for the current VPS deployment.

Use the current port `8080` systemd operations note instead:

- [docs/VPS_SYSTEMD_8080.md](VPS_SYSTEMD_8080.md)

Current runtime summary:

- repository: `/srv/repos/ranobelib-epub`;
- virtual environment: `/srv/repos/ranobelib-epub/.venv`;
- service manager: `systemd`;
- service name: `ranobelib-epub`;
- service port: `8080`.

Do not use older examples that mention port `8000` for the current VPS service.
