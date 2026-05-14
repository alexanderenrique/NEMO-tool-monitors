from logging import getLogger

from NEMO_tool_monitors.models import Monitor, MonitorAlert, MonitorData

alerts_logger = getLogger(__name__)


def process_alerts(monitor: Monitor, monitor_data: MonitorData = None):
    """Run every enabled alert on the most-recent value for the monitor."""
    try:
        monitor_alerts = []
        for sub_class in MonitorAlert.__subclasses__():
            monitor_alerts.extend(sub_class.objects.filter(enabled=True, monitor=monitor))
        for alert in monitor_alerts:
            alert.process(monitor_data)
    except Exception as e:
        alerts_logger.error(e)
