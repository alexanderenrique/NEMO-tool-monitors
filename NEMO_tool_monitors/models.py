from __future__ import annotations

import datetime
import random
from logging import getLogger
from typing import List, Optional

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.safestring import mark_safe

from NEMO_tool_monitors.customizations import MonitorCustomization
from NEMO.constants import CHAR_FIELD_MEDIUM_LENGTH
from NEMO.evaluators import evaluate_boolean_expression
from NEMO.fields import MultiEmailField
from NEMO.models import BaseModel, Tool, User
from NEMO.typing import QuerySetType
from NEMO.utilities import EmailCategory, format_datetime, get_email_from_settings, send_mail

models_logger = getLogger(__name__)


class MonitorCategory(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text="The name for this monitor category")
    parent = models.ForeignKey(
        "MonitorCategory", related_name="children", null=True, blank=True, on_delete=models.SET_NULL
    )

    def is_leaf(self):
        return not self.children.exists()

    def all_children(self) -> List:
        if not self.children.exists():
            return []
        all_children = []
        for child in self.children.all():
            all_children.extend([child, *child.all_children()])
        return all_children

    def ancestors(self, include_self: bool = False) -> List:
        if not self.parent:
            return []
        ancestors = [*self.parent.ancestors(False), self.parent]
        if include_self:
            ancestors.append(self)
        return ancestors

    def alert_triggered(self):
        for monitor in self.monitor_set.all():
            if monitor.alert_triggered():
                return True
        for child in self.children.all():
            if child.alert_triggered():
                return True
        return False

    def __str__(self):
        return self.name if not self.parent else " | ".join([anc.name for anc in self.ancestors(include_self=True)])

    class Meta:
        verbose_name_plural = "Monitor categories"
        ordering = ["name"]


class Monitor(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH)
    visible = models.BooleanField(
        default=True, help_text="Specifies whether this monitor is visible in the monitor dashboard"
    )
    tool = models.ForeignKey(
        Tool,
        on_delete=models.CASCADE,
        related_name="monitors",
        help_text="The tool that this monitor reports data for.",
    )
    monitor_category = models.ForeignKey(MonitorCategory, blank=True, null=True, on_delete=models.SET_NULL)
    data_label = models.CharField(
        blank=True, null=True, max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text="Label for graph and table data"
    )
    data_prefix = models.CharField(
        blank=True, null=True, max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text="Prefix for monitor data values"
    )
    data_suffix = models.CharField(
        blank=True, null=True, max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text="Suffix for monitor data values"
    )
    description = models.TextField(
        blank=True, null=True, help_text="Optional description of what this monitor tracks."
    )
    last_read = models.DateTimeField(null=True, blank=True)
    last_value = models.FloatField(null=True, blank=True)

    def last_value_display(self):
        return display_monitor_value(self, self.last_value)

    def alert_triggered(self) -> bool:
        for alert_qs in MonitorAlert.monitor_alert_filter(monitor=self):
            if alert_qs.filter(triggered_on__isnull=False).exists():
                return True
        return False

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["tool__name", "name"]


class MonitorData(BaseModel):
    monitor = models.ForeignKey(Monitor, on_delete=models.CASCADE)
    value = models.FloatField()
    created_date = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text="The timestamp the data point represents (e.g. measurement time). Editable.",
    )
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="monitor_data_created",
        help_text="The user who originally uploaded this data point.",
    )
    created_on = models.DateTimeField(
        auto_now_add=True, help_text="The server timestamp when this data point was uploaded."
    )
    updated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="monitor_data_updated",
        help_text="The user who last edited this data point.",
    )
    updated_on = models.DateTimeField(auto_now=True, help_text="The server timestamp when this data point was last edited.")
    notes = models.TextField(
        blank=True,
        default="",
        help_text="Optional comment about this measurement (not plotted on the chart).",
    )

    def display_value(self):
        return display_monitor_value(self.monitor, self.value)

    class Meta:
        verbose_name_plural = "Monitor data"
        ordering = ["-created_date"]
        permissions = [("upload_monitor_data", "Can upload tool monitor data")]


@receiver(post_save, sender=MonitorData)
def monitor_data_post_save(sender, instance: MonitorData, created, **kwargs):
    from NEMO_tool_monitors.alerts import process_alerts

    monitor = instance.monitor
    latest = MonitorData.objects.filter(monitor=monitor).order_by("-created_date").first()
    if latest:
        monitor.last_read = latest.created_date
        monitor.last_value = latest.value
        monitor.save(update_fields=["last_read", "last_value"])
    process_alerts(monitor, instance)


class MonitorAlertLog(BaseModel):
    monitor = models.ForeignKey(Monitor, on_delete=models.CASCADE)
    time = models.DateTimeField(auto_now_add=True)
    value = models.FloatField(null=True, blank=True)
    reset = models.BooleanField(default=False)
    condition = models.TextField(null=True, blank=True)
    no_data = models.BooleanField(default=False)

    def description(self):
        return get_alert_description(self.time, self.reset, self.condition, self.no_data, self.value)

    class Meta:
        ordering = ["-time"]


