from django.urls import path, re_path

from NEMO.urls import router, sort_urls

from NEMO_tool_monitors import api, views

router.register(r"tool_monitors/monitors", api.MonitorViewSet)
router.register(r"tool_monitors/monitor_data", api.MonitorDataViewSet)
router.register(r"tool_monitors/monitor_alert_emails", api.MonitorAlertEmailViewSet)
router.register(r"tool_monitors/monitor_alert_logs", api.MonitorAlertLogViewSet)
router.registry.sort(key=sort_urls)


urlpatterns = [
    path("tool_monitors/", views.monitors_dashboard, name="tool_monitors"),
    path(
        "tool_monitors/category/<path:category_path>/",
        views.monitors_dashboard,
        name="tool_monitors_category",
    ),
    path("tool_monitors/upload/", views.monitors_upload_hub, name="tool_monitors_upload"),
    path("tool_monitors/tool/<int:tool_id>/", views.tool_monitors_for_tool, name="tool_monitors_for_tool"),
    path("monitor_details/<int:monitor_id>/", views.monitor_details, name="monitor_details"),
    re_path(
        r"monitor_details/(?P<monitor_id>\d+)/(?P<tab>chart|data|alert|upload)/$",
        views.monitor_details,
        name="monitor_details",
    ),
    path("monitor_chart_data/<int:monitor_id>/", views.monitor_chart_data, name="monitor_chart_data"),
    path("monitor_alert_log/<int:monitor_id>/", views.monitor_alert_log, name="monitor_alert_log"),
    path("export_monitor_data/<int:monitor_id>/", views.export_monitor_data, name="export_monitor_data"),
    path(
        "monitor/<int:monitor_id>/data/add/",
        views.add_monitor_data,
        name="add_monitor_data",
    ),
    path(
        "monitor/<int:monitor_id>/data/upload_csv/",
        views.upload_monitor_data_csv,
        name="upload_monitor_data_csv",
    ),
    path(
        "monitor/<int:monitor_id>/data/<int:data_id>/edit/",
        views.edit_monitor_data,
        name="edit_monitor_data",
    ),
    path(
        "monitor/<int:monitor_id>/data/<int:data_id>/delete/",
        views.delete_monitor_data,
        name="delete_monitor_data",
    ),
    path("monitor/create/<int:tool_id>/", views.create_monitor, name="create_monitor"),
    path("monitor/<int:monitor_id>/edit/", views.edit_monitor, name="edit_monitor"),
    path("monitor/<int:monitor_id>/delete/", views.delete_monitor, name="delete_monitor"),
]
