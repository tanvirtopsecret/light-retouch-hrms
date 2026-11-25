# Light Retouch Management System — LAN Edition (V4)

A standalone, code-based HR and production management web application for Light Retouch. It uses Python's standard library, SQLite, HTML, CSS and JavaScript. It does not use Google Drive, Google Sheets, Google Forms, Apps Script, paid APIs or third-party Python packages.

The intended office setup is one always-on Windows PC running the server and 10–15 office PCs using the same application through the router/LAN.

## 1. Main address and technology

- Main/server PC: `192.168.0.244`
- Other office PCs: `http://192.168.0.244:8000`
- Server runs on `0.0.0.0:8000` (LAN interface)
- Python 3.10+ standard library only; no `pip install` needed
- SQLite main HR database and a separate private payroll database
- Timezone: `Asia/Dhaka`; currency: `BDT (৳)`

## 2. Install or update the office server

### First installation

1. Install Python 3.10 or newer on the PC that will stay powered on. During installation on Windows, enable **Add Python to PATH**.
2. Extract the ZIP to a fixed folder, such as `C:\LightRetouchManagementSystem`.
3. Double-click `start.bat`.
4. On the host PC, open `http://127.0.0.1:8000`.
5. Run `allow_lan_firewall.bat` once using **Run as administrator**.
6. On each other office computer, open `http://192.168.0.244:8000` in Chrome or Edge.
7. Keep the server's black Command Prompt window open while the team uses the system.

### Update from the previous V3 LAN installation without losing records

**Do not overwrite the old installation before making a backup.** This ZIP intentionally excludes live database and uploaded-file data.

1. On the host PC, stop the old server using `Ctrl+C` in its Command Prompt window.
2. Copy the complete old project folder to a separate backup location. At minimum, retain the old `instance` and `uploads` folders.
3. Extract this V4 ZIP to a new folder, for example `C:\LightRetouchManagementSystem_V4`.
4. Copy these old database files into the new V4 `instance` folder:
   - `hrms.db`
   - `payroll_private.db`
5. Copy the old `uploads` folder into the new V4 project folder's `uploads` folder. This preserves employee photos, old documents, and existing branding images.
6. Do **not** copy old `app.py`, `static`, `templates`, or `start.bat` over the new files.
7. Run V4 `start.bat`. Database migrations add the V4 columns while retaining previous employee, attendance, payroll and task records.
8. Sign in using your existing user account/password. Existing login data remains in the database.
9. Verify a few existing employee profiles, documents, salary history and a backup before staff use the new system.

The V3-to-V4 SQLite migration was tested using a copy of the uploaded V3 database. Existing employee, attendance-adjustment, account and salary records remained intact. The time migration created a verified pre-migration backup and did not rewrite payroll history. Still, keep the old project backup until you complete your own verification.

## 3. Fresh installation first login

For a completely new database only:

- Login email: `admin@lightretouch.local`
- Temporary password: `ChangeMeNow!2026`

The initial Super Admin must change the temporary password at first login. When migrating from V3, continue to use the existing login credentials instead of these fresh-install credentials.

## 4. Database and protected files

| Path | Content |
|---|---|
| `instance/hrms.db` | Employees, user accounts, attendance, leave, tasks, recruitment, reviews, assets, employee relations, exits and audit records |
| `instance/payroll_private.db` | Salary history, payroll runs, payroll items and payroll audit records |
| `uploads/` | Protected employee profile photos, employee documents and leave attachments; logo is used for public branding |
| `backups/` | Locally created database backup ZIP files |

The application protects private file URLs using signed-in role checks. However, anyone who has Windows filesystem access to the project folder can potentially copy the SQLite database and uploaded files. Use a protected Windows account on the host PC, restrict folder permissions and keep separate backups. The application should only be used on a trusted private office LAN. Do not open router port forwarding or expose it directly to the public internet.

## 5. Roles and what each role can manage

- **Super Admin:** system settings and branding, user access, employees, all HR modules, production, payroll, backups and audit.
- **HR Admin / HR Executive:** employee records, recruitment, attendance administration, leave, production task management and other HR modules. Payroll access remains restricted to payroll-authorized accounts.
- **Department Manager:** own team's profiles, attendance and leave approval, team performance, team production assignment/submission review and appropriate team documents.
- **Payroll Admin:** payroll and salary records, payslip workflows, employee directory/attendance summaries and own employee self-service information. No general HR administration.
- **Employee:** own profile/contact information/photo, own documents, own attendance details, leave applications, payslips (approved only), and assigned production tasks. Employees can see the company-wide work-hours/overtime summary but cannot see another employee's private leave reason, documents, salary or correction notes.

