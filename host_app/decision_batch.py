from __future__ import annotations

import csv
import json
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from models import RunResult, RunStatus


class DecisionBatchError(RuntimeError):
    pass


_TRUE_VALUES = {"1", "TRUE", "YES", "Y", "ON"}
_FALSE_VALUES = {"0", "FALSE", "NO", "N", "OFF"}


@dataclass(frozen=True)
class DecisionBatchRow:
    profile_id: str
    group_id: str
    repeat_id: str
    decision_id: str
    direction: str
    start_digits: tuple[int, int, int, int]
    active_wheels: tuple[int, ...]
    scan_order: tuple[int, ...]
    binding_wheel: int
    true_digits: tuple[int, int, int, int]
    binding_confidence: int
    preserve_inactive_start: bool
    force_reseat_before: bool
    enabled: bool
    notes: str
    source_row: int

    # Workflow metadata. Legacy Digit Scan plans default to digit_scan.
    task_type: str = "digit_scan"
    prefix_stage: int = 0
    prefix_valid: int = -1
    expected_binding_wheel: int = 0

    @property
    def key(self) -> str:
        return f"{self.decision_id}_{self.repeat_id}"

    @property
    def start_code(self) -> str:
        return "".join(str(value) for value in self.start_digits)

    @property
    def planned_runs(self) -> int:
        return len(self.active_wheels) * 10

    @property
    def active_mask(self) -> tuple[int, int, int, int]:
        active = set(self.active_wheels)
        return tuple(1 if wheel in active else 0 for wheel in range(1, 5))  # type: ignore[return-value]

    @property
    def target_digit(self) -> int:
        if self.binding_wheel not in {1, 2, 3, 4}:
            return -1
        return self.true_digits[self.binding_wheel - 1]

    @property
    def is_binding_scan(self) -> bool:
        return self.task_type == "binding_scan"

    @property
    def storage_root(self) -> str:
        return "binding_scans" if self.is_binding_scan else "decision_batches"

    @property
    def workflow_label(self) -> str:
        return "Binding Scan" if self.is_binding_scan else "Decision Digit Scan"

    @property
    def expected_password(self) -> str | None:
        """Password required by this plan row, if the plan declares one.

        Multi-password plans written for the current collector put PASSWORD=dddd
        in notes.  MPdddd in decision_id is accepted as a second independent
        fallback so a spreadsheet/editor cannot silently remove the guard.
        """
        note_match = re.search(
            r"(?i)(?:EXPECTED_)?PASSWORD\s*=\s*([0-9]{4})(?![0-9])",
            self.notes,
        )
        if note_match is not None:
            return note_match.group(1)

        id_match = re.search(r"(?i)(?:^|[_-])MP([0-9]{4})(?:$|[_-])", self.decision_id)
        if id_match is not None:
            return id_match.group(1)

        return None


def _parse_bool(value: str, *, field: str, row: int, default: bool) -> bool:
    raw = value.strip().upper()
    if not raw:
        return default
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    raise DecisionBatchError(
        f"Plan row {row}: {field} must be 1/0, true/false or yes/no"
    )


def _parse_digit(row: dict[str, str], field: str, row_number: int) -> int:
    raw = (row.get(field) or "").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise DecisionBatchError(
            f"Plan row {row_number}: {field} must be an integer from 0 to 9"
        ) from exc
    if value not in range(10):
        raise DecisionBatchError(
            f"Plan row {row_number}: {field} must be an integer from 0 to 9"
        )
    return value


def _parse_int(
    row: dict[str, str],
    field: str,
    row_number: int,
    *,
    allowed: set[int],
    default: int | None = None,
) -> int:
    raw = (row.get(field) or "").strip()
    if raw == "" and default is not None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        allowed_text = ", ".join(str(v) for v in sorted(allowed))
        raise DecisionBatchError(
            f"Plan row {row_number}: {field} must be one of {allowed_text}"
        ) from exc
    if value not in allowed:
        allowed_text = ", ".join(str(v) for v in sorted(allowed))
        raise DecisionBatchError(
            f"Plan row {row_number}: {field} must be one of {allowed_text}"
        )
    return value


def _parse_flag(row: dict[str, str], field: str, row_number: int) -> bool:
    return _parse_bool(
        row.get(field) or "",
        field=field,
        row=row_number,
        default=False,
    )


def _parse_scan_order(row: dict[str, str], row_number: int) -> tuple[int, ...]:
    order: list[int] = []
    zero_seen = False
    for field in ("scan_1", "scan_2", "scan_3", "scan_4"):
        value = _parse_int(
            row,
            field,
            row_number,
            allowed={0, 1, 2, 3, 4},
            default=0,
        )
        if value == 0:
            zero_seen = True
            continue
        if zero_seen:
            raise DecisionBatchError(
                f"Plan row {row_number}: scan order cannot contain a wheel after a 0"
            )
        if value in order:
            raise DecisionBatchError(
                f"Plan row {row_number}: scan order contains W{value} more than once"
            )
        order.append(value)
    return tuple(order)


def _xlsx_column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch) - ord("A") + 1)
    return max(0, value - 1)