class MonitorAlert(BaseModel):
    enabled = models.BooleanField(default=True)
    monitor = models.ForeignKey(Monitor, on_delete=models.CASCADE)
    trigger_no_data = models.BooleanField(
        default=False, help_text="Check this box to trigger this alert when no data is available"
    )
    trigger_condition = models.TextField(
        null=True,
        blank=True,
        help_text=mark_safe(
            "The trigger condition for this alert. The monitor value is available as a variable named "
            "<b>value</b>. e.g. value == 42 or value > 42."
        ),
    )
    triggered_on = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def _reset_alert(self, alert_time, value):
        if self.triggered_on:
            self.set_alert_time(time=None)
            self.log_alert(alert_time, reset=True, value=value)
            self.reset_alert(alert_time, value)

    def _trigger_alert(self, alert_time, value):
        if not self.triggered_on:
            self.set_alert_time(time=alert_time)
            self.log_alert(alert_time, reset=False, value=value)
            self.trigger_alert(alert_time, value)

    def clean(self):
        if not self.trigger_condition and not self.trigger_no_data:
            raise ValidationError(
                {
                    "trigger_condition": "Please enter a trigger condition or set this alert to trigger when there is no data"
                }
            )
        if self.trigger_condition:
            value = random.uniform(0, 100)
            try:
                evaluate_boolean_expression(self.trigger_condition, value=value)
            except Exception as e:
                raise ValidationError({"trigger_condition": str(e)})

    def set_alert_time(self, time: Optional[datetime.datetime]):
        self.triggered_on = time
        self.save()

    def log_alert(self, time: datetime.datetime, reset: bool = False, value: float = None):
        MonitorAlertLog.objects.create(
            time=time,
            condition=self.trigger_condition,
            monitor=self.monitor,
            value=value,
            reset=reset,
            no_data=self.trigger_no_data,
        )

    def process(self, monitor_data: MonitorData = None):
        now = timezone.now()
        value: float = monitor_data.value if monitor_data else None
        if self.trigger_condition and self.trigger_no_data:
            if value is None or evaluate_boolean_expression(self.trigger_condition, value=value):
                self._trigger_alert(now, value)
            else:
                self._reset_alert(now, value)
        elif self.trigger_condition:
            if value is not None:
                if evaluate_boolean_expression(self.trigger_condition, value=value):
                    self._trigger_alert(now, value)
                else:
                    self._reset_alert(now, value)
        else:
            if value is None:
                self._trigger_alert(now, value)
            else:
                self._reset_alert(now, value)

    def reset_alert(self, alert_time: datetime.datetime, value: float = None):
        pass

    def trigger_alert(self, alert_time: datetime.datetime, value: float = None):
        pass

    @classmethod
    def monitor_alert_filter(cls, enabled=True, monitor=None) -> List[QuerySetType["MonitorAlert"]]:
        monitor_alert_qs = []
        for sub_class in cls.__subclasses__():
            sub_filter = sub_class.objects.all()
            if enabled is not None:
                sub_filter = sub_filter.filter(enabled=enabled)
            if monitor:
                sub_filter = sub_filter.filter(monitor=monitor)
            monitor_alert_qs.append(sub_filter)
        return monitor_alert_qs


class MonitorAlertEmail(MonitorAlert):
    additional_emails = MultiEmailField(
        null=True,
        blank=True,
        help_text="Additional email address to contact when this alert is triggered. A comma-separated list can be used.",
    )

    def reset_alert(self, alert_time: datetime.datetime, value: float = None):
        subject = f"Alert reset for {self.monitor.name}"
        message = get_alert_description(alert_time, True, self.trigger_condition, self.trigger_no_data, value)
        self.send(subject, message)

    def trigger_alert(self, alert_time: datetime.datetime, value: float = None):
        subject = f"Alert triggered for {self.monitor.name}"
        message = get_alert_description(alert_time, False, self.trigger_condition, self.trigger_no_data, value)
        self.send(subject, message)

    def send(self, subject, message):
        email_to = MonitorCustomization.get("monitor_alert_emails")
        recipients = [e for e in email_to.split(",") if e]
        if self.additional_emails:
            recipients.extend(self.additional_emails)
        if recipients:
            send_mail(
                subject=subject,
                content=message,
                from_email=get_email_from_settings(),
                to=recipients,
                email_category=EmailCategory.GENERAL,
            )


def get_alert_description(time, reset: bool, condition: str, no_data: bool, value: float):
    if condition and value is not None:
        if reset:
            trigger_reason = f'the value ({value}) didn\'t meet the alert condition: "{condition}" anymore'
        else:
            trigger_reason = f'the condition: "{condition}" was met with value={value}'
    elif no_data and value is None:
        trigger_reason = "there was no data"
    elif value is not None and reset:
        trigger_reason = f"the monitor sent back value={value}"
    else:
        trigger_reason = None
    alert_description = f"This alert was {'reset' if reset else 'triggered'} on {format_datetime(time)}"
    if trigger_reason:
        alert_description += f" because {trigger_reason}."
    return alert_description


def display_monitor_value(monitor: Monitor, value: float) -> str:
    if value is None:
        return ""
    prefix = f"{monitor.data_prefix} " if monitor.data_prefix else ""
    suffix = f" {monitor.data_suffix}" if monitor.data_suffix else ""
    return f"{prefix}{value}{suffix}"
