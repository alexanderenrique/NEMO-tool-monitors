from importlib.metadata import PackageNotFoundError

from django.apps import AppConfig

# Wheel / PyPI name from pyproject.toml [project].name — NOT the same as AppConfig.name
DISTRIBUTION_NAME = "NEMO-tool-monitors"


class ToolMonitorsConfig(AppConfig):
    name = "NEMO_tool_monitors"
    label = "tool_monitors"
    verbose_name = "Tool monitors"
    default_auto_field = "django.db.models.AutoField"

    def ready(self):
        try:
            from NEMO.plugins.utils import check_extra_dependencies
        except ImportError:
            return

        # get_extra_requires() looks up importlib.metadata.distribution(app_name).
        # That expects the *installed distribution* name (hyphenated PyPI name), not the
        # Python package path (NEMO_tool_monitors). When running only from NEMO/plugins
        # without pip installing the wheel into the active interpreter, the dist is absent
        # — skip the check instead of crashing.
        for dist_name in (DISTRIBUTION_NAME, "nemo-tool-monitors"):
            try:
                check_extra_dependencies(dist_name, ["NEMO", "NEMO-CE"])
                return
            except PackageNotFoundError:
                continue
