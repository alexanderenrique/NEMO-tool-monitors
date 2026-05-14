from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tool_monitors", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitordata",
            name="notes",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Optional comment about this measurement (not plotted on the chart).",
            ),
        ),
    ]
