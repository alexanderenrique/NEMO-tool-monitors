from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tool_monitors", "0004_remove_monitor_category"),
    ]

    operations = [
        migrations.AlterField(
            model_name="monitor",
            name="description",
            field=models.TextField(
                blank=True,
                help_text="Optional description of what this monitor tracks. HTML may be used (for example for links); shown at the top of the monitor details page.",
                null=True,
            ),
        ),
    ]