**User Access:** only the Super Admin can create/edit/reactivate/deactivate login accounts. Assign roles and link employee/manager accounts to a permanent Employee ID. `Delete` in User Access deactivates the login rather than deleting the employee or audit history.

## 6. Employee records and profile

- Add an employee and generate a permanent ID such as `LR-EMP-0001`.
- Reporting Manager is selected from an Employee ID dropdown (`Employee ID · Name`).
- HR can edit an employee's employment records; an employee can update their own name/contact/work location and upload their own profile photo.
- Employee profiles display monthly attendance, duty hours, overtime estimate, late/absence summary and assigned production work.
- Employee profile Documents support upload, replace, download and delete according to role permissions. Employees manage their own documents; HR can manage employee documents; reporting managers can manage documents only for their own reporting team.
- Archiving an employee marks the record Inactive and disables the associated login. Employee IDs are never reused.

## 7. Attendance, duty hours and overtime

Attendance check-in/check-out timestamps are generated by the server in `Asia/Dhaka`. Employees see their own raw attendance events; authorized HR and reporting managers see the appropriate HR/team records.

All signed-in users can view the office-wide monthly attendance summary, including:

- Present days
- Late days and late minutes (when grace rules are configured)
- Absent days for past scheduled working days
- Total completed duty hours
- Overtime hours above the employee's configured shift duration
- Missing check-out count and whether shift rules are configured

Daily duty hours are calculated from check-in to check-out less the assigned shift break. Overtime is the time above the configured shift's expected duration. It is an informational calculation, not automatic overtime pay. Assign the correct shift, start/end time, break, grace period, weekly off days and holidays before relying on reports. Employees with incomplete punches are shown separately; current incomplete workdays are not falsely counted absent.

## V4 time handling, attendance sync and live dashboard

- Every manually entered shift or attendance-correction time uses explicit Hour, Minute and AM/PM selectors. The server stores canonical 24-hour values (for example `03:30 PM` becomes `15:30`) to avoid future AM/PM ambiguity.
- The V4 migration checks only the known named legacy shift patterns and creates a verified SQLite backup before changing them: Morning `07:30–03:30` becomes `07:30–15:30`; Evening `03:30–11:30` becomes `15:30–23:30`; Night `11:30–07:30` becomes `23:30–07:30`. Other/custom shifts are not changed automatically. Matching attendance correction times for employees assigned to those shifts are updated with the shift interpretation; raw server punch events and payroll history are not rewritten.
- My Overview and My Attendance use the same `/api/attendance/punch` endpoint and one event ledger. Both pages display the same server-saved check-in/out state. The server takes an immediate SQLite write lock before checking and inserting a punch, preventing duplicate punches caused by rapid clicks or two tabs. The open dashboard/attendance page refreshes periodically and other tabs synchronize after a punch.
- The dashboard distinguishes **Presence** (clock-in to clock-out), **Break**, **Net Duty** (presence less unpaid break) and **Overtime**. Example: 07:30 AM–03:30 PM is 8 hours of presence; with a 60-minute unpaid break it is 7 net duty hours. Select “Count break as paid duty” only if company policy treats the break as paid. Do not assume the setting without approval.
- All timestamps use `Asia/Dhaka`. Displayed event timestamps use AM/PM.

## 8. Individual salary and attendance-based payroll

Salary data is stored separately in `payroll_private.db`. Each employee can have a different basic salary and fixed allowances with effective dates and preserved salary history. Only Super Admin and Payroll Admin can read/update these salary records.

Payroll preview uses the active/effective monthly salary and attendance:

```text
Payable days = Present days + Approved leave classified as Paid
Attendance factor = min(Payable days / Scheduled working days, 1.0)
Prorated basic = Monthly basic × Attendance factor
Prorated allowances = Monthly fixed allowances × Attendance factor
Gross salary = Prorated basic + Prorated allowances + approved overtime + approved bonus
Net salary = Gross salary - approved deductions - approved adjustments
```

Late is reported but does not automatically deduct salary. No tax, statutory deduction or legal entitlement is invented. Confirm applicable Bangladesh rules and company policy before approving or paying payroll. Every employee needs a correctly assigned shift and leave types must be classified as Paid, Unpaid or To be configured. The payroll preview can be generated before month end, but the system prevents approving the current/open month.

## 9. Photo-editing production management

