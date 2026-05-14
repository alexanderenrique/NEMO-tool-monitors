from django.core.validators import validate_email

from NEMO.decorators import customization
from NEMO.views.customization import CustomizationBase


@customization(key="tool_monitors", title="Tool monitor data")
class MonitorCustomization(CustomizationBase):
    variables = {
        "monitor_default_daterange": "",
        "monitor_default_refresh_rate": "0",
        "monitor_alert_emails": "",
        "monitor_format_millisecond": "",
        "monitor_format_second": "",
        "monitor_format_minute": "",
        "monitor_format_hour": "",
        "monitor_format_day": "",
        "monitor_format_week": "",
        "monitor_format_month": "",
        "monitor_format_quarter": "",
        "monitor_format_year": "",
    }

    def validate(self, name, value):
        if name == "monitor_alert_emails":
            recipients = tuple([e for e in value.split(",") if e])
            for email in recipients:
                validate_email(email)
