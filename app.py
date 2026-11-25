#!/usr/bin/env python3
"""Light Retouch Management System V4 - standalone, dependency-free web application.

Run: python app.py
Database: SQLite (created automatically in instance/hrms.db)
All timestamps are stored in ISO format using Asia/Dhaka local server time.
"""
from __future__ import annotations

import hashlib
import base64
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import tempfile
import zipfile
import urllib.parse
import uuid
from datetime import datetime, date, time, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("HRMS_DB_PATH", BASE_DIR / "instance" / "hrms.db"))
PAYROLL_DB_PATH = Path(os.environ.get("HRMS_PAYROLL_DB_PATH", BASE_DIR / "instance" / "payroll_private.db"))
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"
UPLOAD_DIR = BASE_DIR / "uploads"
BACKUP_DIR = BASE_DIR / "backups"
HOST = os.environ.get("HRMS_HOST", "0.0.0.0")
PORT = int(os.environ.get("HRMS_PORT", "8000"))
TZ_NAME = "Asia/Dhaka"
TZ = ZoneInfo(TZ_NAME)
SESSION_COOKIE = "lr_hrms_session"
SESSION_TTL = 60 * 60 * 10
SESSIONS: dict[str, dict[str, Any]] = {}
LOGIN_ATTEMPTS: dict[str, list[float]] = {}
SESSION_LOCK = threading.RLock()
DB_LOCK = threading.RLock()

ROLES = {
    "super_admin": "Super Admin",
    "hr_admin": "HR Admin",
    "hr_executive": "HR Executive",
    "payroll_admin": "Payroll Admin",
    "manager": "Department Manager",
    "employee": "Employee",
}
HR_ROLES = {"super_admin", "hr_admin", "hr_executive"}
ADMIN_ROLES = {"super_admin", "hr_admin"}
PAYROLL_ROLES = {"super_admin", "payroll_admin"}
MANAGER_ROLES = {"super_admin", "hr_admin", "hr_executive", "manager"}
ALL_ROLES = set(ROLES)

SCHEMA = r"""
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL,
  employee_id TEXT UNIQUE,
  is_active INTEGER NOT NULL DEFAULT 1,
  must_change_password INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  last_login TEXT,
  FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
);
CREATE TABLE IF NOT EXISTS departments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  description TEXT DEFAULT '',
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS designations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  department_id INTEGER,
  description TEXT DEFAULT '',
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  UNIQUE(name, department_id),
  FOREIGN KEY(department_id) REFERENCES departments(id)
);
CREATE TABLE IF NOT EXISTS shifts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  start_time TEXT,
  end_time TEXT,
  break_minutes INTEGER,
  break_is_paid INTEGER NOT NULL DEFAULT 0,
  grace_minutes INTEGER,
  weekly_off_days TEXT DEFAULT '[]',
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS employees (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employee_id TEXT NOT NULL UNIQUE,
  full_name TEXT NOT NULL,
  profile_photo TEXT DEFAULT '',
  personal_email TEXT DEFAULT '',
  company_email TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  emergency_contact TEXT DEFAULT '',
  department_id INTEGER,
  designation_id INTEGER,
  reporting_manager TEXT DEFAULT '',
  employment_type TEXT DEFAULT 'Full-time',
  employment_status TEXT NOT NULL DEFAULT 'Active',
  joining_date TEXT DEFAULT '',
  probation_start_date TEXT DEFAULT '',
  probation_end_date TEXT DEFAULT '',
  confirmation_date TEXT DEFAULT '',
  work_location TEXT DEFAULT 'Mirpur 13, Dhaka',
  shift_id INTEGER,
  remarks TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(department_id) REFERENCES departments(id),
  FOREIGN KEY(designation_id) REFERENCES designations(id),
  FOREIGN KEY(shift_id) REFERENCES shifts(id)
);
CREATE TABLE IF NOT EXISTS attendance_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  employee_id TEXT NOT NULL,
  event_type TEXT NOT NULL CHECK(event_type IN ('CHECK_IN','CHECK_OUT')),
  event_time TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'web',
  note TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
);
CREATE INDEX IF NOT EXISTS idx_attendance_employee_time ON attendance_events(employee_id, event_time);
CREATE TABLE IF NOT EXISTS attendance_adjustments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT NOT NULL UNIQUE,
  employee_id TEXT NOT NULL,
  work_date TEXT NOT NULL,
  requested_check_in TEXT,
  requested_check_out TEXT,
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'Pending',
  reviewer TEXT DEFAULT '',
  review_comment TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  reviewed_at TEXT,
  FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
);
CREATE TABLE IF NOT EXISTS leave_types (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  entitlement_days REAL,
  paid_status TEXT DEFAULT 'To be configured',
  is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS leave_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT NOT NULL UNIQUE,
  employee_id TEXT NOT NULL,
  leave_type_id INTEGER,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  days REAL NOT NULL,
  reason TEXT NOT NULL,
  document_file_id TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'Pending Manager Approval',
  manager_decision TEXT DEFAULT '',
  manager_comment TEXT DEFAULT '',
  manager_decided_by TEXT DEFAULT '',
  manager_decided_at TEXT,
  hr_decision TEXT DEFAULT '',
  hr_comment TEXT DEFAULT '',
  hr_decided_by TEXT DEFAULT '',
  hr_decided_at TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(employee_id) REFERENCES employees(employee_id),
  FOREIGN KEY(leave_type_id) REFERENCES leave_types(id)
);
CREATE TABLE IF NOT EXISTS holidays (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  holiday_date TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_id TEXT NOT NULL UNIQUE,
  full_name TEXT NOT NULL,
  email TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  position TEXT NOT NULL,
  source TEXT DEFAULT '',
  stage TEXT NOT NULL DEFAULT 'Applied',
  interview_date TEXT,
  notes TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id TEXT NOT NULL UNIQUE,
  asset_name TEXT NOT NULL,
  category TEXT DEFAULT '',
  serial_number TEXT DEFAULT '',
  purchase_date TEXT DEFAULT '',
  assigned_employee TEXT,
  assignment_date TEXT,
  condition_status TEXT DEFAULT 'Good',
  return_date TEXT,
  return_condition TEXT DEFAULT '',
  notes TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  FOREIGN KEY(assigned_employee) REFERENCES employees(employee_id)
);
CREATE TABLE IF NOT EXISTS performance_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  review_id TEXT NOT NULL UNIQUE,
  employee_id TEXT NOT NULL,
  review_period TEXT NOT NULL,
  review_type TEXT DEFAULT 'Quarterly',
  score REAL,
  reviewer TEXT NOT NULL,
  feedback TEXT DEFAULT '',
  goals TEXT DEFAULT '',
  status TEXT DEFAULT 'Draft',
  created_at TEXT NOT NULL,
  FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
);
CREATE TABLE IF NOT EXISTS disciplinary_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id TEXT NOT NULL UNIQUE,
  employee_id TEXT NOT NULL,
  record_type TEXT NOT NULL,
  incident_date TEXT NOT NULL,
  description TEXT NOT NULL,
  employee_response TEXT DEFAULT '',
  decision TEXT DEFAULT 'Pending Review',
  follow_up_date TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
);
CREATE TABLE IF NOT EXISTS exit_checklists (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  exit_id TEXT NOT NULL UNIQUE,
  employee_id TEXT NOT NULL,
  exit_type TEXT DEFAULT 'Resignation',
  notice_start TEXT DEFAULT '',
  last_working_day TEXT DEFAULT '',
  resignation_document INTEGER NOT NULL DEFAULT 0,
  attendance_clearance INTEGER NOT NULL DEFAULT 0,
  leave_clearance INTEGER NOT NULL DEFAULT 0,
  asset_clearance INTEGER NOT NULL DEFAULT 0,
  account_clearance INTEGER NOT NULL DEFAULT 0,
  manager_clearance INTEGER NOT NULL DEFAULT 0,
  hr_clearance INTEGER NOT NULL DEFAULT 0,
  finance_clearance INTEGER NOT NULL DEFAULT 0,
  final_settlement INTEGER NOT NULL DEFAULT 0,
  status TEXT DEFAULT 'In Progress',
  notes TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
);
CREATE TABLE IF NOT EXISTS production_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL UNIQUE,
  project_name TEXT NOT NULL,
  client_name TEXT DEFAULT '',
  task_title TEXT NOT NULL,
  editing_type TEXT NOT NULL,
  priority TEXT NOT NULL DEFAULT 'Normal',
  image_count INTEGER NOT NULL DEFAULT 1,
  due_date TEXT,
  instructions TEXT DEFAULT '',
  source_link TEXT DEFAULT '',
  assigned_scope TEXT NOT NULL DEFAULT 'Selected',
  is_active INTEGER NOT NULL DEFAULT 1,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_assignments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  employee_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'Assigned',
  completed_images INTEGER NOT NULL DEFAULT 0,
  output_link TEXT DEFAULT '',
  submission_notes TEXT DEFAULT '',
  submitted_at TEXT,
  review_note TEXT DEFAULT '',
  reviewed_by TEXT DEFAULT '',
  reviewed_at TEXT,
  started_at TEXT,
  updated_at TEXT NOT NULL,
  UNIQUE(task_id, employee_id),
  FOREIGN KEY(task_id) REFERENCES production_tasks(task_id),
  FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
);
CREATE INDEX IF NOT EXISTS idx_task_assign_employee ON task_assignments(employee_id,status);
CREATE INDEX IF NOT EXISTS idx_task_created ON production_tasks(created_at);
CREATE TABLE IF NOT EXISTS recruitment_positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS private_files (
  file_id TEXT PRIMARY KEY,
  owner_employee_id TEXT DEFAULT '',
  category TEXT NOT NULL,
  entity_id TEXT DEFAULT '',
  original_name TEXT NOT NULL,
  stored_name TEXT NOT NULL,
  content_type TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_settings (
  setting_key TEXT PRIMARY KEY,
  setting_value TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id TEXT DEFAULT '',
  details TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schema_migrations (
  migration_key TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL,
  details TEXT DEFAULT ''
);
"""


def now_dt() -> datetime:
    return datetime.now(TZ)


def now_iso() -> str:
    return now_dt().replace(microsecond=0).isoformat()


def today_iso() -> str:
    return now_dt().date().isoformat()


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return con


