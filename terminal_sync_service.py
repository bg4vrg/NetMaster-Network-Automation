import datetime
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from validators import normalize_ip, normalize_mac, normalize_mode


class MacSyncStateStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.state = {
            'running': False,
            'status': 'idle',
            'message': '尚未执行同步',
            'started_at': '',
            'finished_at': '',
            'actor': '',
            'current_switch_index': 0,
            'total_switches': 0,
            'current_switch_ip': '',
            'current_switch_name': '',
            'synced': 0,
            'found': 0,
            'created': 0,
            'updated': 0,
            'unchanged': 0,
            'errors': [],
        }

    def update(self, **kwargs):
        with self.state_lock:
            self.state.update(kwargs)
            return dict(self.state)

    def snapshot(self):
        with self.state_lock:
            state = dict(self.state)
            state['errors'] = list(self.state.get('errors', []))[-20:]
            return state


def binding_matches_query(binding, query_type, value):
    if query_type == 'ip':
        return binding.get('ip_address') == value
    return normalize_mac(binding.get('mac_address', '')) == value


def persist_switch_bindings(switch_row, all_bindings, save_binding_state, query_type=None, query_value=None):
    changed = 0
    found = 0
    created = 0
    updated = 0
    unchanged = 0
    matched = None
    errors = []

    for binding in all_bindings or []:
        try:
            interface_name = binding.get('switch_port') or binding.get('port')
            bind_ip = binding.get('ip')
            mac = binding.get('mac')
            if not interface_name or not bind_ip or not mac or bind_ip == 'Unknown' or mac == 'Unknown':
                continue
            mode = normalize_mode(binding.get('mode', 'access'))
            vlan = str(binding.get('vlan') or '').strip()
            action = save_binding_state(switch_row['ip'], interface_name, vlan, bind_ip, mac, mode)
            found += 1
            if action == 'created':
                created += 1
                changed += 1
            elif action == 'updated':
                updated += 1
                changed += 1
            else:
                unchanged += 1
            saved = {
                'mac_address': normalize_mac(mac),
                'ip_address': normalize_ip(bind_ip, '绑定 IP'),
                'switch_ip': switch_row['ip'],
                'port': interface_name,
                'vlan': vlan,
                'mode': mode,
            }
            if query_type and binding_matches_query(saved, query_type, query_value):
                matched = saved
        except Exception as exc:
            errors.append(f"binding: {exc}")

    return {
        'synced': changed,
        'found': found,
        'created': created,
        'updated': updated,
        'unchanged': unchanged,
        'matched': matched,
        'errors': errors,
    }


def sync_switch_bindings(switch_row, get_manager, persist_switch_bindings_func, query_type=None, query_value=None):
    runtime = {
        'ip': switch_row['ip'],
        'user': switch_row['username'],
        'pass': switch_row['password'],
        'port': switch_row.get('port', 22),
        'vendor': switch_row.get('vendor', 'h3c'),
    }
    mgr = get_manager(runtime)
    return persist_switch_bindings_func(
        switch_row,
        mgr.get_all_bindings(),
        query_type,
        query_value,
    )


def sync_switch_bindings_with_timeout(
    sw,
    read_switch_bindings_func,
    persist_switch_bindings_func,
    query_type=None,
    query_value=None,
):
    read_result = read_switch_bindings_func(sw)
    if read_result.get('errors'):
        return {'synced': 0, 'matched': None, 'errors': read_result['errors']}
    return persist_switch_bindings_func(sw, read_result.get('bindings') or [], query_type, query_value)


def sync_all_switch_bindings(db, sync_switch_bindings_with_timeout_func, query_type=None, query_value=None):
    total_synced = 0
    scanned_switches = 0
    matched = None
    errors = []

    for sw in db.get_terminal_sync_switches():
        scanned_switches += 1
        try:
            result = sync_switch_bindings_with_timeout_func(sw, query_type, query_value)
            total_synced += result['synced']
            errors.extend([f"{sw['ip']} {err}" for err in result['errors'][:5]])
            if result['matched'] and not matched:
                matched = result['matched']
                break
        except Exception as exc:
            errors.append(f"{sw.get('ip', 'Unknown')}: {exc}")

    return {
        'scanned_switches': scanned_switches,
        'synced': total_synced,
        'matched': matched,
        'errors': errors,
    }


