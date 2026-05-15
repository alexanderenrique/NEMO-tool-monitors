from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tool_monitors", "0003_monitor_column"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="monitor",
            name="monitor_category",
        ),
        migrations.DeleteModel(
            name="MonitorCategory",
        ),
    ]
