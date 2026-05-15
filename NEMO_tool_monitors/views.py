from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Prefetch, Q
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
    DEFAULT_DATA_ENTRY_FIELDS,
    Monitor,
    MonitorAlertLog,
    MonitorColumn,
    MonitorData,
)

UPLOAD_PERMISSION = "tool_monitors.upload_monitor_data"


def _monitor_uses_legacy_notes(monitor: Monitor) -> bool:
    """Notes are stored on MonitorData.notes only when there is no Notes data entry field."""
    if not monitor.columns.exists():
        return True
    return not monitor.columns.filter(name__iexact="notes").exists()


def _data_entry_fields_for_form(monitor: Optional[Monitor]) -> List[dict]:
    if monitor:
        return [
            {"name": col.name, "data_type": col.data_type}
            for col in monitor.columns.order_by("order", "name")
        ]
    return [{"name": name, "data_type": data_type} for name, data_type in DEFAULT_DATA_ENTRY_FIELDS]

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


def _tools_with_visible_monitors():
    return Tool.objects.filter(monitors__visible=True).distinct()


def _monitor_category_paths() -> Set[str]:
    paths: Set[str] = set()
    for tool in _tools_with_visible_monitors().only("id", "_category", "parent_tool_id"):
        category = (tool.category or "").strip()
        if category:
            paths.add(category)
    return paths


def _tool_in_category_subtree_filter(category_path: str) -> Q:
    return (
        Q(_category=category_path)
        | Q(_category__startswith=category_path + "/")
        | Q(parent_tool___category=category_path)
        | Q(parent_tool___category__startswith=category_path + "/")
    )


def _tools_at_category(category_path: str) -> QuerySetType[Tool]:
    return (
        _tools_with_visible_monitors()
        .filter(Q(_category=category_path) | Q(parent_tool___category=category_path))
        .order_by("name")
    )


def _immediate_child_category_paths(parent_path: Optional[str] = None) -> List[str]:
    paths = _monitor_category_paths()
    children: Set[str] = set()
    if not parent_path:
        for path in paths:
            if "/" in path:
                children.add(path.split("/")[0])
            else:
                children.add(path)
    else:
        prefix = parent_path + "/"
        for path in paths:
            if path.startswith(prefix):
                remainder = path[len(prefix) :]
                children.add(parent_path + "/" + remainder.split("/")[0])
    return sorted(children, key=lambda value: value.lower())


def _category_navigation(path: Optional[str]) -> Dict:
    if path:
        parts = path.split("/")
        return {
            "path": path,
            "name": parts[-1],
            "ancestors": [
                {"path": "/".join(parts[: index + 1]), "name": segment}
                for index, segment in enumerate(parts[:-1])
            ],
        }
    return None


def _category_has_alert(category_path: str) -> bool:
    monitors = Monitor.objects.filter(
        visible=True, tool__in=_tools_with_visible_monitors().filter(_tool_in_category_subtree_filter(category_path))
    )
    return any(monitor.alert_triggered() for monitor in monitors)


def _uncategorized_tools_with_monitors() -> QuerySetType[Tool]:
    tool_ids = [tool.id for tool in _tools_with_visible_monitors() if not (tool.category or "").strip()]
    return Tool.objects.filter(id__in=tool_ids).order_by("name")


def _monitors_dashboard_context(category_path: Optional[str] = None) -> Dict:
    selected_category = _category_navigation(category_path)
    categories = [
        {
            "path": child_path,
            "name": child_path.split("/")[-1],
            "alert_triggered": _category_has_alert(child_path),
        }
        for child_path in _immediate_child_category_paths(category_path)
    ]
    if category_path:
        tools_with_monitors = _tools_at_category(category_path)
        monitor_filter = Monitor.objects.filter(
            visible=True,
            tool__in=_tools_with_visible_monitors().filter(_tool_in_category_subtree_filter(category_path)),
        )
    else:
        tools_with_monitors = _uncategorized_tools_with_monitors()
        monitor_filter = Monitor.objects.filter(visible=True)
    alert_logs = (
        MonitorAlertLog.objects.filter(monitor__in=monitor_filter)
        .select_related("monitor", "monitor__tool")[:30]
    )
    return {
        "selected_category": selected_category,
        "categories": categories,
        "tools_with_monitors": tools_with_monitors,
        "alert_logs": alert_logs,
    }