def _read_xlsx_plan(path: Path) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """Read the simple Collection Plan sheet without adding an Excel dependency."""
    main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg_rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"

    with zipfile.ZipFile(path, "r") as archive:
        workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
        rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rel_root.findall(f"{{{pkg_rel_ns}}}Relationship")
        }

        sheets = workbook_root.find(f"{{{main_ns}}}sheets")
        if sheets is None or not list(sheets):
            raise DecisionBatchError("XLSX workbook has no worksheets")
        selected = None
        for sheet in list(sheets):
            if sheet.attrib.get("name", "").strip().casefold() == "collection plan":
                selected = sheet
                break
        if selected is None:
            selected = list(sheets)[0]

        rel_id = selected.attrib.get(f"{{{rel_ns}}}id")
        if not rel_id or rel_id not in rel_targets:
            raise DecisionBatchError("Could not resolve the Collection Plan worksheet")
        target = rel_targets[rel_id].replace("\\", "/")
        if target.startswith("/"):
            worksheet_path = target.lstrip("/")
        elif target.startswith("xl/"):
            worksheet_path = target
        else:
            worksheet_path = "xl/" + target.lstrip("./")

        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared_root.findall(f"{{{main_ns}}}si"):
                text = "".join(t.text or "" for t in item.iter(f"{{{main_ns}}}t"))
                shared_strings.append(text)

        ws_root = ET.fromstring(archive.read(worksheet_path))
        sheet_data = ws_root.find(f"{{{main_ns}}}sheetData")
        if sheet_data is None:
            raise DecisionBatchError("XLSX Collection Plan sheet contains no rows")

        matrix: list[tuple[int, list[str]]] = []
        max_col = -1
        for row_node in sheet_data.findall(f"{{{main_ns}}}row"):
            row_number = int(row_node.attrib.get("r", len(matrix) + 1))
            values: dict[int, str] = {}
            for cell in row_node.findall(f"{{{main_ns}}}c"):
                ref = cell.attrib.get("r", "A1")
                col = _xlsx_column_index(ref)
                max_col = max(max_col, col)
                cell_type = cell.attrib.get("t", "")
                if cell_type == "inlineStr":
                    inline = cell.find(f"{{{main_ns}}}is")
                    value = "" if inline is None else "".join(
                        t.text or "" for t in inline.iter(f"{{{main_ns}}}t")
                    )
                else:
                    value_node = cell.find(f"{{{main_ns}}}v")
                    raw = "" if value_node is None or value_node.text is None else value_node.text
                    if cell_type == "s" and raw:
                        try:
                            value = shared_strings[int(raw)]
                        except (ValueError, IndexError):
                            value = raw
                    elif cell_type == "b":
                        value = "1" if raw == "1" else "0"
                    else:
                        value = raw
                        if value.endswith(".0"):
                            try:
                                value = str(int(float(value)))
                            except ValueError:
                                pass
                values[col] = value
            if values:
                row_values = [values.get(i, "") for i in range(max_col + 1)]
                matrix.append((row_number, row_values))

    if not matrix:
        raise DecisionBatchError("XLSX Collection Plan sheet is empty")
    header_row_number, header_values = matrix[0]
    del header_row_number
    headers = [str(value).strip() for value in header_values]
    if not any(headers):
        raise DecisionBatchError("Plan has no header")

    rows: list[tuple[int, dict[str, str]]] = []
    for row_number, row_values in matrix[1:]:
        if len(row_values) < len(headers):
            row_values = row_values + [""] * (len(headers) - len(row_values))
        row = {
            header: str(row_values[index] if index < len(row_values) else "")
            for index, header in enumerate(headers)
            if header
        }
        rows.append((row_number, row))
    return headers, rows


def _read_plan_rows(path: Path) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise DecisionBatchError("Plan has no header")
            headers = [name.strip() for name in reader.fieldnames if name]
            rows = [
                (row_number, {str(k): (v or "") for k, v in row.items() if k is not None})
                for row_number, row in enumerate(reader, start=2)
            ]
            return headers, rows
    if suffix == ".xlsx":
        return _read_xlsx_plan(path)
    raise DecisionBatchError("Decision Batch plan must be a .csv or .xlsx file")


