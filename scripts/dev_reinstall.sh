#!/bin/bash
# Development reinstall script for NEMO Tool Monitors plugin.
# Builds a wheel, copies the extracted package into a local nemo-ce checkout
# (default: /Users/adenton/Desktop/nemo-ce-alex), and runs Django migrations.
#
# Run from project root: ./scripts/dev_reinstall.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

NEMO_PATH="/Users/adenton/Desktop/nemo-ce-alex"
FORCE_REINSTALL=false
SKIP_TESTS=true
SKIP_BUILD=false
SKIP_PIP=false
BACKUP=true
RESTART_SERVER=false

print_status()  { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo "Options:"
    echo "  -n, --nemo-path PATH    Path to nemo-ce checkout (default: $NEMO_PATH)"
    echo "  -f, --force             Force overwrite the installed plugin dir"
    echo "  -s, --run-tests         Run plugin tests after install"
    echo "  -b, --skip-build        Reuse the existing dist/ wheel"
    echo "      --skip-pip          Do not pip-install the wheel (manage.py adds NEMO/plugins to sys.path so copy-only still imports)"
    echo "      --no-backup         Don't back up the existing plugin dir"
    echo "  -r, --restart           Restart Django dev server after install"
    echo "  -h, --help              Show this help"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--nemo-path)   NEMO_PATH="$2"; shift 2 ;;
        -f|--force)       FORCE_REINSTALL=true; shift ;;
        -s|--run-tests)   SKIP_TESTS=false; shift ;;
        -b|--skip-build)  SKIP_BUILD=true; shift ;;
        --skip-pip)       SKIP_PIP=true; shift ;;
        --no-backup)      BACKUP=false; shift ;;
        -r|--restart)     RESTART_SERVER=true; shift ;;
        -h|--help)        show_usage; exit 0 ;;
        *) print_error "Unknown option: $1"; show_usage; exit 1 ;;
    esac
done

[[ ! -d "$NEMO_PATH" ]] && { print_error "NEMO path not found: $NEMO_PATH"; exit 1; }

if [[ -f "$NEMO_PATH/manage.py" ]]; then
    NEMO_PROJECT_ROOT="$NEMO_PATH"
    NEMO_PLUGINS_DIR="$NEMO_PATH/NEMO/plugins"
elif [[ "$(basename "$NEMO_PATH")" == "plugins" ]]; then
    NEMO_PROJECT_ROOT="$(dirname "$(dirname "$NEMO_PATH")")"
    NEMO_PLUGINS_DIR="$NEMO_PATH"
else
    print_error "NEMO path must be a project root containing manage.py, or the NEMO/plugins dir"
    exit 1
fi

mkdir -p "$NEMO_PLUGINS_DIR"

DEV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DEV_DIR"

print_status "Project root:    $DEV_DIR"
print_status "NEMO project:    $NEMO_PROJECT_ROOT"
print_status "NEMO plugins:    $NEMO_PLUGINS_DIR"

# Pick the python interpreter to use for the NEMO side (migrations, restart)
PYTHON_CMD="python"
[[ -f "$NEMO_PROJECT_ROOT/.venv/bin/python" ]] && PYTHON_CMD="$NEMO_PROJECT_ROOT/.venv/bin/python"
[[ -f "$NEMO_PROJECT_ROOT/venv/bin/python"  ]] && PYTHON_CMD="$NEMO_PROJECT_ROOT/venv/bin/python"

