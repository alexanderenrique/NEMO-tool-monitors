from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from typing import List, Optional, Set, Tuple

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Prefetch
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from NEMO.decorators import disable_session_expiry_refresh
from NEMO.models import Tool
from NEMO.typing import QuerySetType
from NEMO.utilities import (
    BasicDisplayTable,
    export_format_datetime,
    extract_times,
    format_datetime,
    slugify_underscore,
)

from NEMO_tool_monitors.customizations import MonitorCustomization
from NEMO_tool_monitors.models import (
    Monitor,
    MonitorAlertLog,
    MonitorCategory,
    MonitorData,
)

UPLOAD_PERMISSION = "tool_monitors.upload_monitor_data"

CSV_DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y",
    "%Y-%m-%d",
]


def _can_upload(user) -> bool:
    return user.is_authenticated and user.has_perm(UPLOAD_PERMISSION)


def _post_add_data_redirect(request, monitor: Monitor) -> str:
    """Prefer returning to the tool monitors page when that form submitted return_to_tool."""
    raw = request.POST.get("return_to_tool")
    if raw is None or raw == "":
        return reverse("monitor_details", args=[monitor.pk, "data"])
    try:
        tool_id = int(raw)
    except (TypeError, ValueError):
        return reverse("monitor_details", args=[monitor.pk, "data"])
    if tool_id != monitor.tool_id:
        return reverse("monitor_details", args=[monitor.pk, "data"])
    return reverse("tool_monitors_for_tool", args=[tool_id])


def _parse_input_datetime(raw: str) -> Optional[datetime]:
    raw = (raw or "").strip()
    if not raw:
        return None
    parsed = parse_datetime(raw)
    if parsed is not None:
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed
    for fmt in CSV_DATETIME_FORMATS:
        try:
            naive = datetime.strptime(raw, fmt)
            return timezone.make_aware(naive, timezone.get_current_timezone())
        except ValueError:
            continue
    return None


@login_required
@require_GET
def monitors_dashboard(request, category_id=None):
    selected_category = None
    if category_id:
        selected_category = get_object_or_404(MonitorCategory, pk=category_id)
    categories = MonitorCategory.objects.filter(parent=category_id)
    tools_with_monitors = (
        Tool.objects.filter(monitors__visible=True, monitors__monitor_category_id=category_id)
        .distinct()
        .order_by("name")
    )
    alert_logs = MonitorAlertLog.objects.filter(monitor__in=recursive_monitors(category_id))[:30]
    dictionary = {
        "selected_category": selected_category,
        "categories": categories,
        "tools_with_monitors": tools_with_monitors,
        "alert_logs": alert_logs,
        "can_upload": _can_upload(request.user),
    }
    return render(request, "NEMO_tool_monitors/monitors.html", dictionary)


@login_required
@permission_required(UPLOAD_PERMISSION, raise_exception=True)
@require_GET
def monitors_upload_hub(request):
    tools = (
        Tool.objects.filter(monitors__visible=True)
        .distinct()
        .order_by("name")
        .prefetch_related(
            Prefetch(
                "monitors",
                queryset=Monitor.objects.filter(visible=True).order_by("name"),
            )
        )
    )
    tools_payload = [
        {
            "id": tool.id,
            "name": tool.name,
            "monitors": [
                {
                    "id": m.id,
                    "name": m.name,
                    "upload_url": reverse("monitor_details", args=[m.id, "upload"]),
                    "chart_url": reverse("monitor_details", args=[m.id, "chart"]),
                    "data_url": reverse("monitor_details", args=[m.id, "data"]),
                }
                for m in tool.monitors.all()
            ],
        }
        for tool in tools
    ]
    return render(
        request,
        "NEMO_tool_monitors/monitors_upload_hub.html",
        {"tools_payload": tools_payload},
    )


@login_required
@require_GET
def tool_monitors_for_tool(request, tool_id):
    tool = get_object_or_404(Tool, pk=tool_id)
    monitor_list = tool.monitors.filter(visible=True).order_by("name")
    alert_logs = MonitorAlertLog.objects.filter(monitor__in=monitor_list)[:30]
    dictionary = {
        "tool": tool,
        "monitors": monitor_list,
        "alert_logs": alert_logs,
        "can_upload": _can_upload(request.user),
        "add_data_action_template": reverse("add_monitor_data", args=[0]),
    }
    return render(request, "NEMO_tool_monitors/tool_monitors.html", dictionary)