@login_required
@require_GET
def monitors_dashboard(request, category_path: Optional[str] = None):
    dictionary = _monitors_dashboard_context(category_path)
    dictionary["can_upload"] = _can_upload(request.user)
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
    monitor_list = tool.monitors.filter(visible=True).order_by("name").prefetch_related("columns")
    alert_logs = MonitorAlertLog.objects.filter(monitor__in=monitor_list)[:30]
    monitors_columns = {
        m.id: [
            {"id": col.id, "name": col.name, "data_type": col.data_type}
            for col in m.columns.order_by("order", "name")
        ]
        for m in monitor_list
    }
    dictionary = {
        "tool": tool,
        "tool_category": _category_navigation((tool.category or "").strip() or None),
        "monitors": monitor_list,
        "alert_logs": alert_logs,
        "can_upload": _can_upload(request.user),
        "add_data_action_template": reverse("add_monitor_data", args=[0]),
        "monitors_columns_json": json.dumps(monitors_columns),
    }
    return render(request, "NEMO_tool_monitors/tool_monitors.html", dictionary)


@login_required
@require_GET
def monitor_details(request, monitor_id, tab: str = None):
    monitor = get_object_or_404(Monitor, pk=monitor_id)
    chart_step = int(request.GET.get("chart_step", 1))
    monitor_data, start, end = get_monitor_data(request, monitor)
    dictionary = {
        "tab": tab or "chart",
        "monitor": monitor,
        "tool_category": _category_navigation((monitor.tool.category or "").strip() or None),
        "use_legacy_notes": _monitor_uses_legacy_notes(monitor),
        "start": start,
        "end": end,
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
    has_columns = monitor.columns.exists()
    table_result = BasicDisplayTable()
    table_result.add_header(("date", "Date"))
    if has_columns:
        table_result.add_header(("column_name", "Data entry field"))
        table_result.add_header(("column_type", "Type"))
    table_result.add_header(("value", "Value"))
    table_result.add_header(("display_value", "Display value"))
    table_result.add_header(("notes", "Notes"))
    table_result.add_header(("created_by", "Created by"))
    table_result.add_header(("created_on", "Uploaded on"))
    table_result.add_header(("updated_by", "Last edited by"))
    table_result.add_header(("updated_on", "Last edited on"))
    for data_point in monitor_data.select_related("column"):
        row = {
            "date": data_point.created_date,
            "value": data_point.value,
            "display_value": data_point.display_value(),
            "notes": data_point.notes or "",
            "created_by": str(data_point.created_by) if data_point.created_by else "",
            "created_on": data_point.created_on,
            "updated_by": str(data_point.updated_by) if data_point.updated_by else "",
            "updated_on": data_point.updated_on,
        }
        if has_columns:
            row["column_name"] = data_point.column.name if data_point.column else ""
            row["column_type"] = data_point.column.data_type if data_point.column else ""
        table_result.add_row(row)
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
    defined_columns = list(monitor.columns.order_by("order", "name"))
    qs = (
        get_monitor_data(request, monitor)[0]
        .select_related("created_by", "updated_by", "column")
        .order_by("created_date")
    )

    if defined_columns:
        # Multi-column mode: group data by column
        col_meta = [{"name": col.name, "type": col.data_type} for col in defined_columns]
        series: dict = {col.name: {"labels": [], "data": [], "string_data": [], "ids": [], "notes": [], "created_by": [], "created_on": [], "updated_on": []} for col in defined_columns}
        # Also bucket any orphaned rows (column=None) under a blank key
        series[""] = {"labels": [], "data": [], "string_data": [], "ids": [], "notes": [], "created_by": [], "created_on": [], "updated_on": []}

        for point in qs:
            col_name = point.column.name if point.column else ""
            bucket = series.get(col_name, series[""])
            bucket["labels"].append(format_datetime(point.created_date, "m/d/Y H:i:s"))
            bucket["data"].append(point.value)
            bucket["string_data"].append(point.string_value or "")
            bucket["ids"].append(point.id)
            bucket["notes"].append(point.notes or "")
            bucket["created_by"].append(str(point.created_by) if point.created_by else "")
            bucket["created_on"].append(format_datetime(point.created_on, "m/d/Y H:i:s") if point.created_on else "")
            last_edit = ""
            if point.updated_on and point.updated_by:
                last_edit = f"{format_datetime(point.updated_on, 'm/d/Y H:i:s')} ({point.updated_by})"
            elif point.updated_on:
                last_edit = format_datetime(point.updated_on, "m/d/Y H:i:s")
            bucket["updated_on"].append(last_edit)

        # Remove the orphan bucket if empty
        if not series[""]["ids"]:
            del series[""]
        elif "" not in [c["name"] for c in col_meta]:
            col_meta.append({"name": "", "type": "float"})

        # Determine if any data at all
        total_rows = sum(len(b["ids"]) for b in series.values())
        return JsonResponse(data={"columns": col_meta, "series": series, "total": total_rows})
    else:
        # Legacy single-value mode
        labels: List[str] = []
        data: List[float] = []
        ids: List[int] = []
        created_by: List[str] = []
        created_on: List[str] = []
        updated_on: List[str] = []
        notes: List[str] = []
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
                "columns": [{"name": "", "type": "float"}],
                "series": {
                    "": {
                        "labels": labels,
                        "data": data,
                        "string_data": [],
                        "ids": ids,
                        "created_by": created_by,
                        "created_on": created_on,
                        "updated_on": updated_on,
                        "notes": notes,
                    }
                },
                "total": len(labels),
                # Legacy flat keys kept for any external consumers
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


@login_required
@permission_required(UPLOAD_PERMISSION, raise_exception=True)
@require_POST
def add_monitor_data(request, monitor_id):
    monitor = get_object_or_404(Monitor, pk=monitor_id)
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    timestamp_raw = request.POST.get("created_date", "").strip()
    notes = (request.POST.get("notes") or "").strip() if _monitor_uses_legacy_notes(monitor) else ""

    created_date: Optional[datetime] = None
    if timestamp_raw:
        created_date = _parse_input_datetime(timestamp_raw)
        if created_date is None:
            err = f"Could not parse timestamp '{timestamp_raw}'."
            if is_ajax:
                return JsonResponse({"success": False, "error": err}, status=400)
            messages.error(request, err)
            return HttpResponseRedirect(_post_add_data_redirect(request, monitor))
    else:
        created_date = timezone.now()

    defined_columns = list(monitor.columns.order_by("order", "name"))

    if defined_columns:
        data_points = []
        col_errors = []
        for col in defined_columns:
            raw = request.POST.get(f"col_value_{col.id}", "").strip()
            if not raw:
                continue
            if col.data_type == "string":
                data_points.append(
                    MonitorData(
                        monitor=monitor,
                        column=col,
                        value=None,
                        string_value=raw,
                        created_date=created_date,
                        notes=notes,
                        created_by=request.user,
                        updated_by=request.user,
                    )
                )
            else:
                try:
                    val = float(int(float(raw))) if col.data_type == "integer" else float(raw)
                    data_points.append(
                        MonitorData(
                            monitor=monitor,
                            column=col,
                            value=val,
                            created_date=created_date,
                            notes=notes,
                            created_by=request.user,
                            updated_by=request.user,
                        )
                    )
                except (ValueError, OverflowError):
                    col_errors.append(
                        f"Field '{col.name}': expected {'integer' if col.data_type == 'integer' else 'number'}, got '{raw}'."
                    )

        if col_errors:
            if is_ajax:
                return JsonResponse({"success": False, "error": " ".join(col_errors)}, status=400)
            for err in col_errors:
                messages.error(request, err)
            return HttpResponseRedirect(_post_add_data_redirect(request, monitor))

        if not data_points:
            err = "Please enter at least one data entry field value."
            if is_ajax:
                return JsonResponse({"success": False, "error": err}, status=400)
            messages.error(request, err)
            return HttpResponseRedirect(_post_add_data_redirect(request, monitor))

        created = MonitorData.objects.bulk_create(data_points)
        _refresh_monitor_last_value(monitor)

        if is_ajax:
            return JsonResponse({"success": True, "ids": [dp.id for dp in created]})
        messages.success(request, f"Added {len(created)} data point(s) at {format_datetime(created_date)}.")
        return HttpResponseRedirect(_post_add_data_redirect(request, monitor))

    else:
        value_raw = request.POST.get("value", "").strip()
        try:
            value = float(value_raw)
        except ValueError:
            err = "Value must be a number."
            if is_ajax:
                return JsonResponse({"success": False, "error": err}, status=400)
            messages.error(request, err)
            return HttpResponseRedirect(_post_add_data_redirect(request, monitor))

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

    defined_columns = {col.name.lower(): col for col in monitor.columns.all()}

    if defined_columns:
        return _upload_multi_column_csv(request, monitor, decoded, defined_columns)
    else:
        return _upload_legacy_csv(request, monitor, decoded)


def _upload_legacy_csv(request, monitor: Monitor, decoded: str):
    monitor_id = monitor.pk
    rows: List[Tuple[datetime, float, str]] = []
    errors: List[str] = []
    reader = csv.reader(io.StringIO(decoded))
    for line_no, row in enumerate(reader, start=1):
        if not row or all(not cell.strip() for cell in row):
            continue
        if line_no == 1 and not _looks_like_data_row(row):
            # Check if this looks like a multi-column header
            if len(row) > 2:
                messages.error(
                    request,
                    "This CSV appears to have multiple fields, but this monitor has no data entry field definitions. "
                    "Please define data entry fields on the monitor first before uploading multi-field data.",
                )
                return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "upload"]))
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

    _refresh_monitor_last_value(monitor)
    messages.success(request, f"Uploaded {len(rows)} data points to {monitor.name}.")
    return HttpResponseRedirect(reverse("monitor_details", args=[monitor.pk, "data"]))


