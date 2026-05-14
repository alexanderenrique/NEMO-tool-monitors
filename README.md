# NEMO Tool Monitors

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Plugin for NEMO that lets privileged users attach **monitor data** (numeric data points)
to NEMO tools and review the values via a "Monitors" page that mirrors the look of the
NEMO Sensors plugin. Each monitor belongs to a tool and has its own table of data points
(timestamp, value, who uploaded it). Data can be added one point at a time or bulk-uploaded
via CSV. Existing data points are editable.

## Features

- One "Monitors" page that browses nested categories and tools that have monitors.
- Each tool can have any number of named monitors with chart, data, and alert tabs.
- Data points record `created_by` / `created_on` and `updated_by` / `updated_on`.
- Bulk CSV upload (two-column `timestamp,value`) and single-point web form.
- Inline-editable data table for privileged users.
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
controls who may add, edit, or delete monitor data and monitors themselves. Assign it to users or
groups via Django admin (Auth -> Users / Groups -> Permissions). Read access to the dashboard,
chart, data, and alert tabs is available to any authenticated user.

## Local development

A helper script is provided to build a wheel and install it directly into a local
`nemo-ce` checkout (default path: `/Users/adenton/Desktop/nemo-ce-alex`):

```bash
./scripts/dev_reinstall.sh                 # build + copy + migrate
./scripts/dev_reinstall.sh --restart       # also restart the Django dev server
./scripts/dev_reinstall.sh --nemo-path /path/to/nemo-ce
```

See [scripts/dev_reinstall.sh](scripts/dev_reinstall.sh) for all options.

## Tests

```bash
python run_tests.py
```