@login_required
@require_GET
def monitor_details(request, monitor_id, tab: str = None):
    monitor = get_object_or_404(Monitor, pk=monitor_id)
    chart_step = int(request.GET.get("chart_step", 1))
    default_refresh_rate = int(MonitorCustomization.get("monitor_default_refresh_rate") or 0)
    refresh_rate = int(request.GET.get("refresh_rate", default_refresh_rate))
    monitor_data, start, end = get_monitor_data(request, monitor)
    dictionary = {
        "tab": tab or "chart",
        "monitor": monitor,
        "start": start,
        "end": end,
        "refresh_rate": refresh_rate,
        "chart_step": chart_step,
        "can_upload": _can_upload(request.user),
        "monitor_date_formats": {
            variable.replace("monitor_format_", ""): MonitorCustomization.get(variable)
            for variable in MonitorCustomization.variables.keys()
            if variable.startswith("monitor_format_")
        },
    }
    return render(request, "NEMO_tool_monitors/monitor_data.html", dictionary)


@login_required
@require_GET
def export_monitor_data(request, monitor_id):
    monitor = get_object_or_404(Monitor, pk=monitor_id)
    monitor_data, start, end = get_monitor_data(request, monitor)
    table_result = BasicDisplayTable()
    table_result.add_header(("date", "Date"))
    table_result.add_header(("value", "Value"))
    table_result.add_header(("display_value", "Display value"))
    table_result.add_header(("notes", "Notes"))
    table_result.add_header(("created_by", "Created by"))
    table_result.add_header(("created_on", "Uploaded on"))
    table_result.add_header(("updated_by", "Last edited by"))
    table_result.add_header(("updated_on", "Last edited on"))
    for data_point in monitor_data:
        table_result.add_row(
            {
                "date": data_point.created_date,
                "value": data_point.value,
                "display_value": data_point.display_value(),
                "notes": data_point.notes or "",
                "created_by": str(data_point.created_by) if data_point.created_by else "",
                "created_on": data_point.created_on,
                "updated_by": str(data_point.updated_by) if data_point.updated_by else "",
                "updated_on": data_point.updated_on,
            }
        )
    response = table_result.to_csv()
    monitor_name = slugify_underscore(f"{monitor.tool.name}_{monitor.name}")
    filename = f"{monitor_name}_data_{export_format_datetime(start)}_to_{export_format_datetime(end)}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@require_GET
@disable_session_expiry_refresh
def monitor_chart_data(request, monitor_id):
    monitor = get_object_or_404(Monitor, pk=monitor_id)
    labels: List[str] = []
    data: List[float] = []
    ids: List[int] = []
    created_by: List[str] = []
    created_on: List[str] = []
    updated_on: List[str] = []
    notes: List[str] = []
    qs = get_monitor_data(request, monitor)[0].select_related("created_by", "updated_by").order_by("created_date")
    for point in qs:
        labels.append(format_datetime(point.created_date, "m/d/Y H:i:s"))
        data.append(point.value)
        ids.append(point.id)
        notes.append(point.notes or "")
        created_by.append(str(point.created_by) if point.created_by else "")
        created_on.append(format_datetime(point.created_on, "m/d/Y H:i:s") if point.created_on else "")
        last_edit = ""
        if point.updated_on and point.updated_by:
            last_edit = f"{format_datetime(point.updated_on, 'm/d/Y H:i:s')} ({point.updated_by})"
        elif point.updated_on:
            last_edit = format_datetime(point.updated_on, "m/d/Y H:i:s")
        updated_on.append(last_edit)
    return JsonResponse(
        data={
            "labels": labels,
            "data": data,
            "ids": ids,
            "created_by": created_by,
            "created_on": created_on,
            "updated_on": updated_on,
            "notes": notes,
        }
    )


@login_required
@require_GET
@disable_session_expiry_refresh
def monitor_alert_log(request, monitor_id):
    monitor = get_object_or_404(Monitor, pk=monitor_id)
    monitor_data, start, end = get_monitor_data(request, monitor)
    alert_log_entries = MonitorAlertLog.objects.filter(
        monitor=monitor, time__gte=start, time__lte=end or timezone.now()
    )
    return render(request, "NEMO_tool_monitors/monitor_alerts.html", {"alerts": alert_log_entries})


def get_monitor_data(request, monitor) -> Tuple[QuerySetType[MonitorData], datetime, datetime]:
    start, end = extract_times(request.GET, start_required=False, end_required=False)
    monitor_data = MonitorData.objects.filter(monitor=monitor)
    now = timezone.now().replace(second=0, microsecond=0).astimezone()
    monitor_default_daterange = MonitorCustomization.get("monitor_default_daterange")
    if not start:
        if monitor_default_daterange == "last_year":
            start = now - timedelta(days=365)
        elif monitor_default_daterange == "last_month":
            start = now - timedelta(days=30)
        elif monitor_default_daterange == "last_week":
            start = now - timedelta(weeks=1)
        elif monitor_default_daterange == "last_72hrs":
            start = now - timedelta(days=3)
        else:
            start = now - timedelta(days=1)
    return monitor_data.filter(created_date__gte=start, created_date__lte=(end or now)), start, end


