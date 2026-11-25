# V4.1 Focused Fix — Leave Review & Duration Display

## Changes
- Added a **View details** action to each leave request.
- The details view displays employee, leave type, start/end dates, requested days, full leave reason, attachment availability, manager decision/comments, HR decision/comments, and submission timestamp.
- Leave attachment metadata is retrieved from the existing private-file record. Authorized users can open/download the original file; supported image and PDF files are previewed in the details view.
- Kept existing role-based private-file authorization in place.
- Replaced decimal-hour display (for example, `7.80 h`) with readable hour/minute output (for example, `7h 48m`). All UI locations using the shared duration formatter now use this display.
- Examples: 60 minutes = `1h`; 90 minutes = `1h 30m`; 7.50 hours = `7h 30m`.

## Data preservation verification
- `instance/hrms.db` was not modified.
- `instance/payroll_private.db` was not modified.
- SHA-256 hashes of both database files match the files in the uploaded V4 archive.
- SQLite `PRAGMA integrity_check` returned `ok` for both databases.
- Existing uploads, backups, branding assets, and application structure were retained.

## Scope
This is a focused application/UI fix only. It does not migrate, delete, reset, or recalculate any employee, attendance, leave, payroll, or production records.
