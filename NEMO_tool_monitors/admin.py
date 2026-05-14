from django import forms
from django.contrib import admin, messages
from django.contrib.admin import register
from django.contrib.admin.decorators import display
from django.urls import reverse
from django.utils.safestring import mark_safe

from NEMO_tool_monitors.models import (
    Monitor,
    MonitorAlertEmail,
    MonitorAlertLog,
    MonitorCategory,
    MonitorData,
)
from NEMO.typing import QuerySetType
from NEMO.utilities import new_model_copy


def duplicate_monitor_configuration(model_admin, request, queryset: QuerySetType[Monitor]):
    for monitor in queryset:
        original_name = monitor.name
        new_name = "Copy of " + monitor.name
        try:
            existing = Monitor.objects.filter(name=new_name, tool=monitor.tool)
            if existing.exists():
                messages.error(
                    request,
                    mark_safe(
                        f'There is already a copy of {original_name} as '
                        f'<a href="{reverse("admin:tool_monitors_monitor_change", args=[existing.first().id])}">{new_name}</a>. '
                        f'Change the copy\'s name and try again'
                    ),
                )
                continue
            new_monitor: Monitor = new_model_copy(monitor)
            new_monitor.name = new_name
            new_monitor.last_read = None
            new_monitor.last_value = None
            new_monitor.save()
            messages.success(
                request,
                mark_safe(
                    f'A duplicate of {original_name} has been made as '
                    f'<a href="{reverse("admin:tool_monitors_monitor_change", args=[new_monitor.id])}">{new_monitor.name}</a>'
                ),
            )
        except Exception as error:
            messages.error(
                request, f"{original_name} could not be duplicated because of the following error: {str(error)}"
            )


@admin.action(description="Hide selected monitors")
def hide_selected_monitors(model_admin, request, queryset: QuerySetType[Monitor]):
    for monitor in queryset:
        monitor.visible = False
        monitor.save(update_fields=["visible"])


@admin.action(description="Show selected monitors")
def show_selected_monitors(model_admin, request, queryset: QuerySetType[Monitor]):
    for monitor in queryset:
        monitor.visible = True
        monitor.save(update_fields=["visible"])


@admin.action(description="Disable selected alerts")
def disable_selected_alerts(model_admin, request, queryset: QuerySetType[MonitorAlertEmail]):
    for monitor_alert in queryset:
        monitor_alert.enabled = False
        monitor_alert.save(update_fields=["enabled"])


@admin.action(description="Enable selected alerts")
def enable_selected_alerts(model_admin, request, queryset: QuerySetType[MonitorAlertEmail]):
    for monitor_alert in queryset:
        monitor_alert.enabled = True
        monitor_alert.save(update_fields=["enabled"])


class MonitorAdminForm(forms.ModelForm):
    class Meta:
        model = Monitor
        fields = "__all__"


class MonitorCategoryAdminForm(forms.ModelForm):
    class Meta:
        model = MonitorCategory
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            children_ids = [child.id for child in self.instance.all_children()]
            if "parent" in self.fields:
                self.fields["parent"].queryset = MonitorCategory.objects.exclude(
                    id__in=[self.instance.pk, *children_ids]
                )


@register(MonitorCategory)
class MonitorCategoryAdmin(admin.ModelAdmin):
    form = MonitorCategoryAdminForm
    list_display = ("name", "get_parent", "get_children")

    @display(ordering="children", description="Children")
    def get_children(self, category: MonitorCategory) -> str:
        return mark_safe(
            ", ".join(
                [
                    f'<a href="{reverse("admin:tool_monitors_monitorcategory_change", args=[child.id])}">{child.name}</a>'
                    for child in category.children.all()
                ]
            )
        )

    @display(ordering="parent", description="Parent")
    def get_parent(self, category: MonitorCategory) -> str:
        if not category.parent:
            return ""
        return mark_safe(
            f'<a href="{reverse("admin:tool_monitors_monitorcategory_change", args=[category.parent.id])}">{category.parent.name}</a>'
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "parent":
            kwargs["queryset"] = MonitorCategory.objects.filter()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@register(Monitor)
class MonitorAdmin(admin.ModelAdmin):
    search_fields = ["name", "tool__name"]
    form = MonitorAdminForm
    list_display = (
        "id",
        "name",
        "tool",
        "visible",
        "monitor_category",
        "last_read",
        "last_value",
    )
    list_filter = (
        "visible",
        ("tool", admin.RelatedOnlyFieldListFilter),
        ("monitor_category", admin.RelatedOnlyFieldListFilter),
    )
    actions = [duplicate_monitor_configuration, hide_selected_monitors, show_selected_monitors]
    autocomplete_fields = ["tool"]
    readonly_fields = ["last_read", "last_value"]


@register(MonitorData)
class MonitorDataAdmin(admin.ModelAdmin):
    list_display = (
        "created_date",
        "monitor",
        "value",
        "get_display_value",
        "created_by",
        "created_on",
        "updated_by",
        "updated_on",
    )
    date_hierarchy = "created_date"
    list_filter = (
        ("monitor", admin.RelatedOnlyFieldListFilter),
        ("monitor__monitor_category", admin.RelatedOnlyFieldListFilter),
        ("created_by", admin.RelatedOnlyFieldListFilter),
    )
    autocomplete_fields = ["monitor", "created_by", "updated_by"]
    readonly_fields = ["created_on", "updated_on"]
    search_fields = ("monitor__name", "monitor__tool__name", "created_by__username", "notes")

    @display(ordering="monitor__data_prefix", description="Display value")
    def get_display_value(self, obj: MonitorData):
        return obj.display_value()

    def save_model(self, request, obj: MonitorData, form, change):
        if not change and not obj.created_by_id:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@register(MonitorAlertEmail)
class MonitorAlertEmailAdmin(admin.ModelAdmin):
    list_display = ("monitor", "enabled", "trigger_condition", "trigger_no_data", "additional_emails", "triggered_on")
    actions = [disable_selected_alerts, enable_selected_alerts]
    autocomplete_fields = ["monitor"]


@register(MonitorAlertLog)
class MonitorAlertLogAdmin(admin.ModelAdmin):
    list_display = ["id", "time", "monitor", "reset", "value"]
    list_filter = [("monitor", admin.RelatedOnlyFieldListFilter), "value", "reset"]
    date_hierarchy = "time"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