def recursive_monitors(category_id, monitor_list: Set[Monitor] = None) -> Set[Monitor]:
    if monitor_list is None:
        monitor_list = set()
    monitor_list.update([m for m in Monitor.objects.filter(visible=True, monitor_category_id=category_id)])
    for category in MonitorCategory.objects.filter(parent=category_id):
        monitor_list.update(recursive_monitors(category.id, monitor_list))
    return monitor_list


@login_required
@permission_required(UPLOAD_PERMISSION, raise_exception=True)
@require_POST
def add_monitor_data(request, monitor_id):
    monitor = get_object_or_404(Monitor, pk=monitor_id)
    value_raw = request.POST.get("value", "").strip()
    timestamp_raw = request.POST.get("created_date", "").strip()
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

    error: Optional[str] = None
    value: Optional[float] = None
    created_date: Optional[datetime] = None

    try:
        value = float(value_raw)
    except ValueError:
        error = "Value must be a number."

    if not error and timestamp_raw:
        created_date = _parse_input_datetime(timestamp_raw)
        if created_date is None:
            error = f"Could not parse timestamp '{timestamp_raw}'."
    elif not error:
        created_date = timezone.now()

    if error:
        if is_ajax:
            return JsonResponse({"success": False, "error": error}, status=400)
        messages.error(request, error)
        return HttpResponseRedirect(_post_add_data_redirect(request, monitor))

    notes = (request.POST.get("notes") or "").strip()

    data_point = MonitorData.objects.create(
        monitor=monitor,
        value=value,
        created_date=created_date,
        notes=notes,
        created_by=request.user,
        updated_by=request.user,
    )

    if is_ajax:
        return JsonResponse({"success": True, "id": data_point.id})
    messages.success(request, f"Added data point: {data_point.display_value()} at {format_datetime(data_point.created_date)}.")
    return HttpResponseRedirect(_post_add_data_redirect(request, monitor))


@login_required
@permission_required(UPLOAD_PERMISSION, raise_exception=True)
@require_POST
def upload_monitor_data_csv(request, monitor_id):
    monitor = get_object_or_404(Monitor, pk=monitor_id)
    csv_file = request.FILES.get("csv_file")
    csv_text = request.POST.get("csv_text", "").strip()

    if csv_file:
        try:
            decoded = csv_file.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            messages.error(request, "Could not decode the uploaded CSV (expected UTF-8).")
            return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "upload"]))
    elif csv_text:
        decoded = csv_text
    else:
        messages.error(request, "Please provide a CSV file or paste CSV data.")
        return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "upload"]))

    rows: List[Tuple[datetime, float, str]] = []
    errors: List[str] = []
    reader = csv.reader(io.StringIO(decoded))
    for line_no, row in enumerate(reader, start=1):
        if not row or all(not cell.strip() for cell in row):
            continue
        if line_no == 1 and not _looks_like_data_row(row):
            continue
        if len(row) < 2:
            errors.append(f"Line {line_no}: expected at least two columns 'timestamp,value' (optional third: notes), got {row!r}.")
            continue
        timestamp = _parse_input_datetime(row[0])
        if timestamp is None:
            errors.append(f"Line {line_no}: could not parse timestamp '{row[0]}'.")
            continue
        try:
            value = float(row[1].strip())
        except ValueError:
            errors.append(f"Line {line_no}: could not parse value '{row[1]}'.")
            continue
        note = row[2].strip() if len(row) > 2 else ""
        rows.append((timestamp, value, note))

    if errors:
        for err in errors[:10]:
            messages.error(request, err)
        if len(errors) > 10:
            messages.error(request, f"...and {len(errors) - 10} more errors.")
        return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "upload"]))

    if not rows:
        messages.warning(request, "No data rows found in the CSV.")
        return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "upload"]))

    with transaction.atomic():
        created = []
        for timestamp, value, note in rows:
            created.append(
                MonitorData(
                    monitor=monitor,
                    value=value,
                    created_date=timestamp,
                    notes=note,
                    created_by=request.user,
                    updated_by=request.user,
                )
            )
        MonitorData.objects.bulk_create(created)

    monitor.refresh_from_db()
    latest = MonitorData.objects.filter(monitor=monitor).order_by("-created_date").first()
    if latest:
        monitor.last_read = latest.created_date
        monitor.last_value = latest.value
        monitor.save(update_fields=["last_read", "last_value"])

    messages.success(request, f"Uploaded {len(rows)} data points to {monitor.name}.")
    return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "data"]))


def _looks_like_data_row(row: List[str]) -> bool:
    if len(row) < 2:
        return False
    try:
        float(row[1].strip())
    except ValueError:
        return False
    return _parse_input_datetime(row[0]) is not None


