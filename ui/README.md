# ui/

The local web UI for the coach workflow. Plain-Python `http.server` based
(no Flask / FastAPI dependency) so the platform stays lightweight and the
UI can be served by `coach serve` without an extra runtime.

## Layout

```
ui/
├── server.py        # The HTTP server, request routing, and HTML rendering
├── assets/          # Static assets served by the UI
│   ├── icon.png
│   └── illustrations/
└── tests/
    └── test_server.py
```

## What lives here vs in coach/

The package owns everything specific to the web UI — request handling,
HTML rendering, asset serving, stage-step UI logic. It depends on `coach.*`
and the step packages (`learn`, `build`, `verify`) the way any other
caller does: through `WeekOrchestrator` and the stage instances mounted
on it. The UI does not reach into stage internals or persistence directly.

What stays in `coach/`:

- The CLI (`coach.cli`) — including the `coach serve` command that spawns
  this UI server. The CLI imports `serve_ui`, `DEFAULT_UI_HOST`, and
  `DEFAULT_UI_PORT` from `ui.server`.
- The reload watcher (`coach.cli.snapshot_reload_state`) — it watches the
  `ui/` directory so source edits trigger a server restart, just like it
  watches the other top-level packages.

## Running

The UI is started via the CLI:

```bash
coach serve            # defaults: 127.0.0.1:4010
coach serve --host 0.0.0.0 --port 8080
coach serve --no-reload   # disable the auto-restart loop
```

The default reload loop watches `coach/`, `ui/`, `learn/`, `build/`,
`verify/`, `curriculum/`, plus `coach.config.json`, `pyproject.toml`, and
`.env`. Edits trigger a clean restart of the UI process; runtime state
under `state/` is intentionally excluded so a change to the ledger
doesn't bounce the server mid-week.

## Tests

`ui/tests/test_server.py` exercises rendering, action routing, and the
topic-chat streaming endpoint. Tests live next to the server they cover.