def scan_one_switch_for_terminal(
    db,
    source_switch_ip,
    query,
    normalize_ip_func,
    normalize_terminal_lookup_func,
    sync_switch_bindings_with_timeout_func,
):
    source_switch_ip = normalize_ip_func(source_switch_ip, '源交换机 IP')
    sw = db.get_switch_by_ip(source_switch_ip)
    if not sw:
        raise ValueError(f"资产管理库未登记该源交换机 IP（{source_switch_ip}）")
    query_type, query_value = normalize_terminal_lookup_func(query)
    result = sync_switch_bindings_with_timeout_func(sw, query_type, query_value)
    return {
        'scanned_switches': 1,
        'synced': result['synced'],
        'matched': result['matched'],
        'errors': [f"{source_switch_ip} {err}" for err in result.get('errors', [])],
    }


def log_mac_sync_switch_result(db, actor, client_ip, sw, result=None, error=None):
    switch_ip = sw.get('ip', 'Unknown')
    switch_name = sw.get('name') or switch_ip
    vendor = sw.get('vendor') or 'unknown'
    if error:
        db.log_operation(
            actor,
            client_ip,
            switch_ip,
            "终端更新（单台设备）",
            f"{switch_name} | 厂商:{vendor} | 失败原因:{error}",
            "失败",
        )
        return

    errors = result.get('errors') or []
    found = int(result.get('found') or 0)
    created = int(result.get('created') or 0)
    updated = int(result.get('updated') or 0)
    unchanged = int(result.get('unchanged') or 0)
    if errors:
        db.log_operation(
            actor,
            client_ip,
            switch_ip,
            "终端更新（单台设备）",
            f"{switch_name} | 厂商:{vendor} | 发现:{found} | 新增:{created} | 更新:{updated} | 未变:{unchanged} | 失败原因:{'; '.join(errors[:3])}",
            "失败",
        )
        return

    status = "成功" if found else "无绑定"
    db.log_operation(
        actor,
        client_ip,
        switch_ip,
        "终端更新（单台设备）",
        f"{switch_name} | 厂商:{vendor} | 发现:{found} | 新增:{created} | 更新:{updated} | 未变:{unchanged}",
        status,
    )