def load_decision_batch_csv(path: Path) -> list[DecisionBatchRow]:
    """Load either a legacy Digit Scan Decision plan or a Binding Scan plan.

    Binding Scan rows use the same movement columns as Decision Digit Scan rows,
    but add task_type=binding_scan plus scan-level labels.  The exact physical
    start code is always preserved for Binding Scan so intentionally wrong
    prefixes cannot be silently replaced by the App's correct combination.
    """
    if not path.exists():
        raise DecisionBatchError(f"Plan file not found: {path}")

    common_required = {
        "profile_id",
        "group_id",
        "repeat_id",
        "decision_id",
        "start_w1",
        "start_w2",
        "start_w3",
        "start_w4",
        "active_w1",
        "active_w2",
        "active_w3",
        "active_w4",
        "scan_1",
        "scan_2",
        "scan_3",
        "scan_4",
    }

    decisions: list[DecisionBatchRow] = []
    seen: set[tuple[str, str]] = set()

    header_list, plan_rows = _read_plan_rows(path)
    headers = {name.strip() for name in header_list if name}
    missing = common_required - headers
    if missing:
        raise DecisionBatchError(
            "Plan is missing required columns: " + ", ".join(sorted(missing))
        )

    for row_number, row in plan_rows:
        if not any((value or "").strip() for value in row.values()):
            continue

        profile_id = (row.get("profile_id") or "").strip()
        group_id = (row.get("group_id") or "").strip()
        repeat_id = (row.get("repeat_id") or "").strip().upper()
        decision_id = (row.get("decision_id") or "").strip()
        direction = (row.get("direction") or "CCW").strip().upper()
        if direction not in {"CW", "CCW"}:
            raise DecisionBatchError(
                f"Plan row {row_number}: direction must be CW or CCW"
            )

        raw_task = (row.get("task_type") or row.get("mode") or "digit_scan").strip().lower()
        aliases = {
            "digit": "digit_scan",
            "decision": "digit_scan",
            "decision_digit_scan": "digit_scan",
            "digit_scan": "digit_scan",
            "binding": "binding_scan",
            "binding_probe": "binding_scan",
            "binding_scan": "binding_scan",
        }
        task_type = aliases.get(raw_task, raw_task)
        if task_type not in {"digit_scan", "binding_scan"}:
            raise DecisionBatchError(
                f"Plan row {row_number}: task_type must be digit_scan or binding_scan"
            )

        notes = (row.get("notes") or "").strip()
        explicit_password = (row.get("expected_password") or "").strip()
        if explicit_password:
            if len(explicit_password) != 4 or not explicit_password.isdigit():
                raise DecisionBatchError(
                    f"Plan row {row_number}: expected_password must be exactly four digits"
                )
            notes = (
                f"EXPECTED_PASSWORD={explicit_password}; {notes}"
                if notes
                else f"EXPECTED_PASSWORD={explicit_password}"
            )

        for field_name, value in {
            "profile_id": profile_id,
            "group_id": group_id,
            "repeat_id": repeat_id,
            "decision_id": decision_id,
        }.items():
            if not value:
                raise DecisionBatchError(
                    f"Plan row {row_number}: {field_name} cannot be empty"
                )

        if repeat_id not in {"A", "B"}:
            raise DecisionBatchError(
                f"Plan row {row_number}: repeat_id must be A or B"
            )

        start_digits = tuple(
            _parse_digit(row, f"start_w{wheel}", row_number)
            for wheel in range(1, 5)
        )
        true_digits = (0, 0, 0, 0)

        active_wheels = tuple(
            wheel
            for wheel in range(1, 5)
            if _parse_flag(row, f"active_w{wheel}", row_number)
        )
        if not active_wheels:
            raise DecisionBatchError(
                f"Plan row {row_number}: at least one active/probe wheel is required"
            )

        scan_order = _parse_scan_order(row, row_number)
        if set(scan_order) != set(active_wheels) or len(scan_order) != len(active_wheels):
            raise DecisionBatchError(
                f"Plan row {row_number}: scan_1..scan_4 must contain every active wheel "
                "exactly once and no inactive wheels"
            )

        binding_confidence = _parse_int(
            row,
            "binding_confidence",
            row_number,
            allowed={0, 1, 2, 3},
            default=2,
        )

        if task_type == "digit_scan":
            raw_binding = (row.get("binding_wheel") or "").strip()
            if not raw_binding:
                raise DecisionBatchError(
                    f"Plan row {row_number}: binding_wheel is required for digit_scan"
                )
            binding_wheel = _parse_int(
                row,
                "binding_wheel",
                row_number,
                allowed={1, 2, 3, 4},
            )
            if binding_wheel not in active_wheels:
                raise DecisionBatchError(
                    f"Plan row {row_number}: binding_wheel W{binding_wheel} must be active"
                )
            prefix_stage = 0
            prefix_valid = -1
            expected_binding_wheel = binding_wheel
            preserve_default = False
        else:
            for label_field in ("prefix_stage", "prefix_valid", "expected_binding_wheel"):
                if not (row.get(label_field) or "").strip():
                    raise DecisionBatchError(
                        f"Plan row {row_number}: {label_field} is required for binding_scan"
                    )
            prefix_stage = _parse_int(
                row,
                "prefix_stage",
                row_number,
                allowed={0, 1, 2, 3, 4},
            )
            prefix_valid = int(
                _parse_bool(
                    row.get("prefix_valid") or "",
                    field="prefix_valid",
                    row=row_number,
                    default=False,
                )
            )
            expected_binding_wheel = _parse_int(
                row,
                "expected_binding_wheel",
                row_number,
                allowed={0, 1, 2, 3, 4},
            )
            # A valid prefix may deliberately use expected_binding_wheel=0 for
            # blind/comparative Binding Scan experiments (for example W3-vs-W4)
            # where the next binding wheel is the quantity being measured.
            # In that case 0 means UNKNOWN, not invalid-prefix.
            if expected_binding_wheel and expected_binding_wheel not in active_wheels:
                raise DecisionBatchError(
                    f"Plan row {row_number}: expected_binding_wheel W{expected_binding_wheel} "
                    "must be one of the probed/active wheels, or 0 for NONE"
                )
            # binding_wheel is intentionally not a target label in Binding Scan.
            # Keep it as the scan-level expected wheel solely for legacy metadata viewers.
            binding_wheel = expected_binding_wheel
            preserve_default = True

        preserve_inactive_start = _parse_bool(
            row.get("preserve_inactive_start") or "",
            field="preserve_inactive_start",
            row=row_number,
            default=preserve_default,
        )
        if task_type == "binding_scan" and not preserve_inactive_start:
            raise DecisionBatchError(
                f"Plan row {row_number}: Binding Scan requires preserve_inactive_start=1 "
                "so wrong-prefix states are not silently corrected"
            )

        force_reseat_before = _parse_bool(
            row.get("force_reseat_before") or "",
            field="force_reseat_before",
            row=row_number,
            default=False,
        )
        enabled = _parse_bool(
            row.get("enabled") or "",
            field="enabled",
            row=row_number,
            default=True,
        )

        duplicate_key = (decision_id, repeat_id)
        if duplicate_key in seen:
            raise DecisionBatchError(
                f"Plan row {row_number}: duplicate decision/repeat {decision_id}/{repeat_id}"
            )
        seen.add(duplicate_key)

        decisions.append(
            DecisionBatchRow(
                profile_id=profile_id,
                group_id=group_id,
                repeat_id=repeat_id,
                decision_id=decision_id,
                direction=direction,
                start_digits=start_digits,  # type: ignore[arg-type]
                active_wheels=active_wheels,
                scan_order=scan_order,
                binding_wheel=binding_wheel,
                true_digits=true_digits,  # type: ignore[arg-type]
                binding_confidence=binding_confidence,
                preserve_inactive_start=preserve_inactive_start,
                force_reseat_before=force_reseat_before,
                enabled=enabled,
                notes=notes,
                source_row=row_number,
                task_type=task_type,
                prefix_stage=prefix_stage,
                prefix_valid=prefix_valid,
                expected_binding_wheel=expected_binding_wheel,
            )
        )

    enabled_decisions = [decision for decision in decisions if decision.enabled]
    if not enabled_decisions:
        raise DecisionBatchError("Plan contains no enabled decisions")

    task_types = {decision.task_type for decision in enabled_decisions}
    if len(task_types) != 1:
        raise DecisionBatchError(
            "A single plan file cannot mix digit_scan and binding_scan rows"
        )
    return enabled_decisions