# Clean build artifacts
if [[ "$SKIP_BUILD" == "false" ]]; then
    rm -rf build/ dist/ ./*.egg-info 2>/dev/null || true
    python -m pip install --upgrade pip setuptools wheel build -q
    python -m build || { print_error "Wheel build failed"; exit 1; }
fi

WHEEL_FILE=$(find dist/ -name "NEMO_tool_monitors*.whl" 2>/dev/null | head -1)
if [[ -z "$WHEEL_FILE" ]]; then
    WHEEL_FILE=$(find dist/ -name "*.whl" 2>/dev/null | head -1)
fi
[[ -z "$WHEEL_FILE" ]] && { print_error "No wheel found in dist/"; exit 1; }
print_status "Wheel:           $WHEEL_FILE"

# Back up the existing plugin dir if present
EXISTING_PLUGIN="$NEMO_PLUGINS_DIR/NEMO_tool_monitors"
if [[ "$BACKUP" == "true" ]] && [[ -d "$EXISTING_PLUGIN" ]]; then
    BACKUP_DIR="$NEMO_PROJECT_ROOT/tool_monitors_backup_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    cp -r "$EXISTING_PLUGIN" "$BACKUP_DIR/"
    print_success "Backup: $BACKUP_DIR"
fi

# Force-remove the installed plugin dir if requested or if a previous install exists
if [[ "$FORCE_REINSTALL" == "true" ]] || [[ -d "$EXISTING_PLUGIN" ]]; then
    rm -rf "$EXISTING_PLUGIN"
fi

# Remove any legacy NEMO_sensors install left over from when this plugin was renamed
rm -rf "$NEMO_PLUGINS_DIR/NEMO_sensors"

# Extract wheel into a temp dir then copy the package into NEMO/plugins
TEMP_DIR=$(mktemp -d)
unzip -q "$DEV_DIR/$WHEEL_FILE" -d "$TEMP_DIR"
EXTRACTED=$(find "$TEMP_DIR" -name "NEMO_tool_monitors" -type d | head -1)
if [[ -z "$EXTRACTED" ]]; then
    print_error "Could not find NEMO_tool_monitors inside the wheel"
    rm -rf "$TEMP_DIR"
    exit 1
fi
cp -r "$EXTRACTED" "$NEMO_PLUGINS_DIR/"
rm -rf "$TEMP_DIR"
print_success "Copied package to $NEMO_PLUGINS_DIR/NEMO_tool_monitors"

# NEMO's default manage.py does NOT put NEMO/plugins on sys.path (unlike the optional
# ../nemo-mqtt-bridge/src hook). Django must import NEMO_tool_monitors as a top-level
# package, so install the wheel into the NEMO project's venv.
WHEEL_ABS="$DEV_DIR/$WHEEL_FILE"
if [[ "$SKIP_PIP" == "false" ]]; then
    print_status "pip install wheel into NEMO venv ($PYTHON_CMD) …"
    (cd "$NEMO_PROJECT_ROOT" && "$PYTHON_CMD" -m pip install --force-reinstall "$WHEEL_ABS") \
        || { print_error "pip install failed"; exit 1; }
    print_success "Installed wheel into venv (import NEMO_tool_monitors works for manage.py)"
else
    print_warning "Skipped pip install; relying on NEMO/plugins on sys.path (see manage.py patch below)."
fi

# Ensure target NEMO's manage.py puts NEMO/plugins on sys.path. Otherwise `python manage.py`
# only works if the same interpreter that received `pip install` is used (e.g. conda vs venv mismatch).
MANAGE_PY="$NEMO_PROJECT_ROOT/manage.py"
if [[ -f "$MANAGE_PY" ]] && ! grep -q "_nemo_plugins_dir" "$MANAGE_PY"; then
    print_status "Patching $MANAGE_PY: prepend NEMO/plugins to sys.path (any Python can import drop-in plugins)"
    cp "$MANAGE_PY" "$MANAGE_PY.bak.$(date +%Y%m%d_%H%M%S)"
    python3 - "$MANAGE_PY" <<'PY'
import sys

path = sys.argv[1]
block = """

# Drop-in plugins under NEMO/plugins (e.g. NEMO_tool_monitors from NEMO-tool-monitors dev_reinstall.sh)
_nemo_plugins_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "NEMO", "plugins")
if os.path.isdir(_nemo_plugins_dir) and _nemo_plugins_dir not in sys.path:
    sys.path.insert(0, _nemo_plugins_dir)
"""
with open(path, "r") as f:
    text = f.read()
if "_nemo_plugins_dir" in text:
    print("manage.py already contains NEMO/plugins path hook.")
    sys.exit(0)
needle = (
    "if os.path.exists(_nemo_mqtt_src):\n"
    "    sys.path.insert(0, os.path.abspath(_nemo_mqtt_src))\n"
)
if needle in text:
    text = text.replace(needle, needle + block)
else:
    # No mqtt dev hook: insert after `import sys`
    insert_after = "import sys\n"
    if insert_after not in text:
        print("Could not find insertion point in manage.py; edit manually.", file=sys.stderr)
        sys.exit(1)
    text = text.replace(insert_after, insert_after + block, 1)
with open(path, "w") as f:
    f.write(text)
print("Patched manage.py.")
PY
    print_success "manage.py now adds NEMO/plugins to sys.path"
fi

# Make sure NEMO_tool_monitors is in INSTALLED_APPS (best-effort, idempotent).
SETTINGS_FILE="$NEMO_PROJECT_ROOT/resources/settings.py"
if [[ -f "$SETTINGS_FILE" ]] && ! grep -q "NEMO_tool_monitors" "$SETTINGS_FILE"; then
    print_status "Adding NEMO_tool_monitors.apps.ToolMonitorsConfig to INSTALLED_APPS in $SETTINGS_FILE"
    cp "$SETTINGS_FILE" "$SETTINGS_FILE.bak.$(date +%Y%m%d_%H%M%S)"
    python - "$SETTINGS_FILE" <<'PY'
import re
import sys
path = sys.argv[1]
with open(path, "r") as f:
    text = f.read()
needle = "INSTALLED_APPS = ["
if needle in text and "NEMO_tool_monitors" not in text:
    text = text.replace(
        needle,
        needle + "\n    \"NEMO_tool_monitors.apps.ToolMonitorsConfig\",",
        1,
    )
    with open(path, "w") as f:
        f.write(text)
    print("Added entry.")
else:
    print("INSTALLED_APPS not found or entry already present; please edit manually.")
PY
fi

# Run migrations in the NEMO project
(cd "$NEMO_PROJECT_ROOT" && $PYTHON_CMD manage.py migrate tool_monitors) \
    || print_warning "Migration command failed; you may need to run it manually."

# Run tests against the plugin source tree
if [[ "$SKIP_TESTS" == "false" ]] && [[ -f "$DEV_DIR/run_tests.py" ]]; then
    (cd "$DEV_DIR" && $PYTHON_CMD run_tests.py) || print_warning "Tests failed."
fi

if [[ "$RESTART_SERVER" == "true" ]]; then
    print_status "Restarting Django dev server (background)"
    pkill -f "manage.py runserver" 2>/dev/null || true
    (cd "$NEMO_PROJECT_ROOT" && nohup $PYTHON_CMD manage.py runserver &>/tmp/nemo_tool_monitors_runserver.log &)
    sleep 1
    print_success "Server restarted. Logs: /tmp/nemo_tool_monitors_runserver.log"
fi

print_success "Done. Plugin installed at $NEMO_PLUGINS_DIR/NEMO_tool_monitors"