def _upload_multi_column_csv(request, monitor: Monitor, decoded: str, defined_columns: dict):
    """Upload handler when the monitor has defined columns."""
    monitor_id = monitor.pk
    reader = csv.reader(io.StringIO(decoded))
    all_rows = [row for row in reader if row and any(cell.strip() for cell in row)]
    if not all_rows:
        messages.warning(request, "No data rows found in the CSV.")
        return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "upload"]))

    # Row 1 must be a header
    header_row = all_rows[0]
    if _looks_like_data_row(header_row):
        messages.error(request, "CSV must include a header row as the first line (e.g. Date, Value, Notes, ...).")
        return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "upload"]))

    date_header = header_row[0].strip()
    col_headers = [cell.strip() for cell in header_row[1:]]

    # Map header names to MonitorColumn objects (case-insensitive)
    col_map: List[Optional[MonitorColumn]] = []
    unrecognized = []
    for h in col_headers:
        col = defined_columns.get(h.lower())
        col_map.append(col)
        if col is None and h:
            unrecognized.append(h)

    if unrecognized:
        messages.warning(request, f"Unrecognized field(s) will be skipped: {', '.join(unrecognized)}")

    missing = [name for name in defined_columns if not any(h.lower() == name for h in col_headers)]
    if missing:
        messages.warning(request, f"Defined field(s) not found in CSV: {', '.join(defined_columns[n].name for n in missing)}")

    errors: List[str] = []
    # Each entry: (timestamp, MonitorColumn, value_or_none, string_value)
    data_rows: List[Tuple[datetime, MonitorColumn, Optional[float], str]] = []

    for line_no, row in enumerate(all_rows[1:], start=2):
        if not row or all(not cell.strip() for cell in row):
            continue
        timestamp = _parse_input_datetime(row[0])
        if timestamp is None:
            errors.append(f"Line {line_no}: could not parse timestamp '{row[0]}'.")
            continue
        for col_idx, col in enumerate(col_map):
            if col is None:
                continue
            cell = row[col_idx + 1].strip() if col_idx + 1 < len(row) else ""
            if not cell:
                continue  # blank cell — skip
            if col.data_type == "string":
                data_rows.append((timestamp, col, None, cell))
            elif col.data_type == "integer":
                try:
                    val = float(int(float(cell)))
                    data_rows.append((timestamp, col, val, ""))
                except (ValueError, OverflowError):
                    errors.append(f"Line {line_no}, field '{col.name}': expected integer, got '{cell}'.")
            else:  # float
                try:
                    val = float(cell)
                    data_rows.append((timestamp, col, val, ""))
                except ValueError:
                    errors.append(f"Line {line_no}, field '{col.name}': expected number, got '{cell}'.")

    if errors:
        for err in errors[:10]:
            messages.error(request, err)
        if len(errors) > 10:
            messages.error(request, f"...and {len(errors) - 10} more errors.")
        return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "upload"]))

    if not data_rows:
        messages.warning(request, "No data rows found in the CSV.")
        return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "upload"]))

    with transaction.atomic():
        MonitorData.objects.bulk_create([
            MonitorData(
                monitor=monitor,
                column=col,
                value=value,
                string_value=string_val,
                created_date=timestamp,
                created_by=request.user,
                updated_by=request.user,
            )
            for timestamp, col, value, string_val in data_rows
        ])

    _refresh_monitor_last_value(monitor)
    messages.success(request, f"Uploaded {len(data_rows)} data points to {monitor.name}.")
    return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "data"]))