def write_decision_batch_template(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "profile_id",
        "group_id",
        "repeat_id",
        "decision_id",
        "task_type",
        "direction",
        "start_w1",
        "start_w2",
        "start_w3",
        "start_w4",
        "active_w1",
        "active_w2",
        "active_w3",
        "active_w4",
        "scan_1",
        "scan_2",
        "scan_3",
        "scan_4",
        "binding_wheel",
        "binding_confidence",
        "preserve_inactive_start",
        "force_reseat_before",
        "expected_password",
        "enabled",
        "notes",
    ]
    rows = [
        {
            "profile_id": "P001",
            "group_id": "P001_D0",
            "repeat_id": "A",
            "decision_id": "P001_D0",
            "task_type": "digit_scan",
            "direction": "CCW",
            "start_w1": 3,
            "start_w2": 5,
            "start_w3": 7,
            "start_w4": 9,
            "active_w1": 1,
            "active_w2": 1,
            "active_w3": 1,
            "active_w4": 1,
            "scan_1": 1,
            "scan_2": 2,
            "scan_3": 3,
            "scan_4": 4,
            "binding_wheel": 1,
            "binding_confidence": 2,
            "preserve_inactive_start": 0,
            "force_reseat_before": 0,
            "expected_password": "1111",
            "enabled": 1,
            "notes": "Example: continuous 40-candidate Decision",
        }
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)