def run_mac_bindings_sync(
    actor,
    client_ip,
    switch_ip,
    lock,
    state_store,
    db,
    normalize_ip_func,
    sync_switch_bindings_with_timeout_func,
    read_switch_bindings_with_timeout_func,
    persist_switch_bindings_func,
    log_mac_sync_switch_result_func,
    get_mac_sync_max_workers_func,
):
    if not lock.acquire(blocking=False):
        return {
            'status': 'busy',
            'msg': '终端绑定信息正在同步中，请稍后再试。',
            'data': {'scanned_switches': 0, 'synced': 0, 'errors': []},
        }

    try:
        started_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        state_store.update(
            running=True,
            status='running',
            message='正在同步终端绑定信息',
            started_at=started_at,
            finished_at='',
            actor=actor,
            current_switch_index=0,
            total_switches=0,
            current_switch_ip='',
            current_switch_name='',
            synced=0,
            found=0,
            created=0,
            updated=0,
            unchanged=0,
            errors=[],
        )

        all_errors = []
        total_synced = 0
        total_found = 0
        total_created = 0
        total_updated = 0
        total_unchanged = 0

        if switch_ip:
            switch_ip = normalize_ip_func(switch_ip, '交换机 IP')
            sw = db.get_switch_by_ip(switch_ip)
            if not sw:
                raise ValueError(f"资产管理库未登记该 IP（{switch_ip}）")
            state_store.update(
                current_switch_index=1,
                total_switches=1,
                current_switch_ip=sw['ip'],
                current_switch_name=sw.get('name', ''),
                message=f"正在扫描 {sw.get('name') or sw['ip']} ({sw['ip']})",
            )
            result = sync_switch_bindings_with_timeout_func(sw)
            log_mac_sync_switch_result_func(actor, client_ip, sw, result=result)
            total_synced += result['synced']
            total_found += result.get('found', 0)
            total_created += result.get('created', 0)
            total_updated += result.get('updated', 0)
            total_unchanged += result.get('unchanged', 0)
            all_errors.extend([f"{sw['ip']} {err}" for err in result['errors'][:5]])
            scanned_switches = 1
            device_scope = switch_ip
            state_store.update(
                synced=total_synced,
                found=total_found,
                created=total_created,
                updated=total_updated,
                unchanged=total_unchanged,
                errors=all_errors,
            )
        else:
            device_scope = 'ALL_SWITCHES'
            switches = db.get_terminal_sync_switches()
            scanned_switches = 0
            max_workers = get_mac_sync_max_workers_func()
            state_store.update(
                total_switches=len(switches),
                message=f"正在并发扫描终端绑定信息，最大并发 {max_workers} 台",
            )
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(read_switch_bindings_with_timeout_func, sw): sw
                    for sw in switches
                }
                for future in as_completed(future_map):
                    sw = future_map[future]
                    scanned_switches += 1
                    state_store.update(
                        current_switch_index=scanned_switches,
                        total_switches=len(switches),
                        current_switch_ip=sw.get('ip', ''),
                        current_switch_name=sw.get('name', ''),
                        synced=total_synced,
                        found=total_found,
                        created=total_created,
                        updated=total_updated,
                        unchanged=total_unchanged,
                        errors=all_errors,
                        message=f"已完成 {scanned_switches}/{len(switches)} 台，正在汇总 {sw.get('name') or sw.get('ip')} ({sw.get('ip')})",
                    )
                    try:
                        read_result = future.result()
                        if read_result.get('errors'):
                            result = {
                                'synced': 0,
                                'found': 0,
                                'created': 0,
                                'updated': 0,
                                'unchanged': 0,
                                'matched': None,
                                'errors': read_result['errors'],
                            }
                        else:
                            result = persist_switch_bindings_func(sw, read_result.get('bindings') or [])
                        log_mac_sync_switch_result_func(actor, client_ip, sw, result=result)
                        total_synced += result['synced']
                        total_found += result.get('found', 0)
                        total_created += result.get('created', 0)
                        total_updated += result.get('updated', 0)
                        total_unchanged += result.get('unchanged', 0)
                        all_errors.extend([f"{sw['ip']} {err}" for err in result['errors'][:5]])
                    except Exception as exc:
                        log_mac_sync_switch_result_func(actor, client_ip, sw, error=str(exc))
                        all_errors.append(f"{sw.get('ip', 'Unknown')}: {exc}")
                    state_store.update(
                        synced=total_synced,
                        found=total_found,
                        created=total_created,
                        updated=total_updated,
                        unchanged=total_unchanged,
                        errors=all_errors,
                    )

        status = "成功" if not all_errors else "部分失败"
        db.log_operation(
            actor,
            client_ip,
            device_scope,
            "终端更新（汇总）",
            (
                f"扫描交换机:{scanned_switches} | 发现绑定:{total_found} | "
                f"新增:{total_created} | 更新:{total_updated} | 未变:{total_unchanged} | 错误:{len(all_errors)}"
            ),
            status,
        )
        finished_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        state_store.update(
            running=False,
            status='success' if not all_errors else 'partial',
            message=(
                f"同步完成：扫描 {scanned_switches} 台交换机，发现 {total_found} 条绑定，"
                f"新增 {total_created} 条，更新 {total_updated} 条，未变 {total_unchanged} 条。"
            ),
            finished_at=finished_at,
            current_switch_index=scanned_switches,
            synced=total_synced,
            found=total_found,
            created=total_created,
            updated=total_updated,
            unchanged=total_unchanged,
            errors=all_errors,
        )
        return {
            'status': 'success',
            'msg': (
                f"同步完成：扫描 {scanned_switches} 台交换机，发现 {total_found} 条绑定，"
                f"新增 {total_created} 条，更新 {total_updated} 条，未变 {total_unchanged} 条。"
            ),
            'data': {
                'scanned_switches': scanned_switches,
                'synced': total_synced,
                'found': total_found,
                'created': total_created,
                'updated': total_updated,
                'unchanged': total_unchanged,
                'errors': all_errors[:20],
            },
        }
    except Exception as exc:
        finished_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        state_store.update(
            running=False,
            status='error',
            message=f"同步失败：{exc}",
            finished_at=finished_at,
        )
        raise
    finally:
        lock.release()


def read_switch_bindings_with_timeout(sw, timeout):
    worker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mac_sync_worker.py')
    payload = {
        'switch': {
            'ip': sw.get('ip'),
            'username': sw.get('username') or '',
            'password': sw.get('password') or '',
            'port': sw.get('port') or 22,
            'vendor': sw.get('vendor') or 'h3c',
        }
    }
    try:
        completed = subprocess.run(
            [sys.executable, worker_path],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
    except subprocess.TimeoutExpired:
        return {
            'bindings': [],
            'errors': [f"设备扫描超过 {timeout} 秒，已终止子进程并跳过"],
        }

    stdout_lines = [line.strip() for line in (completed.stdout or '').splitlines() if line.strip()]
    data = None
    if stdout_lines:
        try:
            data = json.loads(stdout_lines[-1])
        except json.JSONDecodeError:
            data = None

    if completed.returncode != 0 or not data:
        detail = ''
        if data and data.get('error'):
            detail = data['error']
        else:
            detail = (completed.stderr or completed.stdout or '子进程无有效输出').strip()
        return {'bindings': [], 'errors': [detail[:500]]}

    if data.get('status') != 'success':
        return {'bindings': [], 'errors': [str(data.get('error') or '设备读取失败')]}

    return {'bindings': data.get('bindings') or [], 'errors': []}