def _refresh_monitor_last_value(monitor: Monitor):
    monitor.refresh_from_db()
    latest = MonitorData.objects.filter(monitor=monitor, value__isnull=False).order_by("-created_date").first()
    if latest:
        monitor.last_read = latest.created_date
        monitor.last_value = latest.value
        monitor.save(update_fields=["last_read", "last_value"])


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

    is_string_col = data_point.column and data_point.column.data_type == "string"

    if is_string_col:
        data_point.string_value = value_raw
        data_point.value = None
    else:
        try:
            value = float(value_raw)
        except ValueError:
            msg = "Value must be a number."
            if is_ajax:
                return JsonResponse({"success": False, "error": msg}, status=400)
            messages.error(request, msg)
            return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "data"]))
        data_point.value = value

    if timestamp_raw:
        created_date = _parse_input_datetime(timestamp_raw)
        if created_date is None:
            msg = f"Could not parse timestamp '{timestamp_raw}'."
            if is_ajax:
                return JsonResponse({"success": False, "error": msg}, status=400)
            messages.error(request, msg)
            return HttpResponseRedirect(reverse("monitor_details", args=[monitor_id, "data"]))
        data_point.created_date = created_date

    if _monitor_uses_legacy_notes(data_point.monitor):
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

        # Parse column definitions submitted as parallel arrays
        col_names = request.POST.getlist("column_name[]")
        col_types = request.POST.getlist("column_type[]")
        submitted_columns = [
            (n.strip(), t.strip())
            for n, t in zip(col_names, col_types)
            if n.strip()
        ]

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
                )
                messages.success(request, f"Created monitor '{monitor.name}'.")
            else:
                monitor.name = name
                monitor.visible = visible
                monitor.data_label = data_label
                monitor.data_prefix = data_prefix
                monitor.data_suffix = data_suffix
                monitor.description = description
                monitor.save()
                messages.success(request, f"Updated monitor '{monitor.name}'.")

            # Sync column definitions
            _sync_monitor_columns(request, monitor, submitted_columns)
            return HttpResponseRedirect(reverse("tool_monitors_for_tool", args=[tool.id]))

    dictionary = {
        "monitor": monitor,
        "tool": tool,
        "tool_category": _category_navigation((tool.category or "").strip() or None),
        "data_entry_fields": _data_entry_fields_for_form(monitor),
        "column_type_choices": MonitorColumn._meta.get_field("data_type").choices,
        "error": error,
    }
    return render(request, "NEMO_tool_monitors/monitor_form.html", dictionary)