def write_binding_scan_template(path: Path) -> None:
    """Write a minimal Binding Scan plan template.

    Each row is one A/B repeat of one physical prefix state.  The probe wheels
    are listed with active_w* + scan_1..scan_4.  expected_binding_wheel=0 means
    NONE / invalid-prefix for the scan-level training label.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "profile_id",
        "group_id",
        "repeat_id",
        "decision_id",
        "task_type",
        "direction",
        "start_w1",
        "start_w2",
        "start_w3",
        "start_w4",
        "active_w1",
        "active_w2",
        "active_w3",
        "active_w4",
        "scan_1",
        "scan_2",
        "scan_3",
        "scan_4",
        "prefix_stage",
        "prefix_valid",
        "expected_binding_wheel",
        "binding_confidence",
        "preserve_inactive_start",
        "force_reseat_before",
        "expected_password",
        "enabled",
        "notes",
    ]
    rows = [
        {
            "profile_id": "BP001_VALID",
            "group_id": "BP001",
            "repeat_id": "A",
            "decision_id": "BP001_VALID_CCW",
            "task_type": "binding_scan",
            "direction": "CCW",
            "start_w1": 1,
            "start_w2": 5,
            "start_w3": 7,
            "start_w4": 9,
            "active_w1": 0,
            "active_w2": 1,
            "active_w3": 0,
            "active_w4": 1,
            "scan_1": 2,
            "scan_2": 4,
            "scan_3": 0,
            "scan_4": 0,
            "prefix_stage": 1,
            "prefix_valid": 1,
            "expected_binding_wheel": 2,
            "binding_confidence": 2,
            "preserve_inactive_start": 1,
            "force_reseat_before": 1,
            "expected_password": "1111",
            "enabled": 1,
            "notes": "Example valid W1 prefix; probe W2 then W4; 20 WAV total",
        },
        {
            "profile_id": "BP001_VALID",
            "group_id": "BP001",
            "repeat_id": "B",
            "decision_id": "BP001_VALID_CCW",
            "task_type": "binding_scan",
            "direction": "CCW",
            "start_w1": 1,
            "start_w2": 5,
            "start_w3": 7,
            "start_w4": 9,
            "active_w1": 0,
            "active_w2": 1,
            "active_w3": 0,
            "active_w4": 1,
            "scan_1": 2,
            "scan_2": 4,
            "scan_3": 0,
            "scan_4": 0,
            "prefix_stage": 1,
            "prefix_valid": 1,
            "expected_binding_wheel": 2,
            "binding_confidence": 2,
            "preserve_inactive_start": 1,
            "force_reseat_before": 0,
            "expected_password": "1111",
            "enabled": 1,
            "notes": "B repeat; same physical seating as A",
        },
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

def decision_candidate_specs(decision: DecisionBatchRow) -> list[dict[str, object]]:
    """Enumerate the one-digit WAVs in either plan-driven workflow."""
    specs: list[dict[str, object]] = []
    candidate_index = 1
    for scan_position, wheel in enumerate(decision.scan_order, start=1):
        code = list(decision.start_digits)
        for move_index in range(1, 11):
            before = list(code)
            after = list(code)
            delta = -1 if decision.direction == "CW" else 1
            after[wheel - 1] = (before[wheel - 1] + delta) % 10
            to_digit = after[wheel - 1]

            if decision.is_binding_scan:
                # Binding Scan has no per-digit true-gate target.  Its label is
                # scan/wheel-level: valid prefix + expected next binding wheel.
                is_true_gate = 0
                is_target = 0
                # -1 = unknown/unlabelled probe for blind comparisons.
                # 0/1 are used only when an expected wheel is explicitly declared.
                probe_binding_label = (
                    -1
                    if decision.expected_binding_wheel == 0
                    else int(
                        decision.prefix_valid == 1
                        and decision.expected_binding_wheel == wheel
                    )
                )
            else:
                is_true_gate = int(to_digit == decision.true_digits[wheel - 1])
                is_target = int(
                    bool(is_true_gate) and wheel == decision.binding_wheel
                )
                probe_binding_label = int(wheel == decision.binding_wheel)

            specs.append(
                {
                    "candidate_index": candidate_index,
                    "task_type": decision.task_type,
                    "direction": decision.direction,
                    "wheel": wheel,
                    "scan_position": scan_position,
                    "move_index": move_index,
                    "before_code": "".join(str(v) for v in before),
                    "after_code": "".join(str(v) for v in after),
                    "from_digit": before[wheel - 1],
                    "to_digit": to_digit,
                    "is_true_gate_movement": int(is_true_gate),
                    "is_target": int(is_target),
                    "prefix_stage": decision.prefix_stage,
                    "prefix_valid": decision.prefix_valid,
                    "expected_binding_wheel": decision.expected_binding_wheel,
                    "probe_binding_label": probe_binding_label,
                }
            )
            code = after
            candidate_index += 1
        if code != list(decision.start_digits):
            raise DecisionBatchError(
                f"{decision.workflow_label} {decision.key} W{wheel} did not return to the planned start code"
            )

    if not decision.is_binding_scan:
        targets = [spec for spec in specs if spec["is_target"] == 1]
        if len(targets) != 1:
            raise DecisionBatchError(
                f"Decision {decision.key} must have exactly one target candidate; found {len(targets)}"
            )
    return specs


class DecisionProgressStore:
    def progress_path(
        self,
        *,
        dataset_dir: Path,
        session_id: str,
        decision: DecisionBatchRow,
    ) -> Path:
        return (
            dataset_dir
            / decision.storage_root
            / "_progress"
            / session_id
            / f"{decision.key}.json"
        )

    def _base_payload(
        self,
        *,
        decision: DecisionBatchRow,
        plan_file: Path,
        session_id: str,
    ) -> dict[str, object]:
        return {
            "version": 3,
            "task_type": decision.task_type,
            "session_id": session_id,
            "profile_id": decision.profile_id,
            "group_id": decision.group_id,
            "decision_id": decision.decision_id,
            "repeat_id": decision.repeat_id,
            "decision_key": decision.key,
            "direction": decision.direction,
            "force_reseat_before": decision.force_reseat_before,
            "start_code": decision.start_code,
            "active_wheels": list(decision.active_wheels),
            "scan_order": list(decision.scan_order),
            "binding_wheel": decision.binding_wheel,
            "binding_confidence": decision.binding_confidence,
            "prefix_stage": decision.prefix_stage,
            "prefix_valid": decision.prefix_valid,
            "expected_binding_wheel": decision.expected_binding_wheel,
            "preserve_inactive_start": decision.preserve_inactive_start,
            "true_digits": list(decision.true_digits),
            "target_digit": decision.target_digit,
            "planned_runs": decision.planned_runs,
            "plan_file": str(plan_file),
            "plan_source_row": decision.source_row,
            "notes": decision.notes,
            "candidates": {},
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    def load(
        self,
        *,
        dataset_dir: Path,
        session_id: str,
        decision: DecisionBatchRow,
        plan_file: Path,
    ) -> dict[str, object]:
        path = self.progress_path(
            dataset_dir=dataset_dir,
            session_id=session_id,
            decision=decision,
        )
        if not path.exists():
            return self._base_payload(
                decision=decision,
                plan_file=plan_file,
                session_id=session_id,
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("decision_key") != decision.key:
            raise DecisionBatchError(f"Progress file does not match {decision.key}: {path}")
        stored_task = str(payload.get("task_type") or "digit_scan").strip().lower()
        if stored_task != decision.task_type:
            raise DecisionBatchError(
                f"Progress task_type {stored_task!r} does not match plan {decision.task_type!r} "
                f"for {decision.key}. Use a new Session ID or the matching plan."
            )
        stored_direction = str(payload.get("direction") or "CCW").upper()
        if stored_direction != decision.direction:
            raise DecisionBatchError(
                f"Progress direction {stored_direction} does not match plan direction {decision.direction} "
                f"for {decision.key}. Use a new Session ID or the matching plan."
            )
        return payload

    def save(
        self,
        *,
        dataset_dir: Path,
        session_id: str,
        decision: DecisionBatchRow,
        plan_file: Path,
        payload: dict[str, object],
    ) -> Path:
        path = self.progress_path(
            dataset_dir=dataset_dir,
            session_id=session_id,
            decision=decision,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        payload["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
        return path

    def record_result(
        self,
        *,
        dataset_dir: Path,
        session_id: str,
        decision: DecisionBatchRow,
        plan_file: Path,
        result: RunResult,
    ) -> Path:
        payload = self.load(
            dataset_dir=dataset_dir,
            session_id=session_id,
            decision=decision,
            plan_file=plan_file,
        )
        candidates = payload.setdefault("candidates", {})
        if not isinstance(candidates, dict):
            raise DecisionBatchError("Decision progress candidates field is invalid")
        request = result.request
        output_dir = ""
        if result.output_dir is not None:
            try:
                output_dir = str(Path(result.output_dir).relative_to(dataset_dir))
            except ValueError:
                output_dir = str(result.output_dir)
        candidates[str(request.decision_candidate_index)] = {
            "candidate_index": request.decision_candidate_index,
            "run_id": request.run_id,
            "status": result.status.value,
            "output_dir": output_dir,
            "direction": request.direction,
            "wheel": request.wheel_index,
            "scan_position": request.decision_scan_position,
            "move_index": request.decision_move_index,
            "before_code": request.current_code_before,
            "after_code": request.current_code_after,
            "from_digit": request.start_digit,
            "to_digit": request.end_digit,
            "is_true_gate_movement": request.decision_is_true_gate_movement,
            "is_target": request.decision_is_target,
            "binding_wheel": request.decision_binding_wheel,
            "target_digit": request.decision_target_digit,
            "task_type": request.batch_task_type,
            "prefix_stage": request.binding_prefix_stage,
            "prefix_valid": request.binding_prefix_valid,
            "expected_binding_wheel": request.binding_expected_wheel,
            "probe_wheel": request.binding_probe_wheel,
            "probe_binding_label": (
                (
                    -1
                    if request.binding_expected_wheel == 0
                    else int(
                        request.binding_prefix_valid == 1
                        and request.binding_expected_wheel == request.binding_probe_wheel
                    )
                )
                if str(request.batch_task_type or "digit_scan").strip().lower() == "binding_scan"
                else int(request.wheel_index == request.decision_binding_wheel)
            ),
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        return self.save(
            dataset_dir=dataset_dir,
            session_id=session_id,
            decision=decision,
            plan_file=plan_file,
            payload=payload,
        )

    def valid_indices(
        self,
        *,
        dataset_dir: Path,
        session_id: str,
        decision: DecisionBatchRow,
        plan_file: Path,
    ) -> set[int]:
        payload = self.load(
            dataset_dir=dataset_dir,
            session_id=session_id,
            decision=decision,
            plan_file=plan_file,
        )
        candidates = payload.get("candidates", {})
        if not isinstance(candidates, dict):
            return set()
        return {
            int(key)
            for key, value in candidates.items()
            if isinstance(value, dict) and value.get("status") == RunStatus.VALID.value
        }

    def first_missing_index(
        self,
        *,
        dataset_dir: Path,
        session_id: str,
        decision: DecisionBatchRow,
        plan_file: Path,
    ) -> int | None:
        valid = self.valid_indices(
            dataset_dir=dataset_dir,
            session_id=session_id,
            decision=decision,
            plan_file=plan_file,
        )
        for index in range(1, decision.planned_runs + 1):
            if index not in valid:
                return index
        return None

    def delete_from_index(
        self,
        *,
        dataset_dir: Path,
        session_id: str,
        decision: DecisionBatchRow,
        plan_file: Path,
        start_index: int,
    ) -> int:
        if start_index not in range(1, decision.planned_runs + 1):
            raise DecisionBatchError("Resume candidate index is out of range")
        payload = self.load(
            dataset_dir=dataset_dir,
            session_id=session_id,
            decision=decision,
            plan_file=plan_file,
        )
        candidates = payload.get("candidates", {})
        if not isinstance(candidates, dict):
            raise DecisionBatchError("Decision progress candidates field is invalid")
        deleted = 0
        for key in list(candidates):
            try:
                index = int(key)
            except ValueError:
                continue
            if index < start_index:
                continue
            record = candidates.pop(key)
            if isinstance(record, dict):
                output_text = str(record.get("output_dir") or "")
                if output_text:
                    output_path = Path(output_text)
                    if not output_path.is_absolute():
                        output_path = dataset_dir / output_path
                    if output_path.exists() and output_path.is_dir():
                        shutil.rmtree(output_path)
            deleted += 1
        self.save(
            dataset_dir=dataset_dir,
            session_id=session_id,
            decision=decision,
            plan_file=plan_file,
            payload=payload,
        )
        return deleted

    def records(
        self,
        *,
        dataset_dir: Path,
        session_id: str,
        decision: DecisionBatchRow,
        plan_file: Path,
    ) -> list[dict[str, object]]:
        payload = self.load(
            dataset_dir=dataset_dir,
            session_id=session_id,
            decision=decision,
            plan_file=plan_file,
        )
        candidates = payload.get("candidates", {})
        if not isinstance(candidates, dict):
            return []
        ordered: list[dict[str, object]] = []
        for index in range(1, decision.planned_runs + 1):
            record = candidates.get(str(index))
            if isinstance(record, dict):
                ordered.append(record)
        return ordered


class DecisionBatchFinalizer:
    def finalise_decision(
        self,
        *,
        dataset_dir: Path,
        session_id: str,
        plan_file: Path,
        decision: DecisionBatchRow,
        progress_store: DecisionProgressStore,
    ) -> Path:
        records = progress_store.records(
            dataset_dir=dataset_dir,
            session_id=session_id,
            decision=decision,
            plan_file=plan_file,
        )
        if len(records) != decision.planned_runs:
            raise DecisionBatchError(
                f"{decision.workflow_label} {decision.key} requires {decision.planned_runs} recorded WAVs; "
                f"found {len(records)}"
            )
        if any(record.get("status") != RunStatus.VALID.value for record in records):
            raise DecisionBatchError(
                f"{decision.workflow_label} {decision.key} cannot be finalised until every WAV is VALID"
            )

        specs = decision_candidate_specs(decision)
        for spec, record in zip(specs, records, strict=True):
            checks = {
                "candidate_index": spec["candidate_index"],
                "wheel": spec["wheel"],
                "scan_position": spec["scan_position"],
                "move_index": spec["move_index"],
                "before_code": spec["before_code"],
                "after_code": spec["after_code"],
                "from_digit": spec["from_digit"],
                "to_digit": spec["to_digit"],
                "is_true_gate_movement": spec["is_true_gate_movement"],
                "is_target": spec["is_target"],
                "task_type": spec["task_type"],
                "prefix_stage": spec["prefix_stage"],
                "prefix_valid": spec["prefix_valid"],
                "expected_binding_wheel": spec["expected_binding_wheel"],
                "probe_binding_label": spec["probe_binding_label"],
            }
            record_direction = str(record.get("direction") or "CCW").upper()
            if record_direction != decision.direction:
                raise DecisionBatchError(
                    f"{decision.workflow_label} {decision.key} WAV {spec['candidate_index']} direction="
                    f"{record_direction!r}, expected {decision.direction!r}"
                )
            for field, expected in checks.items():
                # Compatibility repair for the short-lived blind-binding patch regression:
                # ordinary Digit Scan records could have probe_binding_label=-1 written
                # because expected_binding_wheel=0 was incorrectly treated as an
                # unlabelled Binding Scan.  Repair that field in-memory so already
                # collected valid WAVs can finalise without recollection.
                if (
                    field == "probe_binding_label"
                    and not decision.is_binding_scan
                    and record.get(field) == -1
                ):
                    record[field] = expected
                if record.get(field) != expected:
                    raise DecisionBatchError(
                        f"{decision.workflow_label} {decision.key} WAV {spec['candidate_index']} field "
                        f"{field}={record.get(field)!r}, expected {expected!r}"
                    )
            output_text = str(record.get("output_dir") or "")
            output_path = Path(output_text)
            if not output_path.is_absolute():
                output_path = dataset_dir / output_path
            if not output_path.exists():
                raise DecisionBatchError(
                    f"{decision.workflow_label} {decision.key} WAV {spec['candidate_index']} run folder is missing"
                )

        output_dir = dataset_dir / decision.storage_root / session_id / decision.key
        if output_dir.exists():
            raise DecisionBatchError(f"Batch output already exists: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=False)

        payload = {
            "version": 3,
            "task_type": decision.task_type,
            "profile_id": decision.profile_id,
            "group_id": decision.group_id,
            "decision_id": decision.decision_id,
            "repeat_id": decision.repeat_id,
            "decision_key": decision.key,
            "session_id": session_id,
            "start_digits": list(decision.start_digits),
            "start_code": decision.start_code,
            "active_wheels": list(decision.active_wheels),
            "active_mask": list(decision.active_mask),
            "scan_order": list(decision.scan_order),
            "direction": decision.direction,
            "force_reseat_before": decision.force_reseat_before,
            "movement_protocol": (
                "continuous one-digit Binding Scan probe WAVs"
                if decision.is_binding_scan
                else "continuous one-digit Digit Scan candidates"
            ),
            "binding_wheel": decision.binding_wheel,
            "binding_confidence": decision.binding_confidence,
            "prefix_stage": decision.prefix_stage,
            "prefix_valid": decision.prefix_valid,
            "expected_binding_wheel": decision.expected_binding_wheel,
            "preserve_inactive_start": decision.preserve_inactive_start,
            "true_digits": list(decision.true_digits),
            "target_digit": decision.target_digit,
            "planned_runs": decision.planned_runs,
            "plan_file": str(plan_file),
            "plan_source_row": decision.source_row,
            "notes": decision.notes,
            "candidates": records,
            "finalised_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        json_name = "binding_scan.json" if decision.is_binding_scan else "decision.json"
        (output_dir / json_name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._append_manifest(
            dataset_dir=dataset_dir,
            session_id=session_id,
            plan_file=plan_file,
            decision=decision,
            output_dir=output_dir,
        )
        return output_dir

    @staticmethod
    def _append_manifest(
        *,
        dataset_dir: Path,
        session_id: str,
        plan_file: Path,
        decision: DecisionBatchRow,
        output_dir: Path,
    ) -> None:
        scan_values = list(decision.scan_order) + [0] * (4 - len(decision.scan_order))
        common = {
            "session_id": session_id,
            "profile_id": decision.profile_id,
            "group_id": decision.group_id,
            "decision_id": decision.decision_id,
            "repeat_id": decision.repeat_id,
            "start_w1": decision.start_digits[0],
            "start_w2": decision.start_digits[1],
            "start_w3": decision.start_digits[2],
            "start_w4": decision.start_digits[3],
            "active_w1": decision.active_mask[0],
            "active_w2": decision.active_mask[1],
            "active_w3": decision.active_mask[2],
            "active_w4": decision.active_mask[3],
            "scan_1": scan_values[0],
            "scan_2": scan_values[1],
            "scan_3": scan_values[2],
            "scan_4": scan_values[3],
            "direction": decision.direction,
            "binding_confidence": decision.binding_confidence,
            "preserve_inactive_start": int(decision.preserve_inactive_start),
            "true_w1": decision.true_digits[0],
            "true_w2": decision.true_digits[1],
            "true_w3": decision.true_digits[2],
            "true_w4": decision.true_digits[3],
            "planned_runs": decision.planned_runs,
            "plan_file": str(plan_file),
            "plan_source_row": decision.source_row,
        }

        if decision.is_binding_scan:
            manifest_path = dataset_dir / "binding_scan_manifest_v1.csv"
            fieldnames = [
                "session_id", "profile_id", "group_id", "decision_id", "repeat_id",
                "start_w1", "start_w2", "start_w3", "start_w4",
                "active_w1", "active_w2", "active_w3", "active_w4",
                "scan_1", "scan_2", "scan_3", "scan_4", "direction",
                "prefix_stage", "prefix_valid", "expected_binding_wheel",
                "binding_confidence", "preserve_inactive_start",
                "true_w1", "true_w2", "true_w3", "true_w4",
                "planned_runs", "binding_scan_dir", "plan_file", "plan_source_row",
            ]
            row = dict(common)
            row.update(
                {
                    "prefix_stage": decision.prefix_stage,
                    "prefix_valid": decision.prefix_valid,
                    "expected_binding_wheel": decision.expected_binding_wheel,
                    "binding_scan_dir": str(output_dir.relative_to(dataset_dir)),
                }
            )
        else:
            manifest_path = dataset_dir / "decision_dataset_manifest_v2.csv"
            fieldnames = [
                "session_id", "profile_id", "group_id", "decision_id", "repeat_id",
                "start_w1", "start_w2", "start_w3", "start_w4",
                "active_w1", "active_w2", "active_w3", "active_w4",
                "scan_1", "scan_2", "scan_3", "scan_4", "direction",
                "binding_wheel", "binding_confidence", "preserve_inactive_start",
                "true_w1", "true_w2", "true_w3", "true_w4",
                "target_digit", "planned_runs", "decision_dir", "plan_file", "plan_source_row",
            ]
            row = dict(common)
            row.update(
                {
                    "binding_wheel": decision.binding_wheel,
                    "target_digit": decision.target_digit,
                    "decision_dir": str(output_dir.relative_to(dataset_dir)),
                }
            )

        write_header = not manifest_path.exists()
        with manifest_path.open("a", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerow({field: row.get(field, "") for field in fieldnames})

