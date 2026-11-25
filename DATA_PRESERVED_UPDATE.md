# Data-Preserved V4 Update Package

This V4 package includes the HRMS and payroll databases from the V3 ZIP uploaded by the user on 24 November 2026, along with the existing Light Retouch company logo.

## Preserved records
- 1 employee record
- 2 user accounts (Super Admin and linked Employee account)
- 18 attendance correction records
- 1 raw attendance event
- 2 leave applications
- 1 production task and its existing assignment
- 2 salary records
- 1 payroll run and 1 payroll item
- Existing company configuration, timezone, currency, work location, grace period, standard working hours, and branding logo

## Update applied
- V4 schema migration applied to the user's database copy.
- Legacy Morning Shift 07:30–03:30 interpreted as 07:30–15:30 (03:30 PM).
- Evening and Night shift legacy values interpreted using their shift names.
- 17 relevant attendance adjustment times corrected without deleting the original records.
- Raw attendance event preserved.
- Payroll history not recalculated or overwritten.
- System display name changed from the previous value to the user-requested "Light Retouch Management System".
- Demo department/designation/shift/position master entries from V4 added; existing master records were not deleted.

## Backups included
- `backups/hrms_before_v4_upgrade.sqlite3`
- `backups/payroll_before_v4_upgrade.sqlite3`
- `backups/hrms_before_explicit_am_pm_migration_*.sqlite3`

## Important
This package contains the data present in the V3 ZIP uploaded on 24 November 2026. If the live office PC has received new changes after that ZIP was created, back up and compare the live `instance` and `uploads` folders before replacing anything.