def _sync_monitor_columns(request, monitor: Monitor, submitted_columns: List[Tuple[str, str]]):
    """
    Sync MonitorColumn records to match submitted_columns (list of (name, data_type)).
    Data entry fields removed from the form are deleted; data points that referenced them become orphaned
    (column FK set to null). A warning is shown when orphaned rows exist.
    """
    valid_types = {choice[0] for choice in MonitorColumn._meta.get_field("data_type").choices}
    existing = {col.name.lower(): col for col in monitor.columns.all()}
    submitted_names_lower = {n.lower() for n, _ in submitted_columns}

    # Delete removed columns (warn if they have data)
    for lower_name, col in existing.items():
        if lower_name not in submitted_names_lower:
            orphan_count = col.data_points.count()
            if orphan_count:
                messages.warning(
                    request,
                    f"Data entry field '{col.name}' was removed. {orphan_count} data point(s) referencing it are now unlinked.",
                )
            col.delete()

    # Create or update remaining columns
    for order, (col_name, col_type) in enumerate(submitted_columns):
        if col_type not in valid_types:
            col_type = "float"
        col = existing.get(col_name.lower())
        if col:
            if col.name != col_name or col.data_type != col_type or col.order != order:
                col.name = col_name
                col.data_type = col_type
                col.order = order
                col.save()
        else:
            MonitorColumn.objects.create(monitor=monitor, name=col_name, data_type=col_type, order=order)
