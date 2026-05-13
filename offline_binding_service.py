import re

from validators import normalize_ip, normalize_mac


def parse_bindings_from_config(config_text, switch_ip):
    bindings = []
    current_iface = ''
    current_vlan = '1'
    current_mode = 'trunk'
    for raw_line in str(config_text or '').splitlines():
        line = raw_line.strip()
        if line.startswith('interface '):
            full_name = line.split(' ', 1)[1].strip()
            current_iface = full_name.replace('Ten-GigabitEthernet', 'XGE')\
                                     .replace('XGigabitEthernet', 'XGE')\
                                     .replace('M-GigabitEthernet', 'MGE')\
                                     .replace('GigabitEthernet', 'GE')\
                                     .replace('Bridge-Aggregation', 'BAGG')\
                                     .replace('Ethernet', 'Eth')
            current_vlan = '1'
            current_mode = 'trunk'
            continue
        if not current_iface:
            continue
        if line.startswith(('port access vlan', 'port default vlan')):
            parts = line.split()
            if parts:
                current_vlan = parts[-1]
        elif line.startswith('port trunk pvid vlan'):
            parts = line.split()
            if parts:
                current_vlan = parts[-1]
        elif 'ip verify source' in line or 'source check user-bind enable' in line:
            current_mode = 'access'
        if ('ip source binding' in line or 'user-bind static' in line) and 'ip-address' in line:
            ip_match = re.search(r'ip-address\s+([\d.]+)', line)
            mac_match = re.search(r'mac-address\s+([0-9a-fA-F:.\-]+)', line)
            vlan_match = re.search(r'\bvlan\s+(\d+)', line)
            if ip_match and mac_match:
                bindings.append({
                    'switch_ip': switch_ip,
                    'switch_port': current_iface,
                    'ip': ip_match.group(1),
                    'mac': mac_match.group(1),
                    'vlan': vlan_match.group(1) if vlan_match else current_vlan,
                    'mode': current_mode if not vlan_match else 'trunk',
                })
    return bindings


def import_bindings_from_backup_files(
    list_backup_config_files,
    read_backup_text,
    save_binding_state,
    limit=2000,
    apply=False,
):
    files = list_backup_config_files(limit=limit)
    found = 0
    unique_map = {}
    duplicate_count = 0
    created = 0
    updated = 0
    unchanged = 0
    errors = []
    for item in files:
        switch_ip = item.get('device_ip') or ''
        try:
            normalize_ip(switch_ip, '备份文件交换机 IP')
        except ValueError:
            continue
        try:
            lines = read_backup_text(item['path'])
            bindings = parse_bindings_from_config('\n'.join(lines), switch_ip)
            found += len(bindings)
            for binding in bindings:
                key = (normalize_mac(binding['mac']).lower(), binding['ip'])
                if key in unique_map:
                    duplicate_count += 1
                    old = unique_map[key]
                    if item.get('date', '') >= old.get('backup_date', ''):
                        unique_map[key] = {**binding, 'backup_file': item['path'], 'backup_date': item.get('date', '')}
                else:
                    unique_map[key] = {**binding, 'backup_file': item['path'], 'backup_date': item.get('date', '')}
        except Exception as exc:
            errors.append(f"{item.get('path')}: {exc}")
    if apply:
        for binding in unique_map.values():
            action = save_binding_state(
                binding['switch_ip'],
                binding['switch_port'],
                binding['vlan'],
                binding['ip'],
                binding['mac'],
                binding['mode'],
            )
            if action == 'created':
                created += 1
            elif action == 'updated':
                updated += 1
            else:
                unchanged += 1
    preview = list(unique_map.values())[:200]
    return {
        'files': len(files),
        'found': found,
        'unique_terminals': len(unique_map),
        'duplicates': duplicate_count,
        'created': created,
        'updated': updated,
        'unchanged': unchanged,
        'errors': errors[:20],
        'preview': preview,
    }
