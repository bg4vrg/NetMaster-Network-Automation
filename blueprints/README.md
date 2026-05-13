NetMaster blueprint split plan
==============================

This directory marks the start of splitting the large `app.py` into focused Flask blueprints.

Target modules:

- `assets`: switch assets, asset import/export, legacy asset migration.
- `access`: port binding, ACL, Excel batch deployment, terminal binding state.
- `roaming`: terminal lookup and migration workflows.
- `alarms`: switch log collection, alarm dashboard and alarm state.
- `backup`: config backup, data packages, config diff.
- `system`: settings, task center, audit logs and user management.

Current status:

- Permission decorators have been introduced in `app.py`.
- `audit_task.py` now owns audit log and task center routes.
- `alarm_read.py` now owns alarm reports and alarm dashboard read-only routes.
- `alarm_manage.py` now owns alarm log collection trigger, alarm collection background task start and alarm state update write routes.
- `backup_read.py` now owns backup file listing and local config diff read-only routes.
- `backup_manage.py` now owns data package import/export, legacy asset import, offline binding import, manual batch backup routes and batch-backup background task start.
- `info_read.py` now owns version info, dashboard stats, health check and settings read routes.
- `asset_user_read.py` now owns switch list, switch import template and user list read routes.
- `asset_manage.py` now owns switch asset export, import preview/import, add, delete, update and metadata update routes.
- `system_manage.py` now owns settings write route.
- `user_manage.py` now owns user add, update and reset password write routes.
- `switch_connect.py` now owns connection test, interface list, port detail and save config routes.
- `access_manage.py` now owns interface description, port binding/unbinding and ACL query/add/delete routes.
- `roam_manage.py` now owns terminal lookup and terminal migration routes.
- `excel_manage.py` now owns Excel binding template, Excel parsing, grouped deployment and row deployment routes.
- `terminal_state.py` now owns terminal binding sync trigger, sync status and bound terminal list routes.
- `terminal_state.py` sync trigger now submits work to the shared `background_tasks` queue.
- `profile_health.py` now owns port profiles, profile risk suggestions, deep online health check routes and health-check background task start.
- `user_manage.py` also owns current-user password change.
- `task_runtime.py` now exposes runtime background task list and detail routes.
- `background_tasks.py` now persists runtime task state to the SQLite `runtime_tasks` table, so task history survives service restarts.
- `port_snapshot.py` now owns port snapshot listing and background collection trigger routes.
- `snmp_status.py` now owns lightweight SNMP port status routes.
- `snmp_status.py` also exposes SNMP-first interface listing for the port binding page, with SSH fallback handled by the frontend.
- `auth_pages.py` now owns login and logout page routes.
- `scheduler_service.py` now owns scheduled backup, terminal sync, data export, alarm collection and APScheduler wiring.
- `validators.py` now owns shared IP, port, VLAN, vendor, role, MAC, mode, ACL and password policy validators.
- `xlsx_utils.py` now owns shared xlsx workbook download and worksheet autosize helpers.
- Next migration can continue extracting shared runtime helpers from `app.py`.
