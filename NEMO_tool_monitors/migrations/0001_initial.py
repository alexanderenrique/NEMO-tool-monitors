import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import NEMO.fields


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("NEMO", "0001_version_1_0_0"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MonitorCategory",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "name",
                    models.CharField(help_text="The name for this monitor category", max_length=255),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="children",
                        to="tool_monitors.monitorcategory",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "Monitor categories",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="Monitor",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                (
                    "visible",
                    models.BooleanField(
                        default=True,
                        help_text="Specifies whether this monitor is visible in the monitor dashboard",
                    ),
                ),
                (
                    "data_label",
                    models.CharField(
                        blank=True, help_text="Label for graph and table data", max_length=255, null=True
                    ),
                ),
                (
                    "data_prefix",
                    models.CharField(
                        blank=True, help_text="Prefix for monitor data values", max_length=255, null=True
                    ),
                ),
                (
                    "data_suffix",
                    models.CharField(
                        blank=True, help_text="Suffix for monitor data values", max_length=255, null=True
                    ),
                ),
                (
                    "description",
                    models.TextField(
                        blank=True, help_text="Optional description of what this monitor tracks.", null=True
                    ),
                ),
                ("last_read", models.DateTimeField(blank=True, null=True)),
                ("last_value", models.FloatField(blank=True, null=True)),
                (
                    "monitor_category",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="tool_monitors.monitorcategory",
                    ),
                ),
                (
                    "tool",
                    models.ForeignKey(
                        help_text="The tool that this monitor reports data for.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="monitors",
                        to="NEMO.tool",
                    ),
                ),
            ],
            options={
                "ordering": ["tool__name", "name"],
            },
        ),
        migrations.CreateModel(
            name="MonitorData",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("value", models.FloatField()),
                (
                    "created_date",
                    models.DateTimeField(
                        db_index=True,
                        default=django.utils.timezone.now,
                        help_text="The timestamp the data point represents (e.g. measurement time). Editable.",
                    ),
                ),
                (
                    "created_on",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="The server timestamp when this data point was uploaded.",
                    ),
                ),
                (
                    "updated_on",
                    models.DateTimeField(
                        auto_now=True,
                        help_text="The server timestamp when this data point was last edited.",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        help_text="The user who originally uploaded this data point.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="monitor_data_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        help_text="The user who last edited this data point.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="monitor_data_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "monitor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="tool_monitors.monitor",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "Monitor data",
                "ordering": ["-created_date"],
                "permissions": [("upload_monitor_data", "Can upload tool monitor data")],
            },
        ),
        migrations.CreateModel(
            name="MonitorAlertLog",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("time", models.DateTimeField(auto_now_add=True)),
                ("value", models.FloatField(blank=True, null=True)),
                ("reset", models.BooleanField(default=False)),
                ("condition", models.TextField(blank=True, null=True)),
                ("no_data", models.BooleanField(default=False)),
                (
                    "monitor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="tool_monitors.monitor",
                    ),
                ),
            ],
            options={
                "ordering": ["-time"],
            },
        ),
        migrations.CreateModel(
            name="MonitorAlertEmail",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=True)),
                (
                    "trigger_no_data",
                    models.BooleanField(
                        default=False,
                        help_text="Check this box to trigger this alert when no data is available",
                    ),
                ),
                (
                    "trigger_condition",
                    models.TextField(
                        blank=True,
                        help_text=(
                            "The trigger condition for this alert. The monitor value is available as a variable "
                            "named <b>value</b>. e.g. value == 42 or value > 42."
                        ),
                        null=True,
                    ),
                ),
                ("triggered_on", models.DateTimeField(blank=True, null=True)),
                (
                    "additional_emails",
                    NEMO.fields.MultiEmailField(
                        blank=True,
                        help_text=(
                            "Additional email address to contact when this alert is triggered. "
                            "A comma-separated list can be used."
                        ),
                        max_length=2000,
                        null=True,
                    ),
                ),
                (
                    "monitor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="tool_monitors.monitor",
                    ),
                ),
            ],
            options={"abstract": False},
        ),
    ]
