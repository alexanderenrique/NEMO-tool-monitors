from django.apps import AppConfig


class ToolMonitorsConfig(AppConfig):
    name = "NEMO_tool_monitors"
    label = "tool_monitors"
    verbose_name = "Tool monitors"
    default_auto_field = "django.db.models.AutoField"

    def ready(self):
        from NEMO.plugins.utils import check_extra_dependencies

        check_extra_dependencies(self.name, ["NEMO", "NEMO-CE"])
