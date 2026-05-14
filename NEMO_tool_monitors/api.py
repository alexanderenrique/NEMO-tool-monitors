from NEMO.serializers import ModelSerializer
from NEMO.views.api import ModelViewSet, boolean_filters, datetime_filters, key_filters, number_filters, string_filters
from drf_excel.mixins import XLSXFileMixin
from rest_flex_fields.serializers import FlexFieldsSerializerMixin
from rest_framework.serializers import DateTimeField
from rest_framework.viewsets import ReadOnlyModelViewSet

from NEMO_tool_monitors.models import (
    Monitor,
    MonitorAlertEmail,
    MonitorAlertLog,
    MonitorCategory,
    MonitorData,
)


class MonitorCategorySerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = MonitorCategory
        fields = "__all__"
        expandable_fields = {
            "parent": "NEMO_tool_monitors.api.MonitorCategorySerializer",
        }


class MonitorSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = Monitor
        fields = "__all__"
        expandable_fields = {
            "tool": "NEMO.serializers.ToolSerializer",
            "monitor_category": "NEMO_tool_monitors.api.MonitorCategorySerializer",
        }


class MonitorDataSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    created_date = DateTimeField()
    created_on = DateTimeField(read_only=True)
    updated_on = DateTimeField(read_only=True)

    class Meta:
        model = MonitorData
        fields = "__all__"
        read_only_fields = ("created_on", "updated_on")
        expandable_fields = {
            "monitor": "NEMO_tool_monitors.api.MonitorSerializer",
            "created_by": "NEMO.serializers.UserSerializer",
            "updated_by": "NEMO.serializers.UserSerializer",
        }


class MonitorAlertEmailSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = MonitorAlertEmail
        fields = "__all__"
        expandable_fields = {
            "monitor": "NEMO_tool_monitors.api.MonitorSerializer",
        }


class MonitorAlertLogSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = MonitorAlertLog
        fields = "__all__"
        expandable_fields = {
            "monitor": "NEMO_tool_monitors.api.MonitorSerializer",
        }


class MonitorCategoryViewSet(ModelViewSet):
    filename = "monitor_categories"
    queryset = MonitorCategory.objects.all()
    serializer_class = MonitorCategorySerializer
    filterset_fields = {
        "id": key_filters,
        "name": string_filters,
        "parent": key_filters,
    }


class MonitorViewSet(ModelViewSet):
    filename = "monitors"
    queryset = Monitor.objects.all()
    serializer_class = MonitorSerializer
    filterset_fields = {
        "id": key_filters,
        "name": string_filters,
        "visible": boolean_filters,
        "tool": key_filters,
        "monitor_category": key_filters,
        "data_label": string_filters,
        "data_prefix": string_filters,
        "data_suffix": string_filters,
        "last_read": datetime_filters,
        "last_value": number_filters,
    }


class MonitorDataViewSet(ModelViewSet):
    filename = "monitor_data"
    queryset = MonitorData.objects.all()
    serializer_class = MonitorDataSerializer
    filterset_fields = {
        "id": key_filters,
        "monitor": key_filters,
        "created_date": datetime_filters,
        "created_on": datetime_filters,
        "updated_on": datetime_filters,
        "created_by": key_filters,
        "updated_by": key_filters,
        "value": number_filters,
        "notes": string_filters,
    }
    filename = "monitor_alert_emails"
    queryset = MonitorAlertEmail.objects.all()
    serializer_class = MonitorAlertEmailSerializer
    filterset_fields = {
        "id": key_filters,
        "enabled": boolean_filters,
        "monitor": key_filters,
        "trigger_no_data": boolean_filters,
        "trigger_condition": string_filters,
        "triggered_on": datetime_filters,
        "additional_emails": string_filters,
    }


class MonitorAlertLogViewSet(XLSXFileMixin, ReadOnlyModelViewSet):
    filename = "monitor_alert_logs"
    queryset = MonitorAlertLog.objects.all()
    serializer_class = MonitorAlertLogSerializer
    filterset_fields = {
        "id": key_filters,
        "monitor": key_filters,
        "time": datetime_filters,
        "value": number_filters,
        "reset": boolean_filters,
        "condition": string_filters,
        "no_data": boolean_filters,
    }