The Production Tasks module is intended for the studio's real workflow. Common editing types are provided in the assignment dropdown, including Background Removal, Clipping Path, Image Masking, Product Photo Retouching, Jewelry Retouching, Fashion/Model Retouching, Ghost Mannequin, Color Correction and AI-assisted edits.

Each job can include project/client, title, editing type, priority, image quantity, deadline, source link and instructions.

- **All:** assign a separate task assignment to every active/probation employee (or the Manager's team for Manager role).
- **Selected:** assign to chosen Employee IDs.
- Every employee has an independent status, completed image count, output link and submission note even when everyone receives the same brief.
- Employees can see their own assigned jobs, start work and submit the result.
- HR can manage all assignments. A Manager can manage/review only their own reporting team's assignments.
- Dashboard and individual employee profiles display relevant production assignments and progress.
- Task deletion archives the job and preserves its assignment history.

## 10. Recruitment and demo master data

Recruitment Position is a dropdown populated from **Settings → Recruitment positions**. Candidate records support add, edit, stage update and archive.

For convenience, a new database includes clearly labelled demo master data for Departments, Designations, a General Shift and Recruitment Positions. These demo entries can be edited or archived in Settings. The demo General Shift is 09:00–18:00, one-hour break, 10-minute grace and Friday weekly off. **This is sample data only—not a confirmed Light Retouch company policy.** Replace it with approved working rules before live payroll or attendance decisions.

Leave types are also seeded, but entitlement and paid/unpaid classifications remain `To be configured`. The system does not seed fictional employee identities or fake salary figures.

## 11. Branding and settings

Open **System Settings** with a Super Admin or HR Admin account to change:

- Application/system name
- Company name
- Company logo (PNG/JPG/WEBP, maximum 2 MB)
- Department and designation lists
- Shifts, breaks, grace periods and weekly offs
- Recruitment position list
- Leave types and classifications
- Company holiday list

System timezone remains `Asia/Dhaka` and currency remains `BDT`.

## 12. CRUD and archive behaviour

The main record modules provide add/edit/update/delete or archive controls according to role. To protect history and preserve employee/payroll/audit references, Delete is usually a soft archive/deactivation rather than permanent database destruction. Documents can be replaced or deleted. User Access Delete deactivates sign-in. Employee Delete archives the employee and disables their login. Back up before bulk changes.

## 13. Backups and troubleshooting

- Super Admin can create a local backup from Settings. The backup contains SQLite snapshots of both databases and is integrity-checked before it is reported successful.
- Keep another copy of the backup on a separate protected drive; a backup on the same PC is not protection against disk failure.
- If another PC cannot connect, confirm the server window is open, all PCs are on the same non-guest network, Windows is set to Private network, the firewall rule is active, and the router has AP/Client Isolation disabled.
- Confirm the host PC still uses `192.168.0.244`. Configure DHCP reservation in the router to keep this address stable.
- If port 8000 is busy, close the other server using that port or update the HRMS port in `start.bat` and firewall rule consistently.
- Do not expose the development server to the internet. For remote access, arrange a properly secured VPN/reverse proxy/HTTPS deployment with an administrator.

## 14. Verification performed for V4

The following backend workflows were exercised against temporary test databases, not the company's records:

- Demo master seeding and public branding
- Employee create/update and reporting manager links
- User account update, deactivate and reactivate
- Employee profile self-update and photo upload
- Employee document upload/list/download and reporting-manager permissions
- Leave attachment upload and access for employee/authorized manager
- Production task assign All / Selected, employee isolation, submit, review, update and archive
- Attendance duty hours, overtime, late minutes and office-wide summary
- Candidate, asset, performance, disciplinary, exit, leave-type and holiday CRUD/archive
- V3 database migration while preserving employee, attendance, account and payroll records
- AM/PM parser tests for 07:30 AM, 03:30 PM, 12:00 AM and 12:00 PM
- Legacy Morning/Evening/Night shift interpretation migration and SQLite backup integrity
- Attendance state shared between Overview and Attendance pages; duplicate punch protection
- Frontend JavaScript and Python syntax checks

The application has not been deployed to the office PC or publicly hosted by this package operation. After installing V4, the administrator should complete an in-office user acceptance test using test/dummy employee accounts before using the application for live HR or payroll decisions.


## Your previous data

This personalized package includes the HRMS database, payroll database, existing user accounts, employee record, settings, and original company logo from the V3 ZIP you uploaded. Use your existing V3 usernames and passwords. Read `UPDATE_GUIDE.md` before starting.
=======
# light-retouch-hrms
Light Retouch Human Resource Management System
