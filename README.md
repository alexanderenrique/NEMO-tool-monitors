# NEMO Tool Monitors

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Plugin for NEMO that lets privileged users attach **monitor data** (numeric data points)
to NEMO tools and review the values via a "Monitors" page that mirrors the look of the
NEMO Sensors plugin. Each monitor belongs to a tool and has its own table of data points
(timestamp, value, who uploaded it). Data can be added one point at a time or bulk-uploaded
via CSV. Existing data points are editable.

## Features

- One "Monitors" page that lists tools that have monitors.
- Each tool can have any number of named monitors with chart, data, and alert tabs.
- Data points record `created_by` / `created_on` and `updated_by` / `updated_on`.
- Bulk CSV upload (two-column `timestamp,value`) and single-point web form on each monitor’s **Upload** tab.
- **Quick add a data point** from the per-tool page (`/tool_monitors/tool/<tool_id>/`) when you have upload permission.
- Inline-editable data table for privileged users (monitor **Data** tab).
- **Monitor definitions** (which tracks exist for a tool) are created and edited in **Django administration** by staff, not from the public tool listing.
- Optional email alerts when a value meets a condition or no data arrives.
- REST API endpoints for every model under `tool_monitors/...`.

## Installation

```bash
pip install NEMO-tool-monitors
```

In `settings.py` add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    "...",
    "NEMO_tool_monitors.apps.ToolMonitorsConfig",
    "...",
]
```

Run migrations:

```bash
python manage.py migrate tool_monitors
```

## Permissions

A single Django permission, **`tool_monitors.upload_monitor_data`** ("Can upload tool monitor data"),
controls who may add, edit, or delete **monitor data points** (including CSV upload, the per-tool quick-add form, and the monitor Upload/Data tabs). Assign it to users or
groups via Django admin (Auth -> Users / Groups -> Permissions). Read access to the dashboard,
chart, data, and alert tabs is available to any authenticated user.

Creating, editing, or deleting **monitor definitions** (the monitor records attached to tools) through the web app is limited to **staff** users (`is_staff`); the same operations are available in Django admin under **Tool monitors** for staff.

## URLs

Paths are relative to your NEMO site root (the same way sensors use `/sensors/`).

| Purpose | Path |
|--------|------|
| Monitors dashboard | `/tool_monitors/` |
| Monitors for one tool | `/tool_monitors/tool/<tool_id>/` |
| Monitor detail (default tab: chart) | `/monitor_details/<monitor_id>/` |
| Chart, data table, alert log, or upload tab | `/monitor_details/<monitor_id>/chart/`, `/data/`, `/alert/`, `/upload/` |
| Chart/table JSON (used by the detail page) | `/monitor_chart_data/<monitor_id>/` |
| Export CSV | `/export_monitor_data/<monitor_id>/` |
| Upload hub (pick tool and monitor; requires upload permission) | `/tool_monitors/upload/` |

The **upload** tab and `/tool_monitors/upload/` require **`tool_monitors.upload_monitor_data`**.

## Local development

A helper script is provided to build a wheel and install it directly into a local
`nemo-ce` checkout (default path: `/Users/adenton/Desktop/nemo-ce-alex`):

```bash
./scripts/dev_reinstall.sh                 # build, copy to NEMO/plugins, pip install into NEMO venv, migrate
./scripts/dev_reinstall.sh --restart       # also restart the Django dev server
./scripts/dev_reinstall.sh --nemo-path /path/to/nemo-ce
```

The script **pip-installs** the wheel into your NEMO project’s **venv** (if `venv/` or `.venv/` exists under the NEMO checkout). If you run `manage.py` with a **different** interpreter (for example **conda** `python` while pip targeted `nemo-ce-alex/venv`), imports still fail.

The script also patches **that NEMO checkout’s `manage.py`** once so `NEMO/plugins` is on `sys.path`—then the copied `NEMO_tool_monitors` package loads with **any** Python, including conda, without a matching `pip install`.

Use `--skip-pip` if you only want the copy + `manage.py` path hook (after the hook exists).

See [scripts/dev_reinstall.sh](scripts/dev_reinstall.sh) for all options.

## Tests

```bash
python run_tests.py
```
