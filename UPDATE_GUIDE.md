# Light Retouch Management System V4 — Data-Preserved Update

## This package already contains your previous data
The V3 database and private payroll database from the ZIP you uploaded are already included. You do **not** need to manually copy the old database into this package.

## Safe installation
1. On the main PC (`192.168.0.244`), stop the currently running HRMS with `Ctrl+C`.
2. Make one more backup of the current live project's `instance` and `uploads` folders before changing anything.
3. Extract this ZIP into a **new folder**. Do not extract over the old project.
4. Confirm that the new folder contains `instance/hrms.db`, `instance/payroll_private.db`, and `uploads/branding/company_logo.png`.
5. Run `start.bat` in the new folder.
6. Open `http://127.0.0.1:8000` on the main PC and verify the Super Admin login, employee profile, settings, attendance, salary records, payroll and logo.
7. From another office PC, open `http://192.168.0.244:8000`.
8. Keep the old project folder and the included backups until you have verified every record.

## Accounts and passwords
Your existing user accounts and password hashes are retained from the uploaded V3 database. Use the same login credentials you used in V3. The previous temporary default password is not automatically reset.

## What this build preserves
- Employee and user accounts
- Attendance corrections and raw attendance event
- Leave applications
- Existing production task and assignment
- Salary history and payroll run/items
- Existing app settings, company branding and original logo
- Existing master records

## Attendance time correction
The uploaded V3 database contained ambiguous legacy time values. The migration interprets the configured shifts by their names, stores canonical 24-hour values, and preserves the original raw attendance event. Review daily attendance totals after first login. Payroll history is not recalculated automatically.

## Rollback
Stop V4. Restore the backed-up `instance` and `uploads` folders to the previous project, or use the pre-upgrade SQLite files under `backups/`. Never overwrite your only database copy.