def connect_payroll_db() -> sqlite3.Connection:
    PAYROLL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(PAYROLL_DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return con


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
    return f"pbkdf2_sha256$240000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        calculated = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)).hex()
        return hmac.compare_digest(calculated, digest_hex)
    except Exception:
        return False


def invalidate_user_sessions(user_ids: set[int] | list[int] | tuple[int, ...]) -> None:
    """Immediately revoke live sessions after account, role or employment access changes."""
    ids = {int(value) for value in user_ids if value is not None}
    if not ids:
        return
    with SESSION_LOCK:
        for token, session in list(SESSIONS.items()):
            if int(session.get("user_id", -1)) in ids:
                SESSIONS.pop(token, None)


def ensure_column(con: sqlite3.Connection, table: str, definition: str) -> None:
    column = definition.split()[0]
    existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def create_pre_migration_backup(con: sqlite3.Connection, label: str) -> Path:
    """Create a consistent SQLite snapshot before modifying existing production data."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now_dt().strftime("%Y%m%d_%H%M%S")
    target_path = BACKUP_DIR / f"{label}_{stamp}.sqlite3"
    target = sqlite3.connect(target_path)
    try:
        con.backup(target)
        target.commit()
    finally:
        target.close()
    verify = sqlite3.connect(target_path)
    try:
        check = verify.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            target_path.unlink(missing_ok=True)
            raise RuntimeError(f"Pre-migration backup integrity check failed: {check}")
    finally:
        verify.close()
    return target_path


def apply_time_interpretation_migration(con: sqlite3.Connection) -> None:
    """Convert legacy ambiguous shift times to explicit 24-hour values, with a verified backup.

    The old UI stored HH:MM without AM/PM. The shift names and configured values in the
    supplied database establish these intended patterns:
      Morning: 07:30 AM–03:30 PM
      Evening: 03:30 PM–11:30 PM
      Night: 11:30 PM–07:30 AM
    Only exact legacy patterns are changed. Other/custom shifts are left untouched.
    """
    migration_key = "20261124_explicit_am_pm_legacy_time_fix_v2"
    if con.execute("SELECT 1 FROM schema_migrations WHERE migration_key=?", (migration_key,)).fetchone():
        return

    specs = [
        {
            "name": "Morning Shift", "old_start": "07:30", "old_end": "03:30",
            "new_start": "07:30", "new_end": "15:30",
            "adjustments": (("requested_check_out", "03:30", "15:30"),),
        },
        {
            "name": "Evening Shift", "old_start": "03:30", "old_end": "11:30",
            "new_start": "15:30", "new_end": "23:30",
            "adjustments": (("requested_check_in", "03:30", "15:30"), ("requested_check_out", "11:30", "23:30")),
        },
        {
            "name": "Night Shift", "old_start": "11:30", "old_end": "07:30",
            "new_start": "23:30", "new_end": "07:30",
            "adjustments": (("requested_check_in", "11:30", "23:30"),),
        },
    ]
    pending = []
    for spec in specs:
        row = con.execute(
            "SELECT id,start_time,end_time FROM shifts WHERE lower(name)=lower(?) ORDER BY id LIMIT 1",
            (spec["name"],),
        ).fetchone()
        if row and row["start_time"] == spec["old_start"] and row["end_time"] == spec["old_end"]:
            pending.append((spec, row["id"]))

    con.commit()
    backup_path = None
    if pending:
        backup_path = create_pre_migration_backup(con, "hrms_before_explicit_am_pm_migration")

    migration_details = {
        "backup_file": str(backup_path.relative_to(BASE_DIR)) if backup_path and backup_path.is_relative_to(BASE_DIR) else (str(backup_path) if backup_path else ""),
        "changed_shifts": [],
        "approved_and_pending_adjustments_corrected": 0,
        "raw_attendance_events_preserved": True,
        "payroll_history_recalculated": False,
    }
    for spec, shift_id in pending:
        con.execute(
            "UPDATE shifts SET start_time=?,end_time=? WHERE id=?",
            (spec["new_start"], spec["new_end"], shift_id),
        )
        employee_ids = [r[0] for r in con.execute(
            "SELECT employee_id FROM employees WHERE shift_id=?", (shift_id,)
        ).fetchall()]
        changed_adjustments = 0
        if employee_ids:
            placeholders = ",".join("?" for _ in employee_ids)
            for column, old_value, new_value in spec["adjustments"]:
                # Column names come only from the fixed migration definitions above.
                cursor = con.execute(
                    f"UPDATE attendance_adjustments SET {column}=? WHERE {column}=? AND status NOT IN ('Rejected','Cancelled') AND employee_id IN ({placeholders})",
                    (new_value, old_value, *employee_ids),
                )
                changed_adjustments += max(0, cursor.rowcount)
        migration_details["approved_and_pending_adjustments_corrected"] += changed_adjustments
        migration_details["changed_shifts"].append({
            "name": spec["name"],
            "from": f"{spec['old_start']}–{spec['old_end']} (legacy ambiguous 12-hour values)",
            "to": f"{spec['new_start']}–{spec['new_end']} (24-hour canonical storage)",
            "adjustments_corrected": changed_adjustments,
        })
    audit(con, "system:migration", "EXPLICIT_AM_PM_TIME_FIX", "AttendanceTime", migration_key, migration_details)
    con.execute(
        "INSERT INTO schema_migrations(migration_key,applied_at,details) VALUES(?,?,?)",
        (migration_key, now_iso(), json.dumps(migration_details, ensure_ascii=False)),
    )


def normalize_time_input(value: Any, label: str = "Time") -> str | None:
    """Accept canonical 24-hour HH:MM or explicit 12-hour AM/PM and return HH:MM."""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().upper().replace(".", "")
    match12 = re.fullmatch(r"(0?[1-9]|1[0-2]):([0-5]\d)\s*(AM|PM)", text)
    if match12:
        hour = int(match12.group(1)) % 12
        if match12.group(3) == "PM":
            hour += 12
        return f"{hour:02d}:{match12.group(2)}"
    match24 = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", text)
    if match24:
        return f"{int(match24.group(1)):02d}:{match24.group(2)}"
    raise ValueError(f"{label} must include a valid time and AM/PM (for example 07:30 AM or 03:30 PM)")


def init_db() -> None:
    with DB_LOCK:
        con = connect_db()
        con.executescript(SCHEMA)
        # The initial account is only for local first-run setup. Change its password immediately.
        admin = con.execute("SELECT id FROM users WHERE username=?", ("admin@lightretouch.local",)).fetchone()
        if not admin:
            con.execute(
                "INSERT INTO users(username,password_hash,role,created_at,must_change_password) VALUES(?,?,?,?,1)",
                ("admin@lightretouch.local", hash_password(os.environ.get("HRMS_ADMIN_PASSWORD", "ChangeMeNow!2026")), "super_admin", now_iso()),
            )
        ensure_column(con, "shifts", "break_is_paid INTEGER NOT NULL DEFAULT 0")
        ensure_column(con, "leave_requests", "document_file_id TEXT DEFAULT ''")
        ensure_column(con, "production_tasks", "is_active INTEGER NOT NULL DEFAULT 1")
        ensure_column(con, "candidates", "is_archived INTEGER NOT NULL DEFAULT 0")
        ensure_column(con, "assets", "is_archived INTEGER NOT NULL DEFAULT 0")
        ensure_column(con, "performance_reviews", "is_archived INTEGER NOT NULL DEFAULT 0")
        ensure_column(con, "disciplinary_records", "is_archived INTEGER NOT NULL DEFAULT 0")
        ensure_column(con, "exit_checklists", "is_archived INTEGER NOT NULL DEFAULT 0")
        defaults = {
            "company_name": "Light Retouch",
            "system_name": "Light Retouch Management System",
            "brand_logo": "",
            "timezone": TZ_NAME,
            "currency": "BDT",
            "work_location": "Mirpur 13, Dhaka, Bangladesh",
            "attendance_grace_minutes": "",
            "standard_working_hours": "",
            "payroll_day": "",
            "leave_year_start": "",
            "policy_note": "Configure company-approved shifts, leave entitlements and payroll rules before live use.",
        }
        for key, value in defaults.items():
            con.execute("INSERT OR IGNORE INTO app_settings(setting_key,setting_value,updated_at,updated_by) VALUES(?,?,?,?)", (key, value, now_iso(), "system"))
        for name in ["Casual Leave", "Sick Leave", "Annual Leave", "Unpaid Leave", "Other Approved Leave"]:
            con.execute("INSERT OR IGNORE INTO leave_types(name,entitlement_days,paid_status,is_active) VALUES(?,NULL,'To be configured',1)", (name,))
        # Editable demo master data. Names explicitly indicate examples; HR can change/archive them in Settings.
        demo_departments = ["Production Team (Demo)", "Quality Control (Demo)", "Human Resources (Demo)", "Business Development (Demo)", "Finance & Administration (Demo)"]
        for name in demo_departments:
            con.execute("INSERT OR IGNORE INTO departments(name,description,created_at) VALUES(?,?,?)", (name, "Demo master record - edit to match company structure", now_iso()))
        dep_map = {r["name"]: r["id"] for r in con.execute("SELECT id,name FROM departments").fetchall()}
        demo_designations = [
            ("Photo Retoucher (Demo)", "Production Team (Demo)"), ("Senior Photo Retoucher (Demo)", "Production Team (Demo)"),
            ("Production Team Leader (Demo)", "Production Team (Demo)"), ("Quality Controller (Demo)", "Quality Control (Demo)"),
            ("HR Executive (Demo)", "Human Resources (Demo)"), ("Lead Generation Specialist (Demo)", "Business Development (Demo)"),
            ("Sales Development Executive (Demo)", "Business Development (Demo)"), ("Accounts Executive (Demo)", "Finance & Administration (Demo)")]
        for name, dep in demo_designations:
            con.execute("INSERT OR IGNORE INTO designations(name,department_id,description,created_at) VALUES(?,?,?,?)", (name, dep_map.get(dep), "Demo master record - edit/archive as needed", now_iso()))
        con.execute("INSERT OR IGNORE INTO shifts(name,start_time,end_time,break_minutes,grace_minutes,weekly_off_days,is_active,created_at) VALUES(?,?,?,?,?,?,1,?)", ("General Shift (Demo)", "09:00", "18:00", 60, 10, json.dumps(["Friday"]), now_iso()))
        demo_positions = ["Photo Retoucher (Demo)", "Senior Photo Retoucher (Demo)", "Clipping Path Specialist (Demo)", "Background Removal Editor (Demo)", "Image Masking Specialist (Demo)", "Product Photo Retoucher (Demo)", "Jewelry Retoucher (Demo)", "Ghost Mannequin Editor (Demo)", "Quality Controller (Demo)", "Production Team Leader (Demo)", "HR Executive (Demo)", "Lead Generation Specialist (Demo)", "Sales Development Executive (Demo)"]
        for name in demo_positions:
            con.execute("INSERT OR IGNORE INTO recruitment_positions(name,created_at) VALUES(?,?)", (name, now_iso()))
        apply_time_interpretation_migration(con)
        con.commit()
        con.close()
        payroll_con = connect_payroll_db()
        payroll_con.executescript(PAYROLL_SCHEMA)
        for definition in (
            "scheduled_days REAL NOT NULL DEFAULT 0", "present_days REAL NOT NULL DEFAULT 0",
            "late_days REAL NOT NULL DEFAULT 0", "absent_days REAL NOT NULL DEFAULT 0",
            "paid_leave_days REAL NOT NULL DEFAULT 0", "payable_days REAL NOT NULL DEFAULT 0",
            "attendance_factor REAL NOT NULL DEFAULT 0", "calculation_status TEXT NOT NULL DEFAULT 'Pending'"
        ):
            ensure_column(payroll_con, "payroll_items", definition)
        payroll_con.commit()
        payroll_con.close()


def rowdict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def rowsdict(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def audit(con: sqlite3.Connection, actor: str, action: str, entity: str, entity_id: str = "", details: Any = "") -> None:
    if not isinstance(details, str):
        details = json.dumps(details, ensure_ascii=False, default=str)
    con.execute("INSERT INTO audit_logs(actor,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)", (actor, action, entity, str(entity_id), details[:6000], now_iso()))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        number = float(value)
        if number != number or abs(number) == float("inf"):
            return default
        return number
    except (TypeError, ValueError):
        return default


def valid_date(value: str, field: str = "date") -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except Exception:
        raise ValueError(f"{field} must be a valid YYYY-MM-DD date")


def next_id(con: sqlite3.Connection, table: str, column: str, prefix: str, width: int = 4) -> str:
    # Table and column names are selected only by trusted server code.
    pattern = f"{prefix}%"
    row = con.execute(f"SELECT {column} FROM {table} WHERE {column} LIKE ? ORDER BY id DESC LIMIT 1", (pattern,)).fetchone()
    number = 1
    if row:
        match = re.search(r"(\d+)$", str(row[0]))
        if match:
            number = int(match.group(1)) + 1
    return f"{prefix}{number:0{width}d}"



PAYROLL_SCHEMA = r"""
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS salary_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employee_id TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  basic_salary REAL NOT NULL DEFAULT 0,
  fixed_allowances REAL NOT NULL DEFAULT 0,
  notes TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_salary_employee_effective ON salary_records(employee_id,effective_from,effective_to);
CREATE TABLE IF NOT EXISTS payroll_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL UNIQUE,
  pay_month TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'Draft',
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  approved_at TEXT,
  approved_by TEXT
);
CREATE TABLE IF NOT EXISTS payroll_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  employee_id TEXT NOT NULL,
  basic_salary REAL NOT NULL DEFAULT 0,
  allowances REAL NOT NULL DEFAULT 0,
  overtime REAL NOT NULL DEFAULT 0,
  bonus REAL NOT NULL DEFAULT 0,
  deductions REAL NOT NULL DEFAULT 0,
  adjustments REAL NOT NULL DEFAULT 0,
  gross_salary REAL NOT NULL DEFAULT 0,
  net_salary REAL NOT NULL DEFAULT 0,
  scheduled_days REAL NOT NULL DEFAULT 0,
  present_days REAL NOT NULL DEFAULT 0,
  late_days REAL NOT NULL DEFAULT 0,
  absent_days REAL NOT NULL DEFAULT 0,
  paid_leave_days REAL NOT NULL DEFAULT 0,
  payable_days REAL NOT NULL DEFAULT 0,
  attendance_factor REAL NOT NULL DEFAULT 0,
  calculation_status TEXT NOT NULL DEFAULT 'Pending',
  notes TEXT DEFAULT '',
  UNIQUE(run_id, employee_id)
);
CREATE TABLE IF NOT EXISTS payroll_audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
"""

class HRMSHandler(BaseHTTPRequestHandler):
    server_version = "LightRetouchManagementSystem/4.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep console output compact; application activity is recorded in audit logs.
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_bytes(self, data: bytes, content_type: str, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store" if content_type.startswith("application/json") else "no-cache")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def json_response(self, payload: Any, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.send_bytes(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8", status, headers)

    def read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 13_000_000:
                raise ValueError("Request too large. Upload a file smaller than 8 MB.")
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
            return data
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON body")

    def get_session(self) -> dict[str, Any] | None:
        cookie = self.headers.get("Cookie", "")
        token = None
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == SESSION_COOKIE:
                token = value
                break
        if not token:
            return None
        with SESSION_LOCK:
            session = SESSIONS.get(token)
            if not session or session.get("expires", 0) < now_dt().timestamp():
                SESSIONS.pop(token, None)
                return None
            session["expires"] = now_dt().timestamp() + SESSION_TTL
            return {**session, "token": token}

    def require_user(self, roles: set[str] | None = None) -> dict[str, Any]:
        user = self.get_session()
        if not user:
            raise PermissionError("Please sign in to continue")
        # A forced password reset is a server-side gate, not only a front-end dialog.
        current_path = urllib.parse.urlparse(self.path).path
        if user.get("must_change_password") and current_path not in {"/api/me", "/api/change-password", "/api/logout"}:
            raise PermissionError("A password change is required before using the HRMS")
        if roles is not None and user["role"] not in roles:
            raise PermissionError("You do not have permission to access this section")
        return user

    def ensure_same_origin(self) -> None:
        # Browser write requests must include a custom header. SameSite cookies are an additional safeguard.
        if self.headers.get("X-HRMS-Request") != "1":
            raise PermissionError("Request verification failed. Refresh the page and try again.")
        origin = self.headers.get("Origin")
        if origin:
            host = self.headers.get("Host", "")
            parsed = urllib.parse.urlparse(origin)
            if parsed.netloc and parsed.netloc != host:
                raise PermissionError("Cross-origin request blocked")

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/":
            self.serve_static(TEMPLATE_DIR / "index.html")
            return
        if path == "/brand-logo":
            self.serve_brand_logo()
            return
        if path.startswith("/api/private-file/"):
            try:
                self.serve_private_file(path.rsplit("/", 1)[-1], download=urllib.parse.parse_qs(parsed.query).get("download", [""])[0] == "1")
            except PermissionError as exc:
                self.json_response({"error": str(exc)}, 403)
            except Exception:
                self.json_response({"error": "File not found"}, 404)
            return
        if path.startswith("/static/"):
            rel = Path(path[len("/static/"):])
            target = (STATIC_DIR / rel).resolve()
            if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
                self.json_response({"error": "Not found"}, 404)
                return
            self.serve_static(target)
            return
        if path.startswith("/api/backup-download/"):
            try:
                user = self.require_user({"super_admin"})
                filename = path.rsplit("/", 1)[-1]
                if not re.fullmatch(r"hrms_backup_[0-9_]+\.zip", filename):
                    self.json_response({"error": "Invalid backup name"}, 400); return
                target = (BACKUP_DIR / filename).resolve()
                if not str(target).startswith(str(BACKUP_DIR.resolve())) or not target.is_file():
                    self.json_response({"error": "Backup not found"}, 404); return
                data = target.read_bytes()
                self.send_bytes(data, "application/octet-stream", 200, {"Content-Disposition": f'attachment; filename="{filename}"'})
            except PermissionError as exc:
                self.json_response({"error": str(exc)}, 403)
            return
        if not path.startswith("/api/"):
            self.json_response({"error": "Not found"}, 404)
            return
        try:
            result = self.api_get(path, urllib.parse.parse_qs(parsed.query))
            self.json_response(result)
        except PermissionError as exc:
            self.json_response({"error": str(exc)}, 401 if "sign in" in str(exc) else 403)
        except ValueError as exc:
            self.json_response({"error": str(exc)}, 400)
        except Exception as exc:
            print("GET error:", repr(exc))
            self.json_response({"error": "An unexpected server error occurred"}, 500)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            self.ensure_same_origin()
            data = self.read_json()
            if path == "/api/login":
                result, headers = self.login(data)
                self.json_response(result, 200, headers)
                return
            if path == "/api/logout":
                user = self.require_user()
                token = user["token"]
                with SESSION_LOCK:
                    SESSIONS.pop(token, None)
                self.json_response({"ok": True}, 200, {"Set-Cookie": f"{SESSION_COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
                return
            result = self.api_post(path, data)
            self.json_response(result)
        except PermissionError as exc:
            msg = str(exc)
            self.json_response({"error": msg}, 401 if "sign in" in msg else 403)
        except ValueError as exc:
            self.json_response({"error": str(exc)}, 400)
        except sqlite3.IntegrityError as exc:
            self.json_response({"error": "This record conflicts with an existing record or required reference."}, 409)
        except Exception as exc:
            print("POST error:", repr(exc))
            self.json_response({"error": "An unexpected server error occurred"}, 500)

    def serve_static(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_bytes(path.read_bytes(), content_type + ("; charset=utf-8" if content_type.startswith("text/") or "javascript" in content_type else ""))

    def serve_brand_logo(self) -> None:
        con = connect_db()
        try:
            row = con.execute("SELECT setting_value FROM app_settings WHERE setting_key='brand_logo'").fetchone()
        finally:
            con.close()
        filename = (row[0] if row else "") or ""
        if not filename:
            self.json_response({"error": "No logo configured"}, 404); return
        target = (UPLOAD_DIR / "branding" / filename).resolve()
        if not str(target).startswith(str((UPLOAD_DIR / "branding").resolve())) or not target.is_file():
            self.json_response({"error": "Logo not found"}, 404); return
        mime = mimetypes.guess_type(str(target))[0] or "image/png"
        self.send_bytes(target.read_bytes(), mime, 200)

    def serve_private_file(self, file_id: str, download: bool = False) -> None:
        user = self.require_user()
        con = connect_db()
        try:
            row = con.execute("SELECT * FROM private_files WHERE file_id=?", (file_id,)).fetchone()
            if not row:
                raise FileNotFoundError(file_id)
            owner = row["owner_employee_id"] or ""
            category = row["category"]
            if category == "brand_logo":
                allowed = True
            elif category == "profile_photo":
                allowed = True  # Internal company directory headshots are visible to signed-in users.
            elif category == "employee_document":
                allowed = user["role"] in HR_ROLES or (bool(owner) and owner == (user.get("employee_id") or "")) or (user["role"] == "manager" and bool(owner) and self.manager_can_see(con, user, owner))
            elif category == "leave_document":
                allowed = user["role"] in HR_ROLES or (bool(owner) and owner == (user.get("employee_id") or "")) or (user["role"] == "manager" and bool(owner) and self.manager_can_see(con, user, owner))
            else:
                allowed = user["role"] in PAYROLL_ROLES
                if user["role"] == "employee": allowed = owner == (user.get("employee_id") or "")
            if not allowed: raise PermissionError("You do not have permission to view this file")
            target = (UPLOAD_DIR / row["stored_name"]).resolve()
            if not str(target).startswith(str(UPLOAD_DIR.resolve())) or not target.is_file():
                raise FileNotFoundError(file_id)
            disposition = "attachment" if download else "inline"
            safe_name = Path(row["original_name"]).name.replace('"', "")
            self.send_bytes(target.read_bytes(), row["content_type"], 200, {"Content-Disposition": f'{disposition}; filename="{safe_name}"'})
        finally:
            con.close()

    def store_uploaded_file(self, con: sqlite3.Connection, payload: Any, category: str, owner_employee_id: str = "", entity_id: str = "", actor: str = "") -> str:
        if not isinstance(payload, dict): raise ValueError("Please choose a file to upload")
        name = Path(str(payload.get("name", "upload"))).name[:180]
        content_type = str(payload.get("type", "application/octet-stream")).lower().split(";")[0]
        raw_data = str(payload.get("data", ""))
        if "," in raw_data and raw_data.startswith("data:"):
            raw_data = raw_data.split(",", 1)[1]
        allowed = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
        if content_type not in allowed: raise ValueError("Allowed formats: JPG, PNG, WEBP or PDF")
        try: content = base64.b64decode(raw_data, validate=True)
        except Exception: raise ValueError("Uploaded file data is invalid")
        limit = 8 * 1024 * 1024 if category == "leave_document" else 4 * 1024 * 1024
        if not content or len(content) > limit: raise ValueError(f"File size must be below {limit // (1024*1024)} MB")
        if category in {"profile_photo", "brand_logo"} and content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("Please upload a JPG, PNG or WEBP image")
        ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}[content_type]
        file_id = "FIL-" + uuid.uuid4().hex[:14].upper()
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        stored_name = file_id + ext
        (UPLOAD_DIR / stored_name).write_bytes(content)
        con.execute("INSERT INTO private_files(file_id,owner_employee_id,category,entity_id,original_name,stored_name,content_type,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (file_id, owner_employee_id, category, entity_id, name, stored_name, content_type, actor, now_iso()))
        audit(con, actor, "UPLOAD", "PrivateFile", file_id, {"category": category, "owner_employee_id": owner_employee_id, "size": len(content)})
        return file_id

    def login(self, data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        username = str(data.get("username", "")).strip().lower()
        password = str(data.get("password", ""))
        con = connect_db()
        client_key = f"{self.client_address[0]}:{username}"
        now_ts = now_dt().timestamp()
        attempts = [ts for ts in LOGIN_ATTEMPTS.get(client_key, []) if now_ts - ts < 900]
        if len(attempts) >= 5:
            con.close()
            raise PermissionError("Too many sign-in attempts. Try again in 15 minutes.")
        row = con.execute("SELECT * FROM users WHERE username=? AND is_active=1", (username,)).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            attempts.append(now_ts)
            LOGIN_ATTEMPTS[client_key] = attempts
            con.close()
            raise PermissionError("Invalid username or password")
        LOGIN_ATTEMPTS.pop(client_key, None)
        con.execute("UPDATE users SET last_login=? WHERE id=?", (now_iso(), row["id"]))
        audit(con, row["username"], "LOGIN", "User", str(row["id"]))
        con.commit()
        con.close()
        token = secrets.token_urlsafe(36)
        session = {"user_id": row["id"], "username": row["username"], "role": row["role"], "employee_id": row["employee_id"], "must_change_password": bool(row["must_change_password"]), "expires": now_dt().timestamp() + SESSION_TTL}
        with SESSION_LOCK:
            SESSIONS[token] = session
        headers = {"Set-Cookie": f"{SESSION_COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}"}
        return ({"ok": True, "user": self.public_user(session)}, headers)

    def public_user(self, user: dict[str, Any]) -> dict[str, Any]:
        return {"username": user["username"], "role": user["role"], "role_label": ROLES.get(user["role"], user["role"]), "employee_id": user.get("employee_id"), "must_change_password": bool(user.get("must_change_password"))}

    def api_get(self, path: str, query: dict[str, list[str]]) -> Any:
        if path == "/api/public-branding":
            con = connect_db()
            try:
                allowed = {"system_name", "company_name", "brand_logo"}
                return {r["setting_key"]: r["setting_value"] for r in con.execute("SELECT setting_key,setting_value FROM app_settings WHERE setting_key IN ('system_name','company_name','brand_logo')").fetchall()}
            finally:
                con.close()
        if path == "/api/me":
            user = self.require_user()
            con = connect_db()
            emp = rowdict(con.execute("SELECT e.*,d.name department,ds.name designation,s.name shift_name FROM employees e LEFT JOIN departments d ON d.id=e.department_id LEFT JOIN designations ds ON ds.id=e.designation_id LEFT JOIN shifts s ON s.id=e.shift_id WHERE e.employee_id=?", (user.get("employee_id"),)).fetchone()) if user.get("employee_id") else None
            settings = {r["setting_key"]: r["setting_value"] for r in con.execute("SELECT * FROM app_settings").fetchall()}
            con.close()
            if emp and emp.get("profile_photo"):
                emp["profile_photo_url"] = "/api/private-file/" + emp["profile_photo"]
            return {"user": self.public_user(user), "employee": emp, "settings": settings}
        user = self.require_user()
        con = connect_db()
        try:
            if path == "/api/dashboard":
                return self.dashboard(con, user)
            if path == "/api/my-payslips":
                if user["role"] != "employee" or not user.get("employee_id"):
                    raise PermissionError("Employee self-service access only")
                payroll_con = connect_payroll_db()
                try:
                    return rowsdict(payroll_con.execute("SELECT r.pay_month,r.status,p.basic_salary,p.allowances,p.overtime,p.bonus,p.deductions,p.adjustments,p.gross_salary,p.net_salary FROM payroll_items p JOIN payroll_runs r ON r.run_id=p.run_id WHERE p.employee_id=? AND r.status='Approved' ORDER BY r.pay_month DESC", (user["employee_id"],)).fetchall())
                finally:
                    payroll_con.close()
            if path == "/api/employees":
                self.require_user(HR_ROLES | PAYROLL_ROLES | {"manager"})
                if user["role"] == "manager":
                    rows = con.execute("SELECT e.employee_id,e.full_name,e.department_id,e.designation_id,e.employment_type,e.employment_status,e.joining_date,e.reporting_manager,d.name department,ds.name designation FROM employees e LEFT JOIN departments d ON d.id=e.department_id LEFT JOIN designations ds ON ds.id=e.designation_id WHERE e.reporting_manager=? ORDER BY e.full_name", (user.get("employee_id") or "",)).fetchall()
                elif user["role"] in PAYROLL_ROLES and user["role"] not in HR_ROLES:
                    rows = con.execute("SELECT e.employee_id,e.full_name,e.department_id,e.designation_id,e.employment_type,e.employment_status,e.joining_date,e.reporting_manager,d.name department,ds.name designation FROM employees e LEFT JOIN departments d ON d.id=e.department_id LEFT JOIN designations ds ON ds.id=e.designation_id ORDER BY e.full_name").fetchall()
                else:
                    rows = con.execute("SELECT e.*,d.name department,ds.name designation FROM employees e LEFT JOIN departments d ON d.id=e.department_id LEFT JOIN designations ds ON ds.id=e.designation_id ORDER BY e.created_at DESC").fetchall()
                output = rowsdict(rows)
                for item in output:
                    if item.get("profile_photo"): item["profile_photo_url"] = "/api/private-file/" + item["profile_photo"]
                return output
            if path.startswith("/api/employees/") and path.endswith("/documents"):
                empid = urllib.parse.unquote(path.split("/")[-2])
                if user["role"] not in HR_ROLES and user.get("employee_id") != empid and not (user["role"] == "manager" and self.manager_can_see(con, user, empid)): raise PermissionError("Employee documents are restricted to the employee, reporting manager and authorized HR")
                docs = con.execute("SELECT file_id,owner_employee_id,entity_id,original_name,content_type,created_by,created_at FROM private_files WHERE category='employee_document' AND owner_employee_id=? ORDER BY created_at DESC", (empid,)).fetchall()
                return [{**dict(r), "document_url": "/api/private-file/" + r["file_id"], "download_url": "/api/private-file/" + r["file_id"] + "?download=1", "document_label": r["entity_id"] or "Employee document"} for r in docs]
            if path == "/api/attendance/summary":
                month = query.get("month", [now_dt().strftime("%Y-%m")])[0]
                if not re.fullmatch(r"\d{4}-\d{2}", month): raise ValueError("Month must use YYYY-MM format")
                date.fromisoformat(month + "-01")
                employees = con.execute("SELECT e.*,d.name department,ds.name designation FROM employees e LEFT JOIN departments d ON d.id=e.department_id LEFT JOIN designations ds ON ds.id=e.designation_id WHERE e.employment_status IN ('Active','Probation','On Notice') ORDER BY e.full_name").fetchall()
                result = []
                for emp in employees:
                    summary = self.employee_attendance_summary(con, emp, month)
                    result.append({"employee_id":emp["employee_id"],"full_name":emp["full_name"],"department":emp["department"],"designation":emp["designation"],"employment_status":emp["employment_status"],"present_days":summary.get("present_days",0),"late_days":summary.get("late_days"),"late_minutes":summary.get("late_minutes"),"absent_days":summary.get("absent_days",0),"paid_leave_days":summary.get("paid_leave_days",0),"presence_hours":summary.get("presence_hours",0),"break_hours":summary.get("break_hours",0),"duty_hours":summary.get("duty_hours",0),"overtime_hours":summary.get("overtime_hours",0),"average_duty_hours":summary.get("average_duty_hours",0),"incomplete_punches":summary.get("incomplete_punches",0),"shift_configured":summary.get("configured",False)})
                return {"month":month,"employees":result,"totals":{"employees":len(result),"presence_hours":round(sum(x["presence_hours"] for x in result),2),"break_hours":round(sum(x["break_hours"] for x in result),2),"duty_hours":round(sum(x["duty_hours"] for x in result),2),"overtime_hours":round(sum(x["overtime_hours"] for x in result),2),"present_days":sum(x["present_days"] for x in result),"late_days":sum(x["late_days"] or 0 for x in result),"absent_days":sum(x["absent_days"] for x in result)}}
            if path.startswith("/api/employees/") and path.count("/") == 3:
                empid = urllib.parse.unquote(path.split("/")[-1])
                if user["role"] == "employee":
                    if user.get("employee_id") != empid: raise PermissionError("You can only view your own profile")
                elif user["role"] == "manager":
                    if not self.manager_can_see(con, user, empid): raise PermissionError("You can only view your own team")
                elif user["role"] not in HR_ROLES | PAYROLL_ROLES:
                    raise PermissionError("Not permitted to view employee profiles")
                if user["role"] in PAYROLL_ROLES and user["role"] not in HR_ROLES:
                    profile_sql = "SELECT e.employee_id,e.full_name,e.department_id,e.designation_id,e.employment_status,e.joining_date,e.shift_id,e.work_location,d.name department,ds.name designation,s.name shift_name,s.start_time shift_start,s.end_time shift_end,s.grace_minutes,s.weekly_off_days FROM employees e LEFT JOIN departments d ON d.id=e.department_id LEFT JOIN designations ds ON ds.id=e.designation_id LEFT JOIN shifts s ON s.id=e.shift_id WHERE e.employee_id=?"
                else:
                    profile_sql = "SELECT e.*,d.name department,ds.name designation,s.name shift_name,s.start_time shift_start,s.end_time shift_end,s.grace_minutes,s.weekly_off_days FROM employees e LEFT JOIN departments d ON d.id=e.department_id LEFT JOIN designations ds ON ds.id=e.designation_id LEFT JOIN shifts s ON s.id=e.shift_id WHERE e.employee_id=?"
                emp = con.execute(profile_sql, (empid,)).fetchone()
                if not emp: raise ValueError("Employee not found")
                month = query.get("month", [now_dt().strftime("%Y-%m")])[0]
                summary = self.employee_attendance_summary(con, emp, month)
                result = {**dict(emp), "attendance_summary": summary}
                if result.get("profile_photo"):
                    result["profile_photo_url"] = "/api/private-file/" + result["profile_photo"]
                if user["role"] == "employee" or user["role"] in HR_ROLES or user["role"] == "manager":
                    if user["role"] != "manager" or self.manager_can_see(con, user, empid):
                        result["production_tasks"] = rowsdict(con.execute("SELECT t.task_id,t.project_name,t.client_name,t.task_title,t.editing_type,t.priority,t.image_count,t.due_date,t.instructions,t.source_link,a.status assignment_status,a.completed_images,a.output_link,a.submission_notes,a.review_note,a.submitted_at FROM task_assignments a JOIN production_tasks t ON t.task_id=a.task_id WHERE a.employee_id=? AND t.is_active=1 ORDER BY t.created_at DESC", (empid,)).fetchall())
                if user["role"] in PAYROLL_ROLES:
                    payroll_con = connect_payroll_db()
                    try:
                        salary = payroll_con.execute("SELECT * FROM salary_records WHERE employee_id=? AND effective_from<=? AND (effective_to IS NULL OR effective_to>=?) ORDER BY effective_from DESC LIMIT 1", (empid, today_iso(), today_iso())).fetchone()
                        result["salary"] = dict(salary) if salary else None
                        result["salary_history"] = rowsdict(payroll_con.execute("SELECT * FROM salary_records WHERE employee_id=? ORDER BY effective_from DESC", (empid,)).fetchall())
                    finally: payroll_con.close()
                return result
            if path == "/api/tasks":
                if user["role"] == "employee":
                    rows = con.execute("SELECT t.*,a.status assignment_status,a.completed_images,a.output_link,a.submission_notes,a.submitted_at,a.review_note,a.started_at,a.updated_at assignment_updated,e.full_name created_by_name FROM task_assignments a JOIN production_tasks t ON t.task_id=a.task_id LEFT JOIN employees e ON e.company_email=t.created_by OR e.personal_email=t.created_by WHERE a.employee_id=? AND COALESCE(t.is_active,1)=1 ORDER BY CASE a.status WHEN 'Assigned' THEN 0 WHEN 'In Progress' THEN 1 WHEN 'Revision Required' THEN 2 WHEN 'Submitted' THEN 3 ELSE 4 END,t.due_date", (user.get("employee_id") or "",)).fetchall()
                elif user["role"] == "manager":
                    rows = con.execute("SELECT t.*,a.employee_id,a.status assignment_status,a.completed_images,a.output_link,a.submission_notes,a.submitted_at,a.review_note,a.started_at,a.updated_at assignment_updated,e.full_name assignee_name FROM production_tasks t JOIN task_assignments a ON a.task_id=t.task_id JOIN employees e ON e.employee_id=a.employee_id WHERE t.is_active=1 AND (t.created_by=? OR e.reporting_manager=? OR a.employee_id=?) ORDER BY t.created_at DESC", (user["username"],user.get("employee_id") or "",user.get("employee_id") or "")).fetchall()
                else:
                    self.require_user(HR_ROLES)
                    rows = con.execute("SELECT t.*,a.employee_id,a.status assignment_status,a.completed_images,a.output_link,a.submission_notes,a.submitted_at,a.review_note,a.started_at,a.updated_at assignment_updated,e.full_name assignee_name FROM production_tasks t JOIN task_assignments a ON a.task_id=t.task_id JOIN employees e ON e.employee_id=a.employee_id WHERE t.is_active=1 ORDER BY t.created_at DESC,t.task_id,e.full_name").fetchall()
                return rowsdict(rows)
            if path == "/api/departments":
                self.require_user(HR_ROLES)
                return rowsdict(con.execute("SELECT * FROM departments ORDER BY name").fetchall())
            if path == "/api/designations":
                self.require_user(HR_ROLES)
                return rowsdict(con.execute("SELECT ds.*,d.name department FROM designations ds LEFT JOIN departments d ON d.id=ds.department_id ORDER BY ds.name").fetchall())
            if path == "/api/shifts":
                self.require_user(HR_ROLES)
                return rowsdict(con.execute("SELECT * FROM shifts ORDER BY name").fetchall())
            if path == "/api/attendance":
                employee_id = query.get("employee_id", [None])[0]
                month = query.get("month", [now_dt().strftime("%Y-%m")])[0]
                if user["role"] == "employee":
                    employee_id = user.get("employee_id")
                elif user["role"] == "manager":
                    if employee_id and not self.manager_can_see(con, user, employee_id):
                        raise PermissionError("You can only view attendance for your team")
                elif user["role"] not in HR_ROLES:
                    raise PermissionError("You do not have permission to view attendance")
                params: list[Any] = [f"{month}%"]
                sql = "SELECT a.*,e.full_name FROM attendance_events a JOIN employees e ON e.employee_id=a.employee_id WHERE a.event_time LIKE ?"
                if user["role"] == "manager":
                    team_ids = [r[0] for r in con.execute("SELECT employee_id FROM employees WHERE reporting_manager=? OR employee_id=?", (user.get("employee_id") or "", user.get("employee_id") or "")).fetchall()]
                    placeholders = ",".join("?" for _ in team_ids) or "NULL"
                    sql += f" AND a.employee_id IN ({placeholders})"
                    params.extend(team_ids)
                elif employee_id:
                    sql += " AND a.employee_id=?"; params.append(employee_id)
                sql += " ORDER BY a.event_time DESC LIMIT 1000"
                return rowsdict(con.execute(sql, params).fetchall())
            if path == "/api/attendance/adjustments":
                if user["role"] == "employee":
                    return rowsdict(con.execute("SELECT * FROM attendance_adjustments WHERE employee_id=? ORDER BY created_at DESC", (user.get("employee_id"),)).fetchall())
                if user["role"] == "manager":
                    return rowsdict(con.execute("SELECT a.*,e.full_name FROM attendance_adjustments a JOIN employees e ON e.employee_id=a.employee_id WHERE e.reporting_manager=? OR a.employee_id=? ORDER BY a.created_at DESC LIMIT 500", (user.get("employee_id"), user.get("employee_id"))).fetchall())
                self.require_user(HR_ROLES)
                return rowsdict(con.execute("SELECT a.*,e.full_name FROM attendance_adjustments a JOIN employees e ON e.employee_id=a.employee_id ORDER BY a.created_at DESC LIMIT 500").fetchall())
            if path == "/api/leaves":
                if user["role"] == "employee":
                    return [{**dict(r), "document_url": ("/api/private-file/" + r["document_file_id"]) if r["document_file_id"] else ""} for r in con.execute("SELECT l.*,t.name leave_type,p.original_name document_name,p.content_type document_content_type FROM leave_requests l LEFT JOIN leave_types t ON t.id=l.leave_type_id LEFT JOIN private_files p ON p.file_id=l.document_file_id WHERE l.employee_id=? ORDER BY l.created_at DESC", (user.get("employee_id"),)).fetchall()]
                if user["role"] == "manager":
                    rows = con.execute("SELECT l.*,t.name leave_type,e.full_name,p.original_name document_name,p.content_type document_content_type FROM leave_requests l LEFT JOIN leave_types t ON t.id=l.leave_type_id JOIN employees e ON e.employee_id=l.employee_id LEFT JOIN private_files p ON p.file_id=l.document_file_id WHERE e.reporting_manager=? OR l.employee_id=? ORDER BY l.created_at DESC", (user.get("employee_id"), user.get("employee_id"))).fetchall()
                    return [{**dict(r), "document_url": ("/api/private-file/" + r["document_file_id"]) if r["document_file_id"] else ""} for r in rows]
                self.require_user(HR_ROLES)
                rows = con.execute("SELECT l.*,t.name leave_type,e.full_name,p.original_name document_name,p.content_type document_content_type FROM leave_requests l LEFT JOIN leave_types t ON t.id=l.leave_type_id JOIN employees e ON e.employee_id=l.employee_id LEFT JOIN private_files p ON p.file_id=l.document_file_id ORDER BY l.created_at DESC").fetchall()
                return [{**dict(r), "document_url": ("/api/private-file/" + r["document_file_id"]) if r["document_file_id"] else ""} for r in rows]
            if path == "/api/leave-types":
                return rowsdict(con.execute("SELECT * FROM leave_types WHERE is_active=1 ORDER BY name").fetchall())
            if path == "/api/holidays":
                return rowsdict(con.execute("SELECT * FROM holidays WHERE is_active=1 ORDER BY holiday_date").fetchall())
            if path == "/api/payroll/employees":
                self.require_user(PAYROLL_ROLES)
                return rowsdict(con.execute("SELECT employee_id,full_name,employment_status,department_id,designation_id FROM employees WHERE employment_status!='Inactive' ORDER BY full_name").fetchall())
            if path == "/api/payroll":
                self.require_user(PAYROLL_ROLES)
                payroll_con = connect_payroll_db()
                try:
                    runs = rowsdict(payroll_con.execute("SELECT * FROM payroll_runs ORDER BY pay_month DESC").fetchall())
                    salaries = rowsdict(payroll_con.execute("SELECT * FROM salary_records ORDER BY employee_id,effective_from DESC").fetchall())
                finally:
                    payroll_con.close()
                names = {r["employee_id"]: r["full_name"] for r in con.execute("SELECT employee_id,full_name FROM employees").fetchall()}
                for salary in salaries: salary["full_name"] = names.get(salary["employee_id"], "Unknown employee")
                return {"runs": runs, "salaries": salaries}
            if path.startswith("/api/payroll/run/"):
                self.require_user(PAYROLL_ROLES)
                run_id = path.rsplit("/", 1)[-1]
                payroll_con = connect_payroll_db()
                try:
                    run = rowdict(payroll_con.execute("SELECT * FROM payroll_runs WHERE run_id=?", (run_id,)).fetchone())
                    if not run: raise ValueError("Payroll run not found")
                    items = rowsdict(payroll_con.execute("SELECT * FROM payroll_items WHERE run_id=? ORDER BY employee_id", (run_id,)).fetchall())
                finally:
                    payroll_con.close()
                profiles = {r["employee_id"]: dict(r) for r in con.execute("SELECT employee_id,full_name,department_id,designation_id FROM employees").fetchall()}
                for item in items: item.update(profiles.get(item["employee_id"], {"full_name":"Unknown employee"}))
                items.sort(key=lambda x:x.get("full_name", ""))
                return {"run": run, "items": items}
            if path == "/api/recruitment":
                self.require_user(HR_ROLES)
                return rowsdict(con.execute("SELECT * FROM candidates WHERE COALESCE(is_archived,0)=0 ORDER BY created_at DESC").fetchall())
            if path == "/api/recruitment/positions":
                self.require_user(HR_ROLES)
                return rowsdict(con.execute("SELECT * FROM recruitment_positions WHERE is_active=1 ORDER BY name").fetchall())
            if path == "/api/assets":
                self.require_user(HR_ROLES)
                return rowsdict(con.execute("SELECT a.*,e.full_name assigned_name FROM assets a LEFT JOIN employees e ON e.employee_id=a.assigned_employee WHERE COALESCE(a.is_archived,0)=0 ORDER BY a.created_at DESC").fetchall())
            if path == "/api/performance":
                if user["role"] not in HR_ROLES | {"manager"}:
                    raise PermissionError("You do not have permission to view performance reviews")
                if user["role"] == "manager":
                    rows = con.execute("SELECT p.*,e.full_name FROM performance_reviews p JOIN employees e ON e.employee_id=p.employee_id WHERE COALESCE(p.is_archived,0)=0 AND e.reporting_manager=? ORDER BY p.created_at DESC", (user.get("employee_id"),)).fetchall()
                else:
                    rows = con.execute("SELECT p.*,e.full_name FROM performance_reviews p JOIN employees e ON e.employee_id=p.employee_id WHERE COALESCE(p.is_archived,0)=0 ORDER BY p.created_at DESC").fetchall()
                return rowsdict(rows)
            if path == "/api/disciplinary":
                self.require_user(HR_ROLES)
                return rowsdict(con.execute("SELECT d.*,e.full_name FROM disciplinary_records d JOIN employees e ON e.employee_id=d.employee_id WHERE COALESCE(d.is_archived,0)=0 ORDER BY d.created_at DESC").fetchall())
            if path == "/api/exits":
                self.require_user(HR_ROLES)
                return rowsdict(con.execute("SELECT x.*,e.full_name FROM exit_checklists x JOIN employees e ON e.employee_id=x.employee_id WHERE COALESCE(x.is_archived,0)=0 ORDER BY x.created_at DESC").fetchall())
            if path == "/api/settings":
                self.require_user(HR_ROLES)
                return {r["setting_key"]: r["setting_value"] for r in con.execute("SELECT * FROM app_settings").fetchall()}
            if path == "/api/audit":
                self.require_user({"super_admin", "hr_admin"})
                return rowsdict(con.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 500").fetchall())
            if path == "/api/backups":
                self.require_user({"super_admin"})
                BACKUP_DIR.mkdir(parents=True, exist_ok=True)
                return [{"filename": p.name, "size": p.stat().st_size, "modified": datetime.fromtimestamp(p.stat().st_mtime, TZ).isoformat()} for p in sorted(BACKUP_DIR.glob("hrms_backup_*.zip"), key=lambda p:p.stat().st_mtime, reverse=True)]
            if path == "/api/users":
                self.require_user({"super_admin"})
                return rowsdict(con.execute("SELECT id,username,role,employee_id,is_active,must_change_password,created_at,last_login FROM users ORDER BY created_at DESC").fetchall())
            raise ValueError("Unknown API endpoint")
        finally:
            con.close()

    def dashboard(self, con: sqlite3.Connection, user: dict[str, Any]) -> dict[str, Any]:
        role = user["role"]
        if role == "employee":
            emp = user.get("employee_id")
            if not emp:
                return {"role": role, "employee": None}
            today_events = rowsdict(con.execute("SELECT * FROM attendance_events WHERE employee_id=? AND event_time LIKE ? ORDER BY event_time", (emp, today_iso()+"%")).fetchall())
            employee_row = con.execute("SELECT * FROM employees WHERE employee_id=?", (emp,)).fetchone()
            month_attendance = self.employee_attendance_summary(con, employee_row, now_dt().strftime("%Y-%m")) if employee_row else {}
            leave = rowsdict(con.execute("SELECT l.*,t.name leave_type FROM leave_requests l LEFT JOIN leave_types t ON t.id=l.leave_type_id WHERE l.employee_id=? ORDER BY l.created_at DESC LIMIT 5", (emp,)).fetchall())
            my_tasks = rowsdict(con.execute("SELECT t.task_id,t.project_name,t.task_title,t.editing_type,t.image_count,t.due_date,a.status assignment_status,a.completed_images,a.output_link,a.review_note FROM task_assignments a JOIN production_tasks t ON t.task_id=a.task_id WHERE a.employee_id=? ORDER BY t.created_at DESC LIMIT 8", (emp,)).fetchall())
            return {"role": role, "employee_id": emp, "today_events": today_events, "month_attendance": month_attendance, "recent_leaves": leave, "my_tasks": my_tasks, "task_summary": {"assigned": sum(x["assignment_status"] == "Assigned" for x in my_tasks), "in_progress": sum(x["assignment_status"] == "In Progress" for x in my_tasks), "submitted": sum(x["assignment_status"] == "Submitted" for x in my_tasks), "revision": sum(x["assignment_status"] == "Revision Required" for x in my_tasks)}, "holidays": rowsdict(con.execute("SELECT * FROM holidays WHERE holiday_date>=? ORDER BY holiday_date LIMIT 5", (today_iso(),)).fetchall())}
        if role == "manager":
            team = con.execute("SELECT employee_id FROM employees WHERE reporting_manager=?", (user.get("employee_id") or "",)).fetchall()
            ids = [r[0] for r in team]
            placeholders = ",".join("?" for _ in ids) or "NULL"
            return {
                "role": role,
                "team_size": len(ids),
                "pending_leaves": con.execute(f"SELECT COUNT(*) FROM leave_requests WHERE status='Pending Manager Approval' AND employee_id IN ({placeholders})", ids).fetchone()[0],
                "team": rowsdict(con.execute(f"SELECT employee_id,full_name,employment_status FROM employees WHERE employee_id IN ({placeholders}) ORDER BY full_name", ids).fetchall()),
                "production": rowsdict(con.execute(f"SELECT t.task_id,t.project_name,t.task_title,t.editing_type,t.image_count,t.due_date,a.employee_id,e.full_name,a.status assignment_status,a.completed_images FROM task_assignments a JOIN production_tasks t ON t.task_id=a.task_id JOIN employees e ON e.employee_id=a.employee_id WHERE a.employee_id IN ({placeholders}) ORDER BY t.created_at DESC LIMIT 30", ids).fetchall()),
            }
        total = con.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        active = con.execute("SELECT COUNT(*) FROM employees WHERE employment_status='Active'").fetchone()[0]
        probation = con.execute("SELECT COUNT(*) FROM employees WHERE employment_status='Probation'").fetchone()[0]
        notice = con.execute("SELECT COUNT(*) FROM employees WHERE employment_status='On Notice'").fetchone()[0]
        today_events = con.execute("SELECT COUNT(DISTINCT employee_id) FROM attendance_events WHERE event_type='CHECK_IN' AND event_time LIKE ?", (today_iso()+"%",)).fetchone()[0]
        pending_leaves = con.execute("SELECT COUNT(*) FROM leave_requests WHERE status LIKE 'Pending%'").fetchone()[0]
        pending_adjustments = con.execute("SELECT COUNT(*) FROM attendance_adjustments WHERE status='Pending'").fetchone()[0]
        pipeline = con.execute("SELECT stage,COUNT(*) c FROM candidates GROUP BY stage").fetchall()
        departments = con.execute("SELECT COALESCE(d.name,'Unassigned') name,COUNT(e.id) count FROM employees e LEFT JOIN departments d ON d.id=e.department_id GROUP BY d.name ORDER BY count DESC").fetchall()
        new_joiners = con.execute("SELECT COUNT(*) FROM employees WHERE joining_date LIKE ?", (now_dt().strftime("%Y-%m")+"%",)).fetchone()[0]
        return {
            "role": role,
            "total_employees": total,
            "active_employees": active,
            "probation_employees": probation,
            "employees_on_notice": notice,
            "new_joiners_this_month": new_joiners,
            "checked_in_today": today_events,
            "pending_leaves": pending_leaves,
            "pending_attendance_corrections": pending_adjustments,
            "recruitment_pipeline": [dict(r) for r in pipeline],
            "department_headcount": [dict(r) for r in departments],
            "upcoming_probation": rowsdict(con.execute("SELECT employee_id,full_name,probation_end_date,department_id FROM employees WHERE probation_end_date BETWEEN ? AND ? AND employment_status='Probation' ORDER BY probation_end_date LIMIT 10", (today_iso(), (now_dt().date()+timedelta(days=30)).isoformat())).fetchall()),
            "production": rowsdict(con.execute("SELECT t.task_id,t.project_name,t.task_title,t.editing_type,t.image_count,t.due_date,a.employee_id,e.full_name,a.status assignment_status,a.completed_images FROM task_assignments a JOIN production_tasks t ON t.task_id=a.task_id JOIN employees e ON e.employee_id=a.employee_id ORDER BY t.created_at DESC LIMIT 40").fetchall()),
            "production_summary": {"total_assignments": con.execute("SELECT COUNT(*) FROM task_assignments").fetchone()[0], "in_progress": con.execute("SELECT COUNT(*) FROM task_assignments WHERE status='In Progress'").fetchone()[0], "submitted": con.execute("SELECT COUNT(*) FROM task_assignments WHERE status='Submitted'").fetchone()[0], "approved": con.execute("SELECT COUNT(*) FROM task_assignments WHERE status='Approved'").fetchone()[0], "revision": con.execute("SELECT COUNT(*) FROM task_assignments WHERE status='Revision Required'").fetchone()[0]},
        }

    def employee_attendance_summary(self, con: sqlite3.Connection, emp: sqlite3.Row, month: str) -> dict[str, Any]:
        """Monthly attendance, clocked duty hours and shift-relative overtime."""
        if not re.fullmatch(r"\d{4}-\d{2}", month): raise ValueError("Month must use YYYY-MM format")
        try: month_start = date.fromisoformat(month + "-01")
        except Exception: raise ValueError("Invalid month")
        month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        end_date = min(month_end, now_dt().date())
        start_date = max(month_start, date.fromisoformat(emp["joining_date"])) if emp["joining_date"] else month_start
        shift = con.execute("SELECT * FROM shifts WHERE id=?", (emp["shift_id"],)).fetchone() if emp["shift_id"] else None
        has_shift_start = bool(shift and shift["start_time"])
        has_shift_end = bool(shift and shift["end_time"])
        try: weekly_off = set(json.loads(shift["weekly_off_days"] or "[]")) if shift else set()
        except Exception: weekly_off = set()
        holidays = {r[0] for r in con.execute("SELECT holiday_date FROM holidays WHERE is_active=1 AND holiday_date BETWEEN ? AND ?", (start_date.isoformat(), end_date.isoformat())).fetchall()}
        events = con.execute("SELECT event_type,event_time FROM attendance_events WHERE employee_id=? AND event_time>=? AND event_time<? ORDER BY event_time", (emp["employee_id"], month_start.isoformat(), (month_end+timedelta(days=1)).isoformat())).fetchall()
        by_day: dict[str, dict[str, Any]] = {}
        for event in events:
            day = event["event_time"][:10]
            rec = by_day.setdefault(day, {"check_in": None, "check_out": None})
            if event["event_type"] == "CHECK_IN" and not rec["check_in"]: rec["check_in"] = event["event_time"]
            if event["event_type"] == "CHECK_OUT": rec["check_out"] = event["event_time"]
        adjustments = con.execute("SELECT work_date,requested_check_in,requested_check_out FROM attendance_adjustments WHERE employee_id=? AND status='Approved' AND work_date BETWEEN ? AND ?", (emp["employee_id"], month_start.isoformat(), month_end.isoformat())).fetchall()
        for adj in adjustments:
            rec = by_day.setdefault(adj["work_date"], {"check_in": None, "check_out": None})
            if adj["requested_check_in"]: rec["check_in"] = adj["work_date"] + "T" + adj["requested_check_in"] + ":00+06:00"
            if adj["requested_check_out"]: rec["check_out"] = adj["work_date"] + "T" + adj["requested_check_out"] + ":00+06:00"
        leave_rows = con.execute("SELECT l.start_date,l.end_date,l.status,t.paid_status FROM leave_requests l LEFT JOIN leave_types t ON t.id=l.leave_type_id WHERE l.employee_id=? AND l.status='Approved' AND l.end_date>=? AND l.start_date<=?", (emp["employee_id"], month_start.isoformat(), month_end.isoformat())).fetchall()
        leave_by_day: dict[str,str] = {}
        for leave in leave_rows:
            d0=max(date.fromisoformat(leave["start_date"]),month_start); d1=min(date.fromisoformat(leave["end_date"]),month_end); d=d0
            while d<=d1:
                leave_by_day[d.isoformat()] = str(leave["paid_status"] or "To be configured"); d += timedelta(days=1)
        grace_configured = bool(has_shift_start and shift["grace_minutes"] is not None)
        grace = int(shift["grace_minutes"] or 0) if shift else 0
        shift_start = time.fromisoformat(shift["start_time"]) if has_shift_start else None
        configured_break_minutes = max(0, int(shift["break_minutes"] or 0)) if shift else 0
        break_is_paid = bool(shift["break_is_paid"]) if shift and "break_is_paid" in shift.keys() else False
        break_minutes = 0 if break_is_paid else configured_break_minutes
        expected_minutes = None
        if has_shift_start and has_shift_end:
            st = time.fromisoformat(shift["start_time"]); et = time.fromisoformat(shift["end_time"])
            raw = int((datetime.combine(date(2000,1,1), et)-datetime.combine(date(2000,1,1), st)).total_seconds()//60)
            if raw <= 0: raw += 24*60
            expected_minutes = max(0, raw-break_minutes)
        days=[]; scheduled=present=late=late_minutes=absent=paid_leave=unpaid_leave=0
        presence_minutes_total=duty_minutes_total=break_minutes_total=overtime_minutes_total=incomplete_punches=0
        completed_duty_days=0; in_progress_minutes_total=0; in_progress_days=0
        d=start_date
        while d<=end_date:
            day=d.isoformat(); rec=by_day.get(day,{"check_in":None,"check_out":None}); cin=rec["check_in"]; cout=rec["check_out"]
            status="Shift Not Configured" if not has_shift_start else "Not Scheduled"
            mins=0; duty_minutes=0; overtime_minutes=0
            if day in holidays: status="Holiday"
            elif d.strftime("%A") in weekly_off and shift: status="Weekly Off"
            elif has_shift_start:
                scheduled += 1
                leave_status=leave_by_day.get(day)
                if cin:
                    present += 1; status="Present"
                    if grace_configured:
                        try:
                            check_time=datetime.fromisoformat(cin).time().replace(tzinfo=None)
                            mins=max(0,int((datetime.combine(d,check_time)-datetime.combine(d,shift_start)).total_seconds()//60)-grace)
                        except Exception: mins=0
                        if mins>0: late += 1; late_minutes += mins; status="Late"
                elif leave_status == "Paid": paid_leave += 1; status="Paid Leave"
                elif leave_status == "Unpaid": unpaid_leave += 1; status="Unpaid Leave"
                elif leave_status: unpaid_leave += 1; status="Leave (Policy Check)"
                elif d < now_dt().date(): absent += 1; status="Absent"
                else: status="Not Checked In"
            elif cin:
                status="Recorded"
            if cin and cout:
                try:
                    ci=datetime.fromisoformat(cin); co=datetime.fromisoformat(cout)
                    if co < ci: co += timedelta(days=1)
                    elapsed=int(max(0,(co-ci).total_seconds())//60)
                    deducted_break=min(break_minutes, elapsed)
                    duty_minutes=max(0,elapsed-deducted_break)
                    presence_minutes_total += elapsed
                    break_minutes_total += deducted_break
                    if expected_minutes is not None: overtime_minutes=max(0,duty_minutes-expected_minutes)
                    duty_minutes_total += duty_minutes; overtime_minutes_total += overtime_minutes
                    completed_duty_days += 1
                except Exception:
                    duty_minutes=0; overtime_minutes=0
            elif cin and not cout:
                incomplete_punches += 1
                if d == now_dt().date():
                    status = "In Progress"
                    try:
                        live_ci=datetime.fromisoformat(cin)
                        live_now=now_dt()
                        in_progress_minutes_total += max(0, int((live_now-live_ci).total_seconds()//60))
                        in_progress_days += 1
                    except Exception:
                        pass
                else:
                    status = "Missing Check-out"
            presence_minutes = 0
            if cin and cout:
                try:
                    _ci=datetime.fromisoformat(cin); _co=datetime.fromisoformat(cout)
                    if _co < _ci: _co += timedelta(days=1)
                    presence_minutes=int(max(0,(_co-_ci).total_seconds())//60)
                except Exception:
                    presence_minutes=0
            days.append({"date":day,"check_in":cin,"check_out":cout,"status":status,"late_minutes":mins,"presence_minutes":presence_minutes,"presence_hours":round(presence_minutes/60,2),"break_minutes":min(break_minutes,presence_minutes) if cin and cout else 0,"break_hours":round((min(break_minutes,presence_minutes) if cin and cout else 0)/60,2),"duty_minutes":duty_minutes,"duty_hours":round(duty_minutes/60,2),"overtime_minutes":overtime_minutes,"overtime_hours":round(overtime_minutes/60,2)})
            d += timedelta(days=1)
        configured = has_shift_start
        return {"month":month,"configured":configured,"late_configured":grace_configured,"overtime_configured":expected_minutes is not None,"message":"Presence hours are check-in to check-out. Net duty hours subtract the configured break. Overtime is net duty above the configured net shift duration; it is informational, not automatic overtime pay." if expected_minutes is not None else "Assign a shift with both start and end times to calculate overtime. Presence and net duty are shown from complete punches.","scheduled_days":scheduled,"present_days":present,"late_days":late if grace_configured else None,"late_minutes":late_minutes if grace_configured else None,"absent_days":absent,"paid_leave_days":paid_leave,"unpaid_leave_days":unpaid_leave,"payable_days":present+paid_leave,"presence_minutes":presence_minutes_total,"presence_hours":round(presence_minutes_total/60,2),"break_minutes":break_minutes_total,"break_hours":round(break_minutes_total/60,2),"duty_minutes":duty_minutes_total,"duty_hours":round(duty_minutes_total/60,2),"average_duty_hours":round(duty_minutes_total/completed_duty_days/60,2) if completed_duty_days else 0,"completed_duty_days":completed_duty_days,"in_progress_days":in_progress_days,"in_progress_minutes":in_progress_minutes_total,"in_progress_hours":round(in_progress_minutes_total/60,2),"overtime_minutes":overtime_minutes_total,"overtime_hours":round(overtime_minutes_total/60,2),"incomplete_punches":incomplete_punches,"expected_shift_minutes":expected_minutes,"break_is_paid":break_is_paid,"configured_break_minutes":configured_break_minutes,"days":days}

    def manager_can_see(self, con: sqlite3.Connection, user: dict[str, Any], employee_id: str) -> bool:
        return bool(con.execute("SELECT 1 FROM employees WHERE employee_id=? AND (reporting_manager=? OR employee_id=?)", (employee_id, user.get("employee_id") or "", user.get("employee_id") or "")).fetchone())

    def api_post(self, path: str, data: dict[str, Any]) -> Any:
        user = self.require_user()
        actor = user["username"]
        con = connect_db()
        try:
            if path == "/api/change-password":
                old = str(data.get("current_password", ""))
                new = str(data.get("new_password", ""))
                if len(new) < 12:
                    raise ValueError("New password must be at least 12 characters")
                rec = con.execute("SELECT password_hash FROM users WHERE id=?", (user["user_id"],)).fetchone()
                if not rec or not verify_password(old, rec["password_hash"]):
                    raise ValueError("Current password is incorrect")
                con.execute("UPDATE users SET password_hash=?,must_change_password=0 WHERE id=?", (hash_password(new), user["user_id"]))
                audit(con, actor, "CHANGE_PASSWORD", "User", str(user["user_id"]))
                con.commit()
                with SESSION_LOCK:
                    if user["token"] in SESSIONS: SESSIONS[user["token"]]["must_change_password"] = False
                return {"ok": True}
            if path == "/api/me/update":
                empid = user.get("employee_id")
                if not empid: raise ValueError("This account is not linked to an employee profile")
                existing = con.execute("SELECT * FROM employees WHERE employee_id=?", (empid,)).fetchone()
                if not existing: raise ValueError("Employee profile not found")
                allowed = ["full_name", "personal_email", "phone", "emergency_contact", "work_location"]
                values = {k: str(data[k]).strip() for k in allowed if k in data}
                if "full_name" in values and not values["full_name"]: raise ValueError("Full name cannot be blank")
                photo = data.get("profile_photo")
                if photo:
                    file_id = self.store_uploaded_file(con, photo, "profile_photo", empid, empid, actor)
                    values["profile_photo"] = file_id
                if not values: raise ValueError("No profile changes supplied")
                values["updated_at"] = now_iso()
                assigns = ",".join(f"{k}=?" for k in values)
                con.execute(f"UPDATE employees SET {assigns} WHERE employee_id=?", (*values.values(), empid))
                audit(con, actor, "SELF_UPDATE", "EmployeeProfile", empid, {k:v for k,v in values.items() if k not in {"profile_photo"}})
                con.commit(); return {"ok": True, "profile_photo_url": ("/api/private-file/" + values["profile_photo"]) if values.get("profile_photo") else None}
            if path.startswith("/api/employees/") and path.endswith("/documents"):
                empid = urllib.parse.unquote(path.split("/")[-2])
                if user["role"] == "employee":
                    if user.get("employee_id") != empid: raise PermissionError("You can only upload documents to your own profile")
                elif user["role"] == "manager":
                    if not self.manager_can_see(con, user, empid): raise PermissionError("You can only manage documents for your team")
                elif user["role"] not in HR_ROLES: raise PermissionError("Not permitted to upload employee documents")
                if not con.execute("SELECT 1 FROM employees WHERE employee_id=?", (empid,)).fetchone(): raise ValueError("Employee not found")
                label = str(data.get("document_label", "Employee document")).strip()[:100] or "Employee document"
                file_id = self.store_uploaded_file(con, data.get("document"), "employee_document", empid, label, actor)
                con.commit(); return {"ok":True,"file_id":file_id,"document_url":"/api/private-file/"+file_id}
            if path.startswith("/api/employee-documents/") and path.endswith("/delete"):
                file_id = path.split("/")[-2]
                row = con.execute("SELECT * FROM private_files WHERE file_id=? AND category='employee_document'", (file_id,)).fetchone()
                if not row: raise ValueError("Employee document not found")
                owner = row["owner_employee_id"] or ""
                if user["role"] not in HR_ROLES and owner != (user.get("employee_id") or "") and not (user["role"] == "manager" and owner and self.manager_can_see(con, user, owner)): raise PermissionError("Employee documents are restricted to the employee, reporting manager and authorized HR")
                target = (UPLOAD_DIR / row["stored_name"]).resolve()
                if str(target).startswith(str(UPLOAD_DIR.resolve())) and target.exists(): target.unlink()
                con.execute("DELETE FROM private_files WHERE file_id=?", (file_id,))
                audit(con, actor, "DELETE", "EmployeeDocument", file_id, {"employee_id":owner})
                con.commit(); return {"ok":True}
            if path == "/api/settings/logo":
                self.require_user(ADMIN_ROLES)
                payload = data.get("logo")
                if not payload: raise ValueError("Choose a logo image")
                # Brand logo is public branding only, not employee data.
                if not isinstance(payload, dict): raise ValueError("Invalid logo upload")
                name = Path(str(payload.get("name", "logo"))).name[:100]
                ctype = str(payload.get("type", "image/png")).lower()
                if ctype not in {"image/png", "image/jpeg", "image/webp"}: raise ValueError("Logo must be PNG, JPG or WEBP")
                raw = str(payload.get("data", "")); raw = raw.split(",",1)[1] if raw.startswith("data:") and "," in raw else raw
                try: content = base64.b64decode(raw, validate=True)
                except Exception: raise ValueError("Logo data is invalid")
                if not content or len(content) > 2*1024*1024: raise ValueError("Logo must be under 2 MB")
                ext = {"image/png":".png","image/jpeg":".jpg","image/webp":".webp"}[ctype]
                folder = UPLOAD_DIR / "branding"; folder.mkdir(parents=True, exist_ok=True)
                filename = "company_logo" + ext
                (folder / filename).write_bytes(content)
                con.execute("INSERT INTO app_settings(setting_key,setting_value,updated_at,updated_by) VALUES('brand_logo',?,?,?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=excluded.updated_at,updated_by=excluded.updated_by", (filename, now_iso(), actor))
                audit(con, actor, "UPDATE_LOGO", "Branding", filename, {"original_name": name})
                con.commit(); return {"ok": True, "logo_url": "/brand-logo?v=" + str(int(now_dt().timestamp()))}
            if path == "/api/employees":
                self.require_user(HR_ROLES)
                full_name = str(data.get("full_name", "")).strip()
                if not full_name: raise ValueError("Employee name is required")
                empid = str(data.get("employee_id") or next_id(con, "employees", "employee_id", "LR-EMP-")).strip()
                if not re.fullmatch(r"LR-EMP-\d{4,}", empid): raise ValueError("Employee ID must follow LR-EMP-0001 format")
                employment_type = str(data.get("employment_type", "Full-time"))
                employment_status = str(data.get("employment_status", "Active"))
                if employment_type not in {"Full-time","Part-time","Contract","Intern"}: raise ValueError("Invalid employment type")
                if employment_status not in {"Active","Probation","On Notice","Inactive"}: raise ValueError("Invalid employment status")
                for date_key in ("joining_date","probation_start_date","probation_end_date","confirmation_date"):
                    if data.get(date_key): valid_date(str(data[date_key]), date_key.replace("_", " "))
                reporting_manager = str(data.get("reporting_manager", "")).strip()
                if reporting_manager and not con.execute("SELECT 1 FROM employees WHERE employee_id=? AND employment_status!='Inactive'", (reporting_manager,)).fetchone(): raise ValueError("Select a valid active Reporting Manager Employee ID")
                fields = {
                    "personal_email": str(data.get("personal_email", "")).strip(),
                    "company_email": str(data.get("company_email", "")).strip(),
                    "phone": str(data.get("phone", "")).strip(),
                    "emergency_contact": str(data.get("emergency_contact", "")).strip(),
                    "department_id": data.get("department_id") or None,
                    "designation_id": data.get("designation_id") or None,
                    "reporting_manager": reporting_manager,
                    "employment_type": employment_type,
                    "employment_status": employment_status,
                    "joining_date": data.get("joining_date") or "",
                    "probation_start_date": data.get("probation_start_date") or "",
                    "probation_end_date": data.get("probation_end_date") or "",
                    "confirmation_date": data.get("confirmation_date") or "",
                    "work_location": str(data.get("work_location") or "Mirpur 13, Dhaka"),
                    "shift_id": data.get("shift_id") or None,
                    "remarks": str(data.get("remarks", "")),
                }
                con.execute("INSERT INTO employees(employee_id,full_name,personal_email,company_email,phone,emergency_contact,department_id,designation_id,reporting_manager,employment_type,employment_status,joining_date,probation_start_date,probation_end_date,confirmation_date,work_location,shift_id,remarks,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (empid, full_name, fields["personal_email"], fields["company_email"], fields["phone"], fields["emergency_contact"], fields["department_id"], fields["designation_id"], fields["reporting_manager"], fields["employment_type"], fields["employment_status"], fields["joining_date"], fields["probation_start_date"], fields["probation_end_date"], fields["confirmation_date"], fields["work_location"], fields["shift_id"], fields["remarks"], now_iso(), now_iso()))
                created_account = None
                if data.get("create_account"):
                    username = (fields["company_email"] or fields["personal_email"]).strip().lower()
                    if not username: raise ValueError("Add a company or personal email before creating a login")
                    temp_password = secrets.token_urlsafe(12) + "A9!"
                    con.execute("INSERT INTO users(username,password_hash,role,employee_id,created_at,must_change_password) VALUES(?,?,?,?,?,1)", (username, hash_password(temp_password), "employee", empid, now_iso()))
                    created_account = {"username": username, "temporary_password": temp_password}
                audit(con, actor, "CREATE", "Employee", empid, {"full_name": full_name, "account_created": bool(created_account)})
                con.commit()
                return {"ok": True, "employee_id": empid, "account": created_account}
            if path.startswith("/api/employees/") and path.endswith("/update"):
                self.require_user(HR_ROLES)
                empid = path.split("/")[-2]
                existing = con.execute("SELECT * FROM employees WHERE employee_id=?", (empid,)).fetchone()
                if not existing: raise ValueError("Employee record not found")
                allowed = ["full_name","personal_email","company_email","phone","emergency_contact","department_id","designation_id","reporting_manager","employment_type","employment_status","joining_date","probation_start_date","probation_end_date","confirmation_date","work_location","shift_id","remarks"]
                values = {}
                for key in allowed:
                    if key in data:
                        val = data[key]
                        if key in ("department_id","designation_id","shift_id"):
                            val = val or None
                        values[key] = val
                if "full_name" in values and not str(values["full_name"]).strip(): raise ValueError("Employee name cannot be blank")
                if "employment_type" in values and values["employment_type"] not in {"Full-time","Part-time","Contract","Intern"}: raise ValueError("Invalid employment type")
                if "employment_status" in values and values["employment_status"] not in {"Active","Probation","On Notice","Inactive"}: raise ValueError("Invalid employment status")
                if "reporting_manager" in values:
                    manager_id = str(values["reporting_manager"] or "").strip()
                    if manager_id and (manager_id == empid or not con.execute("SELECT 1 FROM employees WHERE employee_id=? AND employment_status!='Inactive'", (manager_id,)).fetchone()): raise ValueError("Select a different active Reporting Manager Employee ID")
                    values["reporting_manager"] = manager_id
                for date_key in ("joining_date","probation_start_date","probation_end_date","confirmation_date"):
                    if values.get(date_key): valid_date(str(values[date_key]), date_key.replace("_", " "))
                if not values: raise ValueError("No employee fields supplied")
                values["updated_at"] = now_iso()
                assignments = ",".join(f"{key}=?" for key in values)
                con.execute(f"UPDATE employees SET {assignments} WHERE employee_id=?", (*values.values(), empid))
                if "employment_status" in values:
                    new_active = 0 if values["employment_status"]=="Inactive" else 1
                    linked_user_ids = [r[0] for r in con.execute("SELECT id FROM users WHERE employee_id=?", (empid,)).fetchall()]
                    con.execute("UPDATE users SET is_active=? WHERE employee_id=?", (new_active, empid))
                    if not new_active: invalidate_user_sessions(linked_user_ids)
                audit(con, actor, "UPDATE", "Employee", empid, {k:v for k,v in values.items() if k not in ("emergency_contact",)})
                con.commit(); return {"ok": True}
            if path.startswith("/api/employees/") and path.endswith("/delete"):
                self.require_user(HR_ROLES)
                empid = urllib.parse.unquote(path.split("/")[-2])
                emp = con.execute("SELECT full_name FROM employees WHERE employee_id=?", (empid,)).fetchone()
                if not emp: raise ValueError("Employee record not found")
                # Archive instead of destroying historical attendance/payroll references.
                con.execute("UPDATE employees SET employment_status='Inactive',updated_at=? WHERE employee_id=?", (now_iso(),empid))
                linked_user_ids = [r[0] for r in con.execute("SELECT id FROM users WHERE employee_id=?", (empid,)).fetchall()]
                con.execute("UPDATE users SET is_active=0 WHERE employee_id=?", (empid,))
                invalidate_user_sessions(linked_user_ids)
                audit(con, actor, "ARCHIVE", "Employee", empid, {"full_name":emp["full_name"],"reason":"Archived from employee directory; history preserved"})
                con.commit(); return {"ok":True,"archived":True}
            if path == "/api/departments":
                self.require_user(HR_ROLES)
                name = str(data.get("name", "")).strip()
                if not name: raise ValueError("Department name is required")
                cur = con.execute("INSERT INTO departments(name,description,created_at) VALUES(?,?,?)", (name, str(data.get("description", "")), now_iso()))
                audit(con, actor, "CREATE", "Department", str(cur.lastrowid), {"name": name})
                con.commit(); return {"ok": True, "id": cur.lastrowid}
            if path == "/api/designations":
                self.require_user(HR_ROLES)
                name = str(data.get("name", "")).strip()
                if not name: raise ValueError("Designation name is required")
                cur = con.execute("INSERT INTO designations(name,department_id,description,created_at) VALUES(?,?,?,?)", (name, data.get("department_id") or None, str(data.get("description", "")), now_iso()))
                audit(con, actor, "CREATE", "Designation", str(cur.lastrowid), {"name": name})
                con.commit(); return {"ok": True, "id": cur.lastrowid}
            if path == "/api/shifts":
                self.require_user(HR_ROLES)
                name = str(data.get("name", "")).strip()
                if not name: raise ValueError("Shift name is required")
                start = normalize_time_input(data.get("start_time"), "Shift start time")
                end = normalize_time_input(data.get("end_time"), "Shift end time")
                days = data.get("weekly_off_days", [])
                break_is_paid = 1 if str(data.get("break_is_paid", "0")).lower() in {"1", "true", "yes"} else 0
                cur = con.execute("INSERT INTO shifts(name,start_time,end_time,break_minutes,break_is_paid,grace_minutes,weekly_off_days,created_at) VALUES(?,?,?,?,?,?,?,?)", (name, start or None, end or None, int(data["break_minutes"]) if str(data.get("break_minutes", "")).strip() else None, break_is_paid, int(data["grace_minutes"]) if str(data.get("grace_minutes", "")).strip() else None, json.dumps(days), now_iso()))
                audit(con, actor, "CREATE", "Shift", str(cur.lastrowid), data)
                con.commit(); return {"ok": True, "id": cur.lastrowid}
            m = re.fullmatch(r"/api/(departments|designations|shifts)/(\d+)/(update|delete)", path)
            if m:
                self.require_user(HR_ROLES)
                entity, rid, action = m.group(1), int(m.group(2)), m.group(3)
                table = {"departments":"departments","designations":"designations","shifts":"shifts"}[entity]
                current = con.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone()
                if not current: raise ValueError(f"{entity[:-1].capitalize()} not found")
                if action == "delete":
                    con.execute(f"UPDATE {table} SET is_active=0 WHERE id=?", (rid,))
                    audit(con, actor, "ARCHIVE", entity[:-1].capitalize(), str(rid))
                    con.commit(); return {"ok":True,"archived":True}
                if entity == "departments":
                    name=str(data.get("name", current["name"])).strip(); description=str(data.get("description", current["description"] or ""))
                    if not name: raise ValueError("Department name is required")
                    con.execute("UPDATE departments SET name=?,description=? WHERE id=?", (name,description,rid))
                elif entity == "designations":
                    name=str(data.get("name", current["name"])).strip(); description=str(data.get("description", current["description"] or "")); dep=data.get("department_id",current["department_id"]) or None
                    if not name: raise ValueError("Designation name is required")
                    con.execute("UPDATE designations SET name=?,department_id=?,description=? WHERE id=?", (name,dep,description,rid))
                else:
                    name=str(data.get("name",current["name"])).strip()
                    start=normalize_time_input(data.get("start_time", current["start_time"] or ""), "Shift start time")
                    end=normalize_time_input(data.get("end_time", current["end_time"] or ""), "Shift end time")
                    if not name: raise ValueError("Shift name is required")
                    break_minutes=int(data.get("break_minutes",current["break_minutes"] or 0)) if str(data.get("break_minutes",current["break_minutes"] or "")).strip() else None
                    grace_minutes=int(data.get("grace_minutes",current["grace_minutes"] or 0)) if str(data.get("grace_minutes",current["grace_minutes"] or "")).strip() else None
                    break_is_paid = 1 if str(data.get("break_is_paid", current["break_is_paid"] if "break_is_paid" in current.keys() else 0)).lower() in {"1", "true", "yes"} else 0
                    weekly=data.get("weekly_off_days",json.loads(current["weekly_off_days"] or "[]"))
                    con.execute("UPDATE shifts SET name=?,start_time=?,end_time=?,break_minutes=?,break_is_paid=?,grace_minutes=?,weekly_off_days=? WHERE id=?", (name,start or None,end or None,break_minutes,break_is_paid,grace_minutes,json.dumps(weekly),rid))
                audit(con,actor,"UPDATE",entity[:-1].capitalize(),str(rid),data); con.commit(); return {"ok":True}
            if path.startswith("/api/leave-types/") and path.endswith("/update"):
                self.require_user(HR_ROLES); rid=int(path.split("/")[-2])
                name=str(data.get("name","")).strip()
                if not name: raise ValueError("Leave type name is required")
                entitlement=data.get("entitlement_days")
                if entitlement not in (None, "") and safe_float(entitlement,-1)<0: raise ValueError("Entitlement must be zero or positive")
                paid=str(data.get("paid_status","To be configured"))
                if paid not in {"Paid","Unpaid","To be configured"}: raise ValueError("Invalid leave paid status")
                cur=con.execute("UPDATE leave_types SET name=?,entitlement_days=?,paid_status=? WHERE id=?",(name,safe_float(entitlement) if entitlement not in (None,"") else None,paid,rid))
                if cur.rowcount==0: raise ValueError("Leave type not found")
                audit(con,actor,"UPDATE","LeaveType",str(rid),data); con.commit(); return {"ok":True}
            if path.startswith("/api/leave-types/") and path.endswith("/delete"):
                self.require_user(HR_ROLES); rid=int(path.split("/")[-2])
                cur=con.execute("UPDATE leave_types SET is_active=0 WHERE id=?",(rid,))
                if cur.rowcount == 0: raise ValueError("Leave type not found")
                audit(con,actor,"ARCHIVE","LeaveType",str(rid)); con.commit(); return {"ok":True}
            if path == "/api/holidays":
                self.require_user(HR_ROLES)
                holiday_date=valid_date(str(data.get("holiday_date","")),"Holiday date")
                name=str(data.get("name","")).strip()
                if not name: raise ValueError("Holiday name is required")
                cur=con.execute("INSERT INTO holidays(holiday_date,name,is_active) VALUES(?,?,1)",(holiday_date,name))
                audit(con,actor,"CREATE","Holiday",str(cur.lastrowid),data); con.commit(); return {"ok":True,"id":cur.lastrowid}
            holiday_match=re.fullmatch(r"/api/holidays/(\d+)/(update|delete)",path)
            if holiday_match:
                self.require_user(HR_ROLES); hid=int(holiday_match.group(1)); action=holiday_match.group(2)
                current=con.execute("SELECT * FROM holidays WHERE id=?",(hid,)).fetchone()
                if not current: raise ValueError("Holiday not found")
                if action=="delete":
                    con.execute("UPDATE holidays SET is_active=0 WHERE id=?",(hid,)); audit(con,actor,"ARCHIVE","Holiday",str(hid)); con.commit(); return {"ok":True,"archived":True}
                holiday_date=valid_date(str(data.get("holiday_date",current["holiday_date"])),"Holiday date")
                name=str(data.get("name",current["name"])).strip()
                if not name: raise ValueError("Holiday name is required")
                con.execute("UPDATE holidays SET holiday_date=?,name=? WHERE id=?",(holiday_date,name,hid)); audit(con,actor,"UPDATE","Holiday",str(hid),data); con.commit(); return {"ok":True}
            if path == "/api/attendance/punch":
                empid = user.get("employee_id") if user["role"] == "employee" else str(data.get("employee_id", "")).strip()
                if user["role"] != "employee" and user["role"] not in HR_ROLES: raise PermissionError("Only employees and authorized HR users may record attendance")
                if not empid: raise ValueError("Employee ID is required")
                emp = con.execute("SELECT employment_status FROM employees WHERE employee_id=?", (empid,)).fetchone()
                if not emp or emp["employment_status"] not in ("Active", "Probation"): raise ValueError("Employee is not active for attendance")
                ev = str(data.get("event_type", "")).upper()
                if ev not in ("CHECK_IN", "CHECK_OUT"): raise ValueError("Choose check-in or check-out")
                day = today_iso()
                # Acquire the SQLite write lock before reading today's punch state. This makes
                # check-in/check-out idempotent even when two tabs/devices submit at once.
                con.execute("BEGIN IMMEDIATE")
                today_events = con.execute("SELECT event_type FROM attendance_events WHERE employee_id=? AND event_time LIKE ? ORDER BY event_time", (empid, day+"%")).fetchall()
                types = [r[0] for r in today_events]
                if ev == "CHECK_IN" and "CHECK_IN" in types and (types[-1] == "CHECK_IN" or types.count("CHECK_IN") >= 1):
                    raise ValueError("A check-in has already been recorded for today")
                if ev == "CHECK_OUT" and (not types or types[-1] != "CHECK_IN"):
                    raise ValueError("Record a check-in before checking out")
                event_id = "ATT-" + uuid.uuid4().hex[:12].upper()
                # Timestamp is generated exclusively on the server.
                con.execute("INSERT INTO attendance_events(event_id,employee_id,event_type,event_time,source,note,created_at) VALUES(?,?,?,?,?,?,?)", (event_id, empid, ev, now_iso(), "employee_portal" if user["role"] == "employee" else "hr_admin", str(data.get("note", "")), now_iso()))
                audit(con, actor, ev, "Attendance", event_id, {"employee_id": empid})
                con.commit(); return {"ok": True, "event_id": event_id, "event_time": now_iso()}
            if path == "/api/attendance/adjustments":
                empid = user.get("employee_id") if user["role"] == "employee" else str(data.get("employee_id", "")).strip()
                if user["role"] not in HR_ROLES | {"employee", "manager"}: raise PermissionError("Not permitted")
                if not empid: raise ValueError("Employee ID is required")
                if user["role"] == "manager" and not self.manager_can_see(con, user, empid): raise PermissionError("You can only create correction requests for your team")
                work_date = valid_date(str(data.get("work_date", "")), "Work date")
                requested_check_in = normalize_time_input(data.get("requested_check_in"), "Requested check-in")
                requested_check_out = normalize_time_input(data.get("requested_check_out"), "Requested check-out")
                reason = str(data.get("reason", "")).strip()
                if not reason: raise ValueError("Please explain why an adjustment is needed")
                req = "ATR-" + uuid.uuid4().hex[:10].upper()
                con.execute("INSERT INTO attendance_adjustments(request_id,employee_id,work_date,requested_check_in,requested_check_out,reason,created_at) VALUES(?,?,?,?,?,?,?)", (req, empid, work_date, requested_check_in, requested_check_out, reason, now_iso()))
                audit(con, actor, "REQUEST", "AttendanceAdjustment", req, {"employee_id": empid})
                con.commit(); return {"ok": True, "request_id": req}
            if path.startswith("/api/attendance/adjustments/") and path.endswith("/decision"):
                if user["role"] not in HR_ROLES | {"manager"}: raise PermissionError("Not permitted")
                request_id = path.split("/")[-2]
                if user["role"] == "manager":
                    pending = con.execute("SELECT employee_id FROM attendance_adjustments WHERE request_id=?", (request_id,)).fetchone()
                    if not pending or not self.manager_can_see(con, user, pending["employee_id"]): raise PermissionError("You can only review your team's correction requests")
                decision = str(data.get("decision", ""))
                if decision not in ("Approved", "Rejected"): raise ValueError("Decision must be Approved or Rejected")
                con.execute("UPDATE attendance_adjustments SET status=?,reviewer=?,review_comment=?,reviewed_at=? WHERE request_id=? AND status='Pending'", (decision, actor, str(data.get("comment", "")), now_iso(), request_id))
                if con.total_changes == 0: raise ValueError("Pending adjustment not found")
                audit(con, actor, decision.upper(), "AttendanceAdjustment", request_id, data)
                con.commit(); return {"ok": True}
            if path == "/api/leaves":
                empid = user.get("employee_id") if user["role"] == "employee" else str(data.get("employee_id", "")).strip()
                if user["role"] not in HR_ROLES | {"employee"}: raise PermissionError("Not permitted")
                if not empid: raise ValueError("Employee ID is required")
                start = valid_date(str(data.get("start_date", "")), "Start date")
                end = valid_date(str(data.get("end_date", "")), "End date")
                if end < start: raise ValueError("End date must be on or after start date")
                reason = str(data.get("reason", "")).strip()
                if not reason: raise ValueError("Leave reason is required")
                leave_type_id = data.get("leave_type_id") or None
                overlap = con.execute("SELECT request_id FROM leave_requests WHERE employee_id=? AND status!='Rejected' AND start_date<=? AND end_date>=? LIMIT 1", (empid,end,start)).fetchone()
                if overlap: raise ValueError(f"This request overlaps an existing leave request ({overlap['request_id']})")
                total_days = self.calculate_leave_days(con, start, end)
                if total_days <= 0: raise ValueError("The selected period contains no working days based on configured holidays/week-offs")
                req = "LRQ-" + uuid.uuid4().hex[:10].upper()
                con.execute("INSERT INTO leave_requests(request_id,employee_id,leave_type_id,start_date,end_date,days,reason,created_at) VALUES(?,?,?,?,?,?,?,?)", (req, empid, leave_type_id, start, end, total_days, reason, now_iso()))
                doc_id = ""
                if data.get("document"):
                    doc_id = self.store_uploaded_file(con, data["document"], "leave_document", empid, req, actor)
                    con.execute("UPDATE leave_requests SET document_file_id=? WHERE request_id=?", (doc_id, req))
                audit(con, actor, "CREATE", "LeaveRequest", req, {"employee_id": empid, "days": total_days, "document_attached": bool(doc_id)})
                con.commit(); return {"ok": True, "request_id": req, "days": total_days}
            if path.startswith("/api/leaves/") and path.endswith("/decision"):
                request_id = path.split("/")[-2]
                leave = con.execute("SELECT * FROM leave_requests WHERE request_id=?", (request_id,)).fetchone()
                if not leave: raise ValueError("Leave request not found")
                decision = str(data.get("decision", ""))
                if decision not in ("Approved", "Rejected"): raise ValueError("Decision must be Approved or Rejected")
                comment = str(data.get("comment", ""))
                if user["role"] == "manager":
                    if leave["status"] != "Pending Manager Approval" or not self.manager_can_see(con, user, leave["employee_id"]): raise PermissionError("This request is not assigned to your approval queue")
                    new_status = "Pending HR Approval" if decision == "Approved" else "Rejected"
                    con.execute("UPDATE leave_requests SET manager_decision=?,manager_comment=?,manager_decided_by=?,manager_decided_at=?,status=? WHERE request_id=?", (decision, comment, actor, now_iso(), new_status, request_id))
                else:
                    self.require_user(HR_ROLES)
                    if leave["status"] not in ("Pending HR Approval", "Pending Manager Approval") and user["role"] not in ADMIN_ROLES: raise ValueError("This leave request is not awaiting HR approval")
                    if leave["status"] == "Pending Manager Approval" and decision == "Approved":
                        # HR admins may complete both steps when operationally necessary; audit captures the override.
                        con.execute("UPDATE leave_requests SET manager_decision='HR Override',manager_comment='Completed by HR',manager_decided_by=?,manager_decided_at=? WHERE request_id=?", (actor, now_iso(), request_id))
                    con.execute("UPDATE leave_requests SET hr_decision=?,hr_comment=?,hr_decided_by=?,hr_decided_at=?,status=? WHERE request_id=?", (decision, comment, actor, now_iso(), decision, request_id))
                audit(con, actor, decision.upper(), "LeaveRequest", request_id, {"comment": comment})
                con.commit(); return {"ok": True}
            if path == "/api/leave-types":
                self.require_user(HR_ROLES)
                name = str(data.get("name", "")).strip()
                if not name: raise ValueError("Leave type name is required")
                entitlement = data.get("entitlement_days")
                entitlement = safe_float(entitlement) if entitlement not in (None, "") else None
                paid = str(data.get("paid_status", "To be configured"))
                if paid not in ("Paid", "Unpaid", "To be configured"): raise ValueError("Invalid paid status")
                cur = con.execute("INSERT INTO leave_types(name,entitlement_days,paid_status) VALUES(?,?,?)", (name, entitlement, paid))
                audit(con, actor, "CREATE", "LeaveType", str(cur.lastrowid), data)
                con.commit(); return {"ok": True, "id": cur.lastrowid}
            if path.startswith("/api/leave-types/") and path.endswith("/update"):
                self.require_user(HR_ROLES)
                type_id=path.split("/")[-2]
                row=con.execute("SELECT * FROM leave_types WHERE id=?",(type_id,)).fetchone()
                if not row: raise ValueError("Leave type not found")
                name=str(data.get("name",row["name"])).strip()
                paid=str(data.get("paid_status",row["paid_status"]))
                if not name: raise ValueError("Leave type name is required")
                if paid not in {"To be configured","Paid","Unpaid"}: raise ValueError("Invalid paid status")
                entitlement=data.get("entitlement_days",row["entitlement_days"])
                entitlement=safe_float(entitlement) if entitlement not in (None,"") else None
                con.execute("UPDATE leave_types SET name=?,paid_status=?,entitlement_days=? WHERE id=?",(name,paid,entitlement,type_id))
                audit(con,actor,"UPDATE","LeaveType",type_id,{"name":name,"paid_status":paid,"entitlement_days":entitlement})
                con.commit(); return {"ok":True}
            if path == "/api/holidays":
                self.require_user(HR_ROLES)
                holiday_date = valid_date(str(data.get("holiday_date", "")), "Holiday date")
                name = str(data.get("name", "")).strip()
                if not name: raise ValueError("Holiday name is required")
                cur = con.execute("INSERT INTO holidays(holiday_date,name) VALUES(?,?)", (holiday_date, name))
                audit(con, actor, "CREATE", "Holiday", str(cur.lastrowid), data)
                con.commit(); return {"ok": True, "id": cur.lastrowid}
            if path.startswith("/api/employees/") and path.endswith("/salary"):
                self.require_user(PAYROLL_ROLES)
                empid=urllib.parse.unquote(path.split("/")[-2])
                if not con.execute("SELECT 1 FROM employees WHERE employee_id=?",(empid,)).fetchone(): raise ValueError("Employee not found")
                effective_from=valid_date(str(data.get("effective_from") or today_iso()),"Effective date")
                basic=safe_float(data.get("basic_salary"),-1); allowance=safe_float(data.get("fixed_allowances"),0)
                if basic<0 or allowance<0: raise ValueError("Salary values cannot be negative")
                payroll_con=connect_payroll_db()
                try:
                    if payroll_con.execute("SELECT 1 FROM salary_records WHERE employee_id=? AND effective_from=?",(empid,effective_from)).fetchone():
                        raise ValueError("A salary record already exists for this effective date")
                    previous_end=(date.fromisoformat(effective_from)-timedelta(days=1)).isoformat()
                    payroll_con.execute("UPDATE salary_records SET effective_to=? WHERE employee_id=? AND effective_to IS NULL AND effective_from<?",(previous_end,empid,effective_from))
                    cur=payroll_con.execute("INSERT INTO salary_records(employee_id,effective_from,basic_salary,fixed_allowances,notes,created_at,created_by) VALUES(?,?,?,?,?,?,?)",(empid,effective_from,basic,allowance,str(data.get("notes","")),now_iso(),actor))
                    payroll_con.commit()
                finally: payroll_con.close()
                audit(con,actor,"UPDATE_SALARY","Employee",empid,{"effective_from":effective_from,"basic_salary":basic,"fixed_allowances":allowance})
                con.commit(); return {"ok":True,"id":cur.lastrowid}
            if path == "/api/payroll/salary":
                self.require_user(PAYROLL_ROLES)
                empid = str(data.get("employee_id", "")).strip()
                effective_from = valid_date(str(data.get("effective_from", "")), "Effective date")
                basic = safe_float(data.get("basic_salary"), -1)
                allowance = safe_float(data.get("fixed_allowances"), -1)
                if not empid or basic < 0 or allowance < 0: raise ValueError("Employee, valid basic salary and allowance are required")
                if not con.execute("SELECT 1 FROM employees WHERE employee_id=?", (empid,)).fetchone(): raise ValueError("Employee not found")
                payroll_con = connect_payroll_db()
                try:
                    duplicate = payroll_con.execute("SELECT 1 FROM salary_records WHERE employee_id=? AND effective_from=?", (empid,effective_from)).fetchone()
                    if duplicate: raise ValueError("A salary record already exists for this employee and effective date")
                    previous_end = (date.fromisoformat(effective_from)-timedelta(days=1)).isoformat()
                    payroll_con.execute("UPDATE salary_records SET effective_to=? WHERE employee_id=? AND effective_to IS NULL AND effective_from<?", (previous_end, empid, effective_from))
                    cur = payroll_con.execute("INSERT INTO salary_records(employee_id,effective_from,basic_salary,fixed_allowances,notes,created_at,created_by) VALUES(?,?,?,?,?,?,?)", (empid, effective_from, basic, allowance, str(data.get("notes", "")), now_iso(), actor))
                    payroll_con.commit()
                finally:
                    payroll_con.close()
                audit(con, actor, "CREATE", "SalaryRecord", str(cur.lastrowid), {"employee_id": empid, "effective_from": effective_from})
                con.commit(); return {"ok": True, "id": cur.lastrowid}
            if path == "/api/payroll/preview":
                self.require_user(PAYROLL_ROLES)
                pay_month = str(data.get("pay_month", ""))
                if not re.fullmatch(r"\d{4}-\d{2}", pay_month): raise ValueError("Pay month must use YYYY-MM format")
                try: date.fromisoformat(pay_month + "-01")
                except Exception: raise ValueError("Invalid pay month")
                payroll_con = connect_payroll_db()
                try:
                    existing = payroll_con.execute("SELECT * FROM payroll_runs WHERE pay_month=?", (pay_month,)).fetchone()
                    if existing and existing["status"] == "Approved": raise ValueError("This month's payroll has already been approved and is locked")
                    if existing:
                        run_id = existing["run_id"]
                        payroll_con.execute("DELETE FROM payroll_items WHERE run_id=?", (run_id,))
                    else:
                        run_id = "PAY-" + pay_month.replace("-", "") + "-" + uuid.uuid4().hex[:5].upper()
                        payroll_con.execute("INSERT INTO payroll_runs(run_id,pay_month,status,created_at,created_by) VALUES(?,?, 'Draft',?,?)", (run_id, pay_month, now_iso(), actor))
                    month_end = (date.fromisoformat(pay_month+"-01").replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                    employees = con.execute("SELECT * FROM employees WHERE employment_status IN ('Active','Probation','On Notice') ORDER BY full_name").fetchall()
                    preview = []
                    for emp in employees:
                        sal = payroll_con.execute("SELECT * FROM salary_records WHERE employee_id=? AND effective_from<=? AND (effective_to IS NULL OR effective_to>=?) ORDER BY effective_from DESC LIMIT 1", (emp["employee_id"], month_end.isoformat(), month_end.isoformat())).fetchone()
                        base_basic = float(sal["basic_salary"]) if sal else 0.0
                        base_allowance = float(sal["fixed_allowances"]) if sal else 0.0
                        profile_emp = con.execute("SELECT e.*,s.* FROM employees e LEFT JOIN shifts s ON s.id=e.shift_id WHERE e.employee_id=?",(emp["employee_id"],)).fetchone()
                        attendance = self.employee_attendance_summary(con, profile_emp, pay_month) if profile_emp else {"configured":False,"scheduled_days":0}
                        scheduled = float(attendance.get("scheduled_days",0)); present = float(attendance.get("present_days",0)); paid_leave = float(attendance.get("paid_leave_days",0))
                        payable = present + paid_leave
                        factor = min(1.0, payable/scheduled) if scheduled>0 else 0.0
                        calculation_status = "Salary Required" if not sal else ("Calculated" if attendance.get("configured") and scheduled>0 else "Shift Required")
                        basic = round(base_basic*factor,2) if calculation_status=="Calculated" else 0.0
                        allowance = round(base_allowance*factor,2) if calculation_status=="Calculated" else 0.0
                        gross = basic + allowance; net = gross
                        payroll_con.execute("INSERT INTO payroll_items(run_id,employee_id,basic_salary,allowances,overtime,bonus,deductions,adjustments,gross_salary,net_salary,scheduled_days,present_days,late_days,absent_days,paid_leave_days,payable_days,attendance_factor,calculation_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (run_id, emp["employee_id"], basic, allowance, 0, 0, 0, 0, gross, net, scheduled, present, float(attendance.get("late_days",0)), float(attendance.get("absent_days",0)), paid_leave, payable, factor, calculation_status))
                        preview.append({"employee_id": emp["employee_id"], "full_name": emp["full_name"], "basic_salary": basic, "allowances": allowance, "gross_salary": gross, "net_salary": net, "salary_configured": bool(sal), "scheduled_days":scheduled,"present_days":present,"late_days":attendance.get("late_days",0),"absent_days":attendance.get("absent_days",0),"paid_leave_days":paid_leave,"payable_days":payable,"attendance_factor":factor,"calculation_status":calculation_status})
                    payroll_con.commit()
                finally:
                    payroll_con.close()
                audit(con, actor, "PREVIEW", "PayrollRun", run_id, {"pay_month": pay_month, "employees": len(preview)})
                con.commit(); return {"ok": True, "run_id": run_id, "items": preview, "warning": "Preview only. Add approved variable earnings/deductions and verify policy before approval. Unconfigured salaries are shown as zero."}
            if path.startswith("/api/payroll/run/") and path.endswith("/approve"):
                self.require_user(PAYROLL_ROLES)
                run_id = path.split("/")[-2]
                payroll_con = connect_payroll_db()
                try:
                    run = payroll_con.execute("SELECT * FROM payroll_runs WHERE run_id=?", (run_id,)).fetchone()
                    if not run: raise ValueError("Payroll run not found")
                    if run["status"] == "Approved": raise ValueError("Payroll is already approved")
                    if run["pay_month"] >= now_dt().strftime("%Y-%m"):
                        raise ValueError("A payroll month can only be approved after that month has ended. You can still prepare and review the draft.")
                    count = payroll_con.execute("SELECT COUNT(*) FROM payroll_items WHERE run_id=?", (run_id,)).fetchone()[0]
                    if count == 0: raise ValueError("There are no payroll items to approve")
                    unconfigured = payroll_con.execute("SELECT COUNT(*) FROM payroll_items WHERE run_id=? AND calculation_status!='Calculated'",(run_id,)).fetchone()[0]
                    if unconfigured: raise ValueError(f"{unconfigured} employee(s) need a shift with working days and start time before payroll can be approved")
                    payroll_con.execute("UPDATE payroll_runs SET status='Approved',approved_at=?,approved_by=? WHERE run_id=?", (now_iso(), actor, run_id))
                    payroll_con.execute("INSERT INTO payroll_audit_log(actor,action,entity,entity_id,created_at) VALUES(?,?,?,?,?)", (actor,"APPROVE","PayrollRun",run_id,now_iso()))
                    payroll_con.commit()
                finally:
                    payroll_con.close()
                audit(con, actor, "APPROVE", "PayrollRun", run_id, {"items": count})
                con.commit(); return {"ok": True}
            if path.startswith("/api/payroll/run/") and path.endswith("/items"):
                self.require_user(PAYROLL_ROLES)
                run_id = path.split("/")[-2]
                item_id = str(data.get("employee_id", ""))
                payroll_con = connect_payroll_db()
                try:
                    run = payroll_con.execute("SELECT status FROM payroll_runs WHERE run_id=?", (run_id,)).fetchone()
                    if not run or run["status"] == "Approved": raise ValueError("Payroll run not found or is locked")
                    item = payroll_con.execute("SELECT * FROM payroll_items WHERE run_id=? AND employee_id=?", (run_id, item_id)).fetchone()
                    if not item: raise ValueError("Payroll item not found")
                    overtime, bonus, deductions, adjustments = [safe_float(data.get(k), 0) for k in ("overtime", "bonus", "deductions", "adjustments")]
                    if any(v < 0 for v in (overtime,bonus,deductions,adjustments)): raise ValueError("Payroll amounts cannot be negative")
                    gross = item["basic_salary"] + item["allowances"] + overtime + bonus
                    net = gross - deductions - adjustments
                    payroll_con.execute("UPDATE payroll_items SET overtime=?,bonus=?,deductions=?,adjustments=?,gross_salary=?,net_salary=?,notes=? WHERE run_id=? AND employee_id=?", (overtime, bonus, deductions, adjustments, gross, net, str(data.get("notes", "")), run_id, item_id))
                    payroll_con.execute("INSERT INTO payroll_audit_log(actor,action,entity,entity_id,created_at) VALUES(?,?,?,?,?)", (actor,"UPDATE","PayrollItem",f"{run_id}:{item_id}",now_iso()))
                    payroll_con.commit()
                finally:
                    payroll_con.close()
                audit(con, actor, "UPDATE", "PayrollItem", f"{run_id}:{item_id}", {k:v for k,v in data.items() if k!="notes"})
                con.commit(); return {"ok": True, "gross_salary": gross, "net_salary": net}
            if path == "/api/tasks":
                if user["role"] not in HR_ROLES | {"manager"}: raise PermissionError("Only HR or managers can assign production tasks")
                project=str(data.get("project_name","")).strip(); title=str(data.get("task_title","")).strip(); editing=str(data.get("editing_type","")).strip()
                if not project or not title or not editing: raise ValueError("Project, task title and editing type are required")
                priority=str(data.get("priority","Normal"))
                if priority not in {"Low","Normal","High","Urgent"}: raise ValueError("Invalid task priority")
                image_count=int(safe_float(data.get("image_count"),0))
                if image_count<1 or image_count>100000: raise ValueError("Image count must be between 1 and 100000")
                due=data.get("due_date") or None
                if due: valid_date(str(due),"Due date")
                scope=str(data.get("assigned_scope","Selected"))
                if scope not in {"All","Selected"}: raise ValueError("Invalid assignment scope")
                if scope=="All":
                    if user["role"]=="manager":
                        employees=con.execute("SELECT employee_id FROM employees WHERE (reporting_manager=? OR employee_id=?) AND employment_status IN ('Active','Probation')",(user.get("employee_id") or "",user.get("employee_id") or "")).fetchall()
                    else:
                        employees=con.execute("SELECT employee_id FROM employees WHERE employment_status IN ('Active','Probation')",()).fetchall()
                    empids=[r[0] for r in employees]
                else:
                    empids=data.get("employee_ids",[])
                    if isinstance(empids,str): empids=[empids]
                    empids=list(dict.fromkeys(str(x) for x in empids if x))
                if not empids: raise ValueError("Select at least one employee to assign this task")
                for empid in empids:
                    if not con.execute("SELECT 1 FROM employees WHERE employee_id=? AND employment_status IN ('Active','Probation')",(empid,)).fetchone(): raise ValueError(f"Employee {empid} is not active")
                    if user["role"]=="manager" and not self.manager_can_see(con,user,empid): raise PermissionError("Managers can only assign tasks to their own team")
                task_id="LR-TASK-"+uuid.uuid4().hex[:10].upper()
                con.execute("INSERT INTO production_tasks(task_id,project_name,client_name,task_title,editing_type,priority,image_count,due_date,instructions,source_link,assigned_scope,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(task_id,project,str(data.get("client_name","")),title,editing,priority,image_count,due,str(data.get("instructions","")),str(data.get("source_link","")),scope,actor,now_iso(),now_iso()))
                con.executemany("INSERT INTO task_assignments(task_id,employee_id,status,updated_at) VALUES(?,?, 'Assigned',?)",[(task_id,x,now_iso()) for x in empids])
                audit(con,actor,"ASSIGN","ProductionTask",task_id,{"scope":scope,"employees":empids,"images":image_count})
                con.commit(); return {"ok":True,"task_id":task_id,"assigned_count":len(empids)}
            task_admin_match = re.fullmatch(r"/api/tasks/([^/]+)/(update|delete)", path)
            if task_admin_match:
                if user["role"] not in HR_ROLES | {"manager"}: raise PermissionError("Only HR or managers can manage production task details")
                task_id, action = task_admin_match.group(1), task_admin_match.group(2)
                task = con.execute("SELECT * FROM production_tasks WHERE task_id=?", (task_id,)).fetchone()
                if not task: raise ValueError("Production task not found")
                assignments = rowsdict(con.execute("SELECT employee_id FROM task_assignments WHERE task_id=?", (task_id,)).fetchall())
                if user["role"] == "manager" and any(not self.manager_can_see(con, user, row["employee_id"]) for row in assignments): raise PermissionError("Managers can only manage assignments for their own team")
                if action == "delete":
                    con.execute("UPDATE production_tasks SET is_active=0,updated_at=? WHERE task_id=?", (now_iso(), task_id))
                    audit(con, actor, "ARCHIVE", "ProductionTask", task_id, {"project_name":task["project_name"]})
                    con.commit(); return {"ok":True,"archived":True}
                values = {k:data.get(k, task[k]) for k in ("project_name","client_name","task_title","editing_type","priority","image_count","due_date","instructions","source_link")}
                for k in ("project_name","task_title","editing_type"):
                    values[k] = str(values[k] or "").strip()
                    if not values[k]: raise ValueError(f"{k.replace('_',' ').capitalize()} is required")
                if values["priority"] not in {"Low","Normal","High","Urgent"}: raise ValueError("Invalid task priority")
                image_count = int(safe_float(values["image_count"],0))
                if image_count < 1 or image_count > 100000: raise ValueError("Image count must be between 1 and 100000")
                if any(row[0] > image_count for row in con.execute("SELECT completed_images FROM task_assignments WHERE task_id=?", (task_id,)).fetchall()): raise ValueError("New image quantity cannot be below work already submitted")
                if values["due_date"]: valid_date(str(values["due_date"]), "Due date")
                con.execute("UPDATE production_tasks SET project_name=?,client_name=?,task_title=?,editing_type=?,priority=?,image_count=?,due_date=?,instructions=?,source_link=?,updated_at=? WHERE task_id=?", (values["project_name"],str(values["client_name"] or ""),values["task_title"],values["editing_type"],values["priority"],image_count,values["due_date"] or None,str(values["instructions"] or ""),str(values["source_link"] or ""),now_iso(),task_id))
                audit(con, actor, "UPDATE", "ProductionTask", task_id, values)
                con.commit(); return {"ok":True}
            if path.startswith("/api/tasks/") and path.endswith("/progress"):
                if user["role"]!="employee": raise PermissionError("Employees update their own task progress")
                task_id=path.split("/")[-2]
                assignment=con.execute("SELECT * FROM task_assignments WHERE task_id=? AND employee_id=?",(task_id,user.get("employee_id"))).fetchone()
                if not assignment: raise PermissionError("This task is not assigned to your account")
                status=str(data.get("status","In Progress"))
                if status!="In Progress" or assignment["status"] not in {"Assigned","In Progress","Revision Required"}: raise ValueError("This task cannot be started")
                con.execute("UPDATE task_assignments SET status='In Progress',started_at=COALESCE(started_at,?),updated_at=? WHERE task_id=? AND employee_id=?",(now_iso(),now_iso(),task_id,user["employee_id"]))
                audit(con,actor,"START","ProductionTask",task_id,{"employee_id":user["employee_id"]})
                con.commit(); return {"ok":True}
            if path.startswith("/api/tasks/") and path.endswith("/submit"):
                if user["role"]!="employee": raise PermissionError("Only the assigned employee can submit this work")
                task_id=path.split("/")[-2]
                assignment=con.execute("SELECT * FROM task_assignments WHERE task_id=? AND employee_id=?",(task_id,user.get("employee_id"))).fetchone()
                if not assignment: raise PermissionError("This task is not assigned to your account")
                completed=int(safe_float(data.get("completed_images"),0))
                if completed<1: raise ValueError("Enter the number of completed images")
                task=con.execute("SELECT image_count FROM production_tasks WHERE task_id=?",(task_id,)).fetchone()
                if not task: raise ValueError("Task not found")
                if completed>task["image_count"]: raise ValueError("Completed image count cannot exceed the assigned image count")
                output=str(data.get("output_link","")).strip()
                notes=str(data.get("submission_notes","")).strip()
                if not output and not notes: raise ValueError("Add an output folder/link or submission notes")
                con.execute("UPDATE task_assignments SET status='Submitted',completed_images=?,output_link=?,submission_notes=?,submitted_at=?,updated_at=? WHERE task_id=? AND employee_id=?",(completed,output,notes,now_iso(),now_iso(),task_id,user["employee_id"]))
                audit(con,actor,"SUBMIT","ProductionTask",task_id,{"employee_id":user["employee_id"],"completed_images":completed})
                con.commit(); return {"ok":True}
            if path.startswith("/api/tasks/") and path.endswith("/review"):
                if user["role"] not in HR_ROLES | {"manager"}: raise PermissionError("Only HR or the assigned manager can review task submissions")
                task_id=path.split("/")[-2]; empid=str(data.get("employee_id","")); decision=str(data.get("decision",""))
                if decision not in {"Approved","Revision Required"}: raise ValueError("Invalid task review decision")
                assignment=con.execute("SELECT * FROM task_assignments WHERE task_id=? AND employee_id=?",(task_id,empid)).fetchone()
                if not assignment or assignment["status"]!="Submitted": raise ValueError("Submitted task assignment not found")
                if user["role"]=="manager" and not self.manager_can_see(con,user,empid): raise PermissionError("You can only review your team's submissions")
                con.execute("UPDATE task_assignments SET status=?,review_note=?,reviewed_by=?,reviewed_at=?,updated_at=? WHERE task_id=? AND employee_id=?",(decision,str(data.get("review_note","")),actor,now_iso(),now_iso(),task_id,empid))
                audit(con,actor,"REVIEW_"+decision.upper().replace(" ","_"),"ProductionTask",task_id,{"employee_id":empid})
                con.commit(); return {"ok":True}
            if path == "/api/recruitment/positions":
                self.require_user(HR_ROLES)
                name = str(data.get("name", "")).strip()
                if not name: raise ValueError("Position name is required")
                cur = con.execute("INSERT INTO recruitment_positions(name,created_at) VALUES(?,?)", (name, now_iso()))
                audit(con, actor, "CREATE", "RecruitmentPosition", str(cur.lastrowid), {"name":name})
                con.commit(); return {"ok":True,"id":cur.lastrowid}
            if path.startswith("/api/recruitment/positions/") and path.endswith("/update"):
                self.require_user(HR_ROLES)
                rid=path.split("/")[-2]; name=str(data.get("name","")).strip()
                if not name: raise ValueError("Position name is required")
                con.execute("UPDATE recruitment_positions SET name=? WHERE id=?",(name,rid))
                audit(con,actor,"UPDATE","RecruitmentPosition",rid,{"name":name}); con.commit(); return {"ok":True}
            if path.startswith("/api/recruitment/positions/") and path.endswith("/delete"):
                self.require_user(HR_ROLES); rid=path.split("/")[-2]
                con.execute("UPDATE recruitment_positions SET is_active=0 WHERE id=?",(rid,))
                audit(con,actor,"ARCHIVE","RecruitmentPosition",rid); con.commit(); return {"ok":True}
            if path == "/api/recruitment":
                self.require_user(HR_ROLES)
                name = str(data.get("full_name", "")).strip()
                position = str(data.get("position", "")).strip()
                if not name or not position: raise ValueError("Candidate name and position are required")
                cid = next_id(con, "candidates", "candidate_id", "LR-CAN-")
                cur = con.execute("INSERT INTO candidates(candidate_id,full_name,email,phone,position,source,stage,interview_date,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (cid,name,str(data.get("email","")),str(data.get("phone","")),position,str(data.get("source","")),str(data.get("stage","Applied")),data.get("interview_date") or None,str(data.get("notes","")),now_iso(),now_iso()))
                audit(con, actor, "CREATE", "Candidate", cid, data)
                con.commit(); return {"ok": True, "candidate_id": cid}
            candidate_match = re.fullmatch(r"/api/recruitment/([^/]+)/(update|delete)", path)
            if candidate_match:
                self.require_user(HR_ROLES)
                cid, action = candidate_match.group(1), candidate_match.group(2)
                current = con.execute("SELECT * FROM candidates WHERE candidate_id=?", (cid,)).fetchone()
                if not current: raise ValueError("Candidate not found")
                if action == "delete":
                    con.execute("UPDATE candidates SET is_archived=1,updated_at=? WHERE candidate_id=?", (now_iso(), cid))
                    audit(con, actor, "ARCHIVE", "Candidate", cid)
                    con.commit(); return {"ok":True,"archived":True}
                name = str(data.get("full_name", current["full_name"])).strip()
                position = str(data.get("position", current["position"])).strip()
                stage = str(data.get("stage", current["stage"]))
                allowed_stages = {"Applied","Shortlisted","Interview Scheduled","Interviewed","Selected","Offer Sent","Offer Accepted","Joined","Rejected","Withdrawn","On Hold"}
                if not name or not position: raise ValueError("Candidate name and position are required")
                if stage not in allowed_stages: raise ValueError("Invalid recruitment stage")
                interview_date = data.get("interview_date", current["interview_date"]) or None
                if interview_date: valid_date(str(interview_date), "Interview date")
                con.execute("UPDATE candidates SET full_name=?,email=?,phone=?,position=?,source=?,stage=?,interview_date=?,notes=?,updated_at=? WHERE candidate_id=?", (name,str(data.get("email",current["email"])),str(data.get("phone",current["phone"])),position,str(data.get("source",current["source"])),stage,interview_date,str(data.get("notes",current["notes"])),now_iso(),cid))
                audit(con, actor, "UPDATE", "Candidate", cid, data)
                con.commit(); return {"ok":True}
            if path.startswith("/api/recruitment/") and path.endswith("/stage"):
                self.require_user(HR_ROLES)
                cid = path.split("/")[-2]
                stage = str(data.get("stage", ""))
                allowed = {"Applied","Shortlisted","Interview Scheduled","Interviewed","Selected","Offer Sent","Offer Accepted","Joined","Rejected","Withdrawn","On Hold"}
                if stage not in allowed: raise ValueError("Invalid recruitment stage")
                con.execute("UPDATE candidates SET stage=?,updated_at=? WHERE candidate_id=?", (stage, now_iso(), cid))
                audit(con, actor, "UPDATE_STAGE", "Candidate", cid, {"stage": stage})
                con.commit(); return {"ok": True}
            if path == "/api/assets":
                self.require_user(HR_ROLES)
                name = str(data.get("asset_name", "")).strip()
                if not name: raise ValueError("Asset name is required")
                aid = next_id(con, "assets", "asset_id", "LR-AST-")
                cur = con.execute("INSERT INTO assets(asset_id,asset_name,category,serial_number,purchase_date,assigned_employee,assignment_date,condition_status,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (aid,name,str(data.get("category","")),str(data.get("serial_number","")),str(data.get("purchase_date","")),data.get("assigned_employee") or None,data.get("assignment_date") or None,str(data.get("condition_status","Good")),str(data.get("notes","")),now_iso()))
                audit(con, actor, "CREATE", "Asset", aid, data)
                con.commit(); return {"ok": True, "asset_id": aid}
            asset_match = re.fullmatch(r"/api/assets/([^/]+)/(update|delete)", path)
            if asset_match:
                self.require_user(HR_ROLES)
                aid, action = asset_match.group(1), asset_match.group(2)
                current = con.execute("SELECT * FROM assets WHERE asset_id=?", (aid,)).fetchone()
                if not current: raise ValueError("Asset record not found")
                if action == "delete":
                    con.execute("UPDATE assets SET is_archived=1 WHERE asset_id=?", (aid,))
                    audit(con, actor, "ARCHIVE", "Asset", aid)
                    con.commit(); return {"ok":True,"archived":True}
                name = str(data.get("asset_name", current["asset_name"])).strip()
                if not name: raise ValueError("Asset name is required")
                assigned = data.get("assigned_employee", current["assigned_employee"]) or None
                if assigned and not con.execute("SELECT 1 FROM employees WHERE employee_id=?", (assigned,)).fetchone(): raise ValueError("Assigned employee does not exist")
                con.execute("UPDATE assets SET asset_name=?,category=?,serial_number=?,purchase_date=?,assigned_employee=?,assignment_date=?,condition_status=?,return_date=?,return_condition=?,notes=? WHERE asset_id=?", (name,str(data.get("category",current["category"])),str(data.get("serial_number",current["serial_number"])),str(data.get("purchase_date",current["purchase_date"])),assigned,data.get("assignment_date",current["assignment_date"]) or None,str(data.get("condition_status",current["condition_status"])),data.get("return_date",current["return_date"]) or None,str(data.get("return_condition",current["return_condition"])),str(data.get("notes",current["notes"])),aid))
                audit(con, actor, "UPDATE", "Asset", aid, data)
                con.commit(); return {"ok":True}
            if path == "/api/performance":
                if user["role"] not in HR_ROLES | {"manager"}: raise PermissionError("Not permitted")
                empid = str(data.get("employee_id", "")).strip()
                if user["role"] == "manager" and not self.manager_can_see(con, user, empid): raise PermissionError("You can only create reviews for your team")
                period = str(data.get("review_period", "")).strip()
                if not empid or not period: raise ValueError("Employee and review period are required")
                score = data.get("score")
                score = safe_float(score) if score not in (None, "") else None
                rid = "REV-" + uuid.uuid4().hex[:10].upper()
                con.execute("INSERT INTO performance_reviews(review_id,employee_id,review_period,review_type,score,reviewer,feedback,goals,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (rid,empid,period,str(data.get("review_type","Quarterly")),score,actor,str(data.get("feedback","")),str(data.get("goals","")),str(data.get("status","Draft")),now_iso()))
                audit(con, actor, "CREATE", "PerformanceReview", rid, {"employee_id": empid})
                con.commit(); return {"ok": True, "review_id": rid}
            review_match = re.fullmatch(r"/api/performance/([^/]+)/(update|delete)", path)
            if review_match:
                if user["role"] not in HR_ROLES | {"manager"}: raise PermissionError("Not permitted")
                rid, action = review_match.group(1), review_match.group(2)
                current = con.execute("SELECT * FROM performance_reviews WHERE review_id=?", (rid,)).fetchone()
                if not current: raise ValueError("Performance review not found")
                if user["role"] == "manager" and not self.manager_can_see(con, user, current["employee_id"]): raise PermissionError("You can only manage your team's reviews")
                if action == "delete":
                    con.execute("UPDATE performance_reviews SET is_archived=1 WHERE review_id=?", (rid,))
                    audit(con, actor, "ARCHIVE", "PerformanceReview", rid)
                    con.commit(); return {"ok":True,"archived":True}
                period = str(data.get("review_period", current["review_period"])).strip()
                if not period: raise ValueError("Review period is required")
                score_raw = data.get("score", current["score"])
                score = safe_float(score_raw) if score_raw not in (None, "") else None
                status = str(data.get("status", current["status"]))
                if status not in {"Draft","Submitted","Completed"}: raise ValueError("Invalid review status")
                con.execute("UPDATE performance_reviews SET review_period=?,review_type=?,score=?,feedback=?,goals=?,status=? WHERE review_id=?", (period,str(data.get("review_type",current["review_type"])),score,str(data.get("feedback",current["feedback"])),str(data.get("goals",current["goals"])),status,rid))
                audit(con, actor, "UPDATE", "PerformanceReview", rid, data)
                con.commit(); return {"ok":True}
            if path == "/api/disciplinary":
                self.require_user(HR_ROLES)
                empid = str(data.get("employee_id", "")).strip()
                record_type = str(data.get("record_type", "")).strip()
                incident = valid_date(str(data.get("incident_date", "")), "Incident date")
                desc = str(data.get("description", "")).strip()
                if not empid or not record_type or not desc: raise ValueError("Employee, record type and description are required")
                rid = "DIS-" + uuid.uuid4().hex[:10].upper()
                con.execute("INSERT INTO disciplinary_records(record_id,employee_id,record_type,incident_date,description,employee_response,decision,follow_up_date,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (rid,empid,record_type,incident,desc,str(data.get("employee_response","")),"Pending Review",data.get("follow_up_date") or None,actor,now_iso()))
                audit(con, actor, "CREATE", "DisciplinaryRecord", rid, {"employee_id": empid, "type": record_type})
                con.commit(); return {"ok": True, "record_id": rid}
            discipline_match = re.fullmatch(r"/api/disciplinary/([^/]+)/(update|delete)", path)
            if discipline_match:
                self.require_user(HR_ROLES)
                rid, action = discipline_match.group(1), discipline_match.group(2)
                current = con.execute("SELECT * FROM disciplinary_records WHERE record_id=?", (rid,)).fetchone()
                if not current: raise ValueError("Disciplinary record not found")
                if action == "delete":
                    con.execute("UPDATE disciplinary_records SET is_archived=1 WHERE record_id=?", (rid,))
                    audit(con, actor, "ARCHIVE", "DisciplinaryRecord", rid)
                    con.commit(); return {"ok":True,"archived":True}
                record_type = str(data.get("record_type", current["record_type"])).strip()
                incident = valid_date(str(data.get("incident_date", current["incident_date"])), "Incident date")
                description = str(data.get("description", current["description"])).strip()
                if not record_type or not description: raise ValueError("Record type and description are required")
                follow = data.get("follow_up_date", current["follow_up_date"]) or None
                if follow: valid_date(str(follow), "Follow-up date")
                con.execute("UPDATE disciplinary_records SET record_type=?,incident_date=?,description=?,employee_response=?,decision=?,follow_up_date=? WHERE record_id=?", (record_type,incident,description,str(data.get("employee_response",current["employee_response"])),str(data.get("decision",current["decision"])),follow,rid))
                audit(con, actor, "UPDATE", "DisciplinaryRecord", rid, {"record_type":record_type,"decision":data.get("decision",current["decision"])})
                con.commit(); return {"ok":True}
            if path == "/api/exits":
                self.require_user(HR_ROLES)
                empid = str(data.get("employee_id", "")).strip()
                if not empid: raise ValueError("Employee is required")
                xid = "EXT-" + uuid.uuid4().hex[:10].upper()
                con.execute("INSERT INTO exit_checklists(exit_id,employee_id,exit_type,notice_start,last_working_day,notes,created_at) VALUES(?,?,?,?,?,?,?)", (xid,empid,str(data.get("exit_type","Resignation")),str(data.get("notice_start","")),str(data.get("last_working_day","")),str(data.get("notes","")),now_iso()))
                audit(con, actor, "CREATE", "ExitChecklist", xid, {"employee_id": empid})
                con.commit(); return {"ok": True, "exit_id": xid}
            if path.startswith("/api/exits/") and path.endswith("/update"):
                self.require_user(HR_ROLES)
                xid = path.split("/")[-2]
                allowed = ["resignation_document","attendance_clearance","leave_clearance","asset_clearance","account_clearance","manager_clearance","hr_clearance","finance_clearance","final_settlement"]
                current = con.execute("SELECT * FROM exit_checklists WHERE exit_id=?", (xid,)).fetchone()
                if not current: raise ValueError("Exit record not found")
                values = {key: 1 if bool(data.get(key, current[key])) else 0 for key in allowed}
                status = "Completed" if all(values.values()) else "In Progress"
                assigns = ",".join(f"{k}=?" for k in allowed)
                con.execute(f"UPDATE exit_checklists SET {assigns},status=?,notes=? WHERE exit_id=?", (*values.values(), status, str(data.get("notes", current["notes"])), xid))
                if status == "Completed":
                    con.execute("UPDATE employees SET employment_status='Inactive',updated_at=? WHERE employee_id=(SELECT employee_id FROM exit_checklists WHERE exit_id=?)", (now_iso(), xid))
                audit(con, actor, "UPDATE", "ExitChecklist", xid, {**values, "status": status})
                con.commit(); return {"ok": True, "status": status}
            if path.startswith("/api/exits/") and path.endswith("/delete"):
                self.require_user(HR_ROLES)
                xid = path.split("/")[-2]
                current = con.execute("SELECT exit_id FROM exit_checklists WHERE exit_id=?", (xid,)).fetchone()
                if not current: raise ValueError("Exit record not found")
                con.execute("UPDATE exit_checklists SET is_archived=1 WHERE exit_id=?", (xid,))
                audit(con, actor, "ARCHIVE", "ExitChecklist", xid)
                con.commit(); return {"ok":True,"archived":True}
            if path == "/api/backup":
                self.require_user({"super_admin"})
                BACKUP_DIR.mkdir(parents=True, exist_ok=True)
                filename = "hrms_backup_" + now_dt().strftime("%Y_%m_%d_%H_%M_%S") + ".zip"
                destination = BACKUP_DIR / filename
                # Snapshot both databases via SQLite's online backup API, verify integrity, then package them.
                with tempfile.TemporaryDirectory() as tmp_dir:
                    snapshots = []
                    for label, opener in (("hrms.db", connect_db), ("payroll_private.db", connect_payroll_db)):
                        source = opener()
                        snapshot_path = Path(tmp_dir) / label
                        backup_con = sqlite3.connect(snapshot_path)
                        try:
                            source.backup(backup_con)
                            check = backup_con.execute("PRAGMA integrity_check").fetchone()[0]
                            if check != "ok": raise RuntimeError(f"Backup integrity verification failed for {label}")
                        finally:
                            backup_con.close(); source.close()
                        snapshots.append(snapshot_path)
                    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                        for snapshot_path in snapshots:
                            archive.write(snapshot_path, arcname=snapshot_path.name)
                audit(con, actor, "CREATE_BACKUP", "DatabaseBackup", filename, {"verified": True, "bytes": destination.stat().st_size, "databases": 2})
                con.commit(); return {"ok": True, "filename": filename, "size": destination.stat().st_size, "download_url": "/api/backup-download/"+filename}
            if path == "/api/settings":
                self.require_user(ADMIN_ROLES)
                allowed_settings = {"company_name","system_name","timezone","currency","work_location","attendance_grace_minutes","standard_working_hours","payroll_day","leave_year_start","policy_note"}
                for key, value in data.items():
                    if key not in allowed_settings: continue
                    if key == "timezone" and str(value) != TZ_NAME: raise ValueError("The application timezone is fixed to Asia/Dhaka")
                    if key == "currency" and str(value).upper() != "BDT": raise ValueError("The application currency is fixed to BDT")
                    if key in {"attendance_grace_minutes","standard_working_hours","payroll_day"} and str(value).strip():
                        numeric = safe_float(value, -1)
                        if numeric < 0: raise ValueError(f"{key.replace('_',' ')} must be zero or a positive number")
                    con.execute("INSERT INTO app_settings(setting_key,setting_value,updated_at,updated_by) VALUES(?,?,?,?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=excluded.updated_at,updated_by=excluded.updated_by", (key, str(value), now_iso(), actor))
                audit(con, actor, "UPDATE", "Settings", "", data)
                con.commit(); return {"ok": True}
            if path.startswith("/api/users/") and path.endswith("/update"):
                self.require_user({"super_admin"})
                user_id = int(path.split("/")[-2])
                existing = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
                if not existing: raise ValueError("User account not found")
                if user_id == user["user_id"] and data.get("is_active") in (False, 0, "0", "false"): raise ValueError("You cannot deactivate your own account")
                username = str(data.get("username", existing["username"])).strip().lower()
                role = str(data.get("role", existing["role"]))
                empid = data.get("employee_id", existing["employee_id"]) or None
                if not username or "@" not in username: raise ValueError("Enter a valid login email")
                if role not in ALL_ROLES: raise ValueError("Invalid role")
                if role in {"employee","manager"} and not empid: raise ValueError("Employee and manager accounts must be linked to an Employee ID")
                if empid and not con.execute("SELECT 1 FROM employees WHERE employee_id=?", (empid,)).fetchone(): raise ValueError("Linked Employee ID does not exist")
                active = 1 if str(data.get("is_active", existing["is_active"])).lower() not in {"0", "false", "off"} else 0
                con.execute("UPDATE users SET username=?,role=?,employee_id=?,is_active=? WHERE id=?", (username, role, empid, active, user_id))
                temp_password = str(data.get("reset_password", ""))
                if temp_password:
                    if len(temp_password) < 12: raise ValueError("Reset password must be at least 12 characters")
                    con.execute("UPDATE users SET password_hash=?,must_change_password=1 WHERE id=?", (hash_password(temp_password), user_id))
                audit(con, actor, "UPDATE", "User", str(user_id), {"username":username,"role":role,"employee_id":empid,"is_active":active,"password_reset":bool(temp_password)})
                con.commit(); invalidate_user_sessions({user_id}); return {"ok": True, "password_reset": bool(temp_password), "relogin_required": True}
            if path.startswith("/api/users/") and path.endswith("/delete"):
                self.require_user({"super_admin"})
                user_id = int(path.split("/")[-2])
                if user_id == user["user_id"]: raise ValueError("You cannot deactivate your own account")
                row = con.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
                if not row: raise ValueError("User account not found")
                con.execute("UPDATE users SET is_active=0 WHERE id=?", (user_id,))
                audit(con, actor, "DEACTIVATE", "User", str(user_id), {"username": row["username"]})
                con.commit(); invalidate_user_sessions({user_id}); return {"ok": True, "deactivated": True}
            if path == "/api/users":
                self.require_user({"super_admin"})
                username = str(data.get("username", "")).strip().lower()
                password = str(data.get("password", ""))
                role = str(data.get("role", "employee"))
                empid = data.get("employee_id") or None
                if not username or "@" not in username: raise ValueError("Enter a valid login email")
                if len(password) < 12: raise ValueError("Temporary password must be at least 12 characters")
                if role not in ALL_ROLES: raise ValueError("Invalid role")
                if role in {"employee","manager"} and not empid: raise ValueError("Employee and manager accounts must be linked to an Employee ID")
                if empid and not con.execute("SELECT 1 FROM employees WHERE employee_id=?", (empid,)).fetchone(): raise ValueError("Linked Employee ID does not exist")
                cur = con.execute("INSERT INTO users(username,password_hash,role,employee_id,created_at,must_change_password) VALUES(?,?,?,?,?,1)", (username,hash_password(password),role,empid,now_iso()))
                audit(con, actor, "CREATE", "User", str(cur.lastrowid), {"username": username, "role": role, "employee_id": empid})
                con.commit(); return {"ok": True, "id": cur.lastrowid}
            raise ValueError("Unknown API endpoint")
        finally:
            con.close()

    def calculate_leave_days(self, con: sqlite3.Connection, start: str, end: str) -> float:
        start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
        holidays = {r[0] for r in con.execute("SELECT holiday_date FROM holidays WHERE is_active=1 AND holiday_date BETWEEN ? AND ?", (start, end)).fetchall()}
        # Weekly offs are counted only when all selected employees' work schedules are not known.
        # Therefore, default calculation excludes configured public holidays only; HR can verify before approval.
        days = 0
        d = start_d
        while d <= end_d:
            if d.isoformat() not in holidays:
                days += 1
            d += timedelta(days=1)
        return float(days)


def main() -> None:
    init_db()
    print("\nLight Retouch Management System is starting")
    if HOST in ("0.0.0.0", "::"):
        print(f"This PC: http://127.0.0.1:{PORT}")
        print(f"Other office PCs: open http://192.168.0.244:{PORT} (replace the IP if this PC's LAN address changes)")
    else:
        print(f"URL: http://{HOST}:{PORT}")
    print("First login: admin@lightretouch.local")
    if not os.environ.get("HRMS_ADMIN_PASSWORD"):
        print("Temporary password: ChangeMeNow!2026 (change it immediately)")
    print(f"Database: {DB_PATH}")
    print("For LAN access set HRMS_HOST=0.0.0.0 and configure a trusted network/firewall. Use HTTPS before public deployment.\n")
    server = ThreadingHTTPServer((HOST, PORT), HRMSHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down HRMS...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