@login_required
@permission_required(UPLOAD_PERMISSION, raise_exception=True)
@require_POST
def edit_monitor_data(request, monitor_id, data_id):
    data_point = get_object_or_404(MonitorData, pk=data_id, monitor_id=monitor_id)
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    value_raw = request.POST.get("value", "").strip()
    timestamp_raw = request.POST.get("created_date", "").strip()

    try:
        value = float(value_raw)
    except ValueError:
        msg = "Value must be a number."
        if is_ajax:
            return JsonResponse({"success": False, "error": msg}, status=400)
        messages.error(request, msg)
        return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "data"]))

    if timestamp_raw:
        created_date = _parse_input_datetime(timestamp_raw)
        if created_date is None:
            msg = f"Could not parse timestamp '{timestamp_raw}'."
            if is_ajax:
                return JsonResponse({"success": False, "error": msg}, status=400)
            messages.error(request, msg)
            return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "data"]))
        data_point.created_date = created_date

    data_point.value = value
    data_point.notes = (request.POST.get("notes") or "").strip()
    data_point.updated_by = request.user
    data_point.save()

    if is_ajax:
        return JsonResponse(
            {
                "success": True,
                "id": data_point.id,
                "value": data_point.value,
                "display_value": data_point.display_value(),
                "created_date": format_datetime(data_point.created_date, "m/d/Y H:i:s"),
                "notes": data_point.notes or "",
            }
        )
    messages.success(request, f"Updated data point {data_point.id}.")
    return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "data"]))


@login_required
@permission_required(UPLOAD_PERMISSION, raise_exception=True)
@require_http_methods(["POST", "DELETE"])
def delete_monitor_data(request, monitor_id, data_id):
    data_point = get_object_or_404(MonitorData, pk=data_id, monitor_id=monitor_id)
    data_point.delete()

    monitor = get_object_or_404(Monitor, pk=monitor_id)
    latest = MonitorData.objects.filter(monitor=monitor).order_by("-created_date").first()
    if latest:
        monitor.last_read = latest.created_date
        monitor.last_value = latest.value
        monitor.save(update_fields=["last_read", "last_value"])
    else:
        monitor.last_read = None
        monitor.last_value = None
        monitor.save(update_fields=["last_read", "last_value"])

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"success": True})
    messages.success(request, "Deleted data point.")
    return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "data"]))


@login_required
@staff_member_required
@require_http_methods(["GET", "POST"])
def create_monitor(request, tool_id):
    tool = get_object_or_404(Tool, pk=tool_id)
    return _monitor_form(request, monitor=None, tool=tool)


@login_required
@staff_member_required
@require_http_methods(["GET", "POST"])
def edit_monitor(request, monitor_id):
    monitor = get_object_or_404(Monitor, pk=monitor_id)
    return _monitor_form(request, monitor=monitor, tool=monitor.tool)


@login_required
@staff_member_required
@require_POST
def delete_monitor(request, monitor_id):
    monitor = get_object_or_404(Monitor, pk=monitor_id)
    tool_id = monitor.tool_id
    monitor.delete()
    messages.success(request, f"Deleted monitor.")
    return HttpResponseRedirect(reverse("tool_monitors_for_tool", args=[tool_id]))


def _monitor_form(request, monitor: Optional[Monitor], tool: Tool):
    error = None
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        data_label = (request.POST.get("data_label") or "").strip() or None
        data_prefix = (request.POST.get("data_prefix") or "").strip() or None
        data_suffix = (request.POST.get("data_suffix") or "").strip() or None
        description = (request.POST.get("description") or "").strip() or None
        visible = bool(request.POST.get("visible"))
        category_id = request.POST.get("monitor_category") or None
        category = MonitorCategory.objects.filter(pk=category_id).first() if category_id else None

        if not name:
            error = "Monitor name is required."
        else:
            if monitor is None:
                monitor = Monitor.objects.create(
                    name=name,
                    tool=tool,
                    visible=visible,
                    data_label=data_label,
                    data_prefix=data_prefix,
                    data_suffix=data_suffix,
                    description=description,
                    monitor_category=category,
                )
                messages.success(request, f"Created monitor '{monitor.name}'.")
            else:
                monitor.name = name
                monitor.visible = visible
                monitor.data_label = data_label
                monitor.data_prefix = data_prefix
                monitor.data_suffix = data_suffix
                monitor.description = description
                monitor.monitor_category = category
                monitor.save()
                messages.success(request, f"Updated monitor '{monitor.name}'.")
            return HttpResponseRedirect(reverse("tool_monitors_for_tool", args=[tool.id]))

    dictionary = {
        "monitor": monitor,
        "tool": tool,
        "categories": MonitorCategory.objects.all().order_by("name"),
        "error": error,
    }
    return render(request, "NEMO_tool_monitors/monitor_form.html", dictionary)
