import re
import time
from netmiko import ConnectHandler

SSH_CONN_TIMEOUT = 12
SSH_COMMAND_TIMEOUT = 25
SSH_LONG_COMMAND_TIMEOUT = 60

class H3CManager:
    def __init__(self, ip, username, password, port=22):
        self.device_info = {
            'device_type': 'hp_comware',
            'ip': ip,
            'username': username,
            'password': password,
            'port': port,
            'global_delay_factor': 2, # 澧炲姞寤舵椂闃叉瓒呮椂
            'conn_timeout': SSH_CONN_TIMEOUT,
            'auth_timeout': SSH_CONN_TIMEOUT,
            'banner_timeout': SSH_CONN_TIMEOUT,
            'blocking_timeout': SSH_COMMAND_TIMEOUT,
            'session_timeout': SSH_COMMAND_TIMEOUT,
        }

    def _get_connection(self):
        return ConnectHandler(**self.device_info)

    def _ensure_command_success(self, output):
        text = str(output or "")
        markers = [
            "Error:",
            "Wrong parameter found",
            "Unrecognized command found",
            "Incomplete command found",
            "Too many parameters found",
        ]
        if any(marker in text for marker in markers):
            raise RuntimeError(text.strip())
        return output
    
    def format_mac(self, mac):
        if not mac: return ""
        clean_mac = mac.replace(":", "").replace("-", "").replace(".", "").lower()
        if len(clean_mac) != 12: return mac 
        return f"{clean_mac[0:4]}-{clean_mac[4:8]}-{clean_mac[8:12]}"

    def get_device_info(self):
        conn = self._get_connection()
        prompt = conn.find_prompt()
        hostname = prompt.replace('<', '').replace('>', '').replace('[', '').replace(']', '').strip()
        version_out = conn.send_command("display version")
        conn.disconnect()
        
        model = "Unknown Model"
        for line in version_out.split('\n'):
            if "uptime is" in line:
                model = line.split("uptime is")[0].strip()
                break
        
        if model == "Unknown Model":
            for line in version_out.split('\n'):
                if "H3C" in line and "Software" not in line:
                    model = line.strip()
                    break
                    
        return f"连接成功\n设备名称: {hostname}\n设备型号: {model}"

    def get_alarm_logs(self):
        conn = self._get_connection()
        try:
            output = conn.send_command("display logbuffer", read_timeout=SSH_LONG_COMMAND_TIMEOUT)
        finally:
            conn.disconnect()
        return output

# === 馃洜锔?缁堟瀬淇鐗堬細鑾峰彇鎺ュ彛鍒楄〃 (瑙ｅ喅 XGE 鎻忚堪涓㈠け闂) ===
    def get_interface_list(self):
        conn = self._get_connection()
        brief_out = conn.send_command("display interface brief")
        config_out = conn.send_command("display current-configuration interface")
        conn.disconnect()

        interfaces = []
        
        # 1. 瑙ｆ瀽 brief 鑾峰彇鎺ュ彛鍚嶃€佺姸鎬?(UP/DOWN)銆佹ā寮?(Access/Trunk)
        for line in brief_out.split('\n'):
            parts = line.split()
            if len(parts) >= 5:
                name = parts[0]
                if name.startswith(('GE', 'XGE', 'Gigabit', 'MGE', 'Bridge', 'Ten-Gigabit', 'XGigabit')):
                    # 馃敟 淇锛氬厛鏇挎崲闀跨殑 (Ten-GigabitEthernet)锛屽啀鏇挎崲鐭殑 (GigabitEthernet)
                    short_name = name.replace('Ten-GigabitEthernet', 'XGE')\
                                     .replace('XGigabitEthernet', 'XGE')\
                                     .replace('M-GigabitEthernet', 'MGE')\
                                     .replace('GigabitEthernet', 'GE')\
                                     .replace('Bridge-Aggregation', 'BAGG')
                    
                    link_status = parts[1] 
                    port_type_raw = parts[4] 
                    port_type = "Access" if port_type_raw == 'A' else "Trunk" if port_type_raw == 'T' else "Hybrid" if port_type_raw == 'H' else port_type_raw
                    
                    interfaces.append({
                        'name': short_name, 
                        'desc': '', 
                        'link': link_status, 
                        'type': port_type
                    })
        
        # 2. 瑙ｆ瀽 config 鑾峰彇 description
        current_iface = None
        for line in config_out.split('\n'):
            line = line.strip()
            if line.startswith('interface '):
                full_name = line.split(' ')[1]
                # 馃敟 淇锛氫繚鎸佹纭殑鏇挎崲椤哄簭
                current_iface = full_name.replace('Ten-GigabitEthernet', 'XGE')\
                                         .replace('XGigabitEthernet', 'XGE')\
                                         .replace('M-GigabitEthernet', 'MGE')\
                                         .replace('GigabitEthernet', 'GE')\
                                         .replace('Bridge-Aggregation', 'BAGG')
            elif line.startswith('description ') and current_iface:
                desc_text = line.replace('description ', '').strip()
                for iface in interfaces:
                    if iface['name'] == current_iface:
                        iface['desc'] = desc_text
                        break
        
        # 3. 鏍煎紡鍖栬緭鍑?
        result = []
        for iface in interfaces:
            display_text = f"[{iface['link']}] [{iface['type']}] {iface['name']}"
            if iface['desc']:
                display_text += f" ({iface['desc']})"
            result.append({'value': iface['name'], 'text': display_text})
            
        return result

    def get_port_info(self, interface_name):
        conn = self._get_connection()
        try:
            output_iface = conn.send_command(
                f"display current-configuration interface {interface_name}",
                read_timeout=SSH_COMMAND_TIMEOUT,
            )
            output_global = conn.send_command(
                "display ip source binding",
                read_timeout=SSH_COMMAND_TIMEOUT,
            )
        finally:
            conn.disconnect()

        vlan = ""
        description = ""
        bindings = []
        
        # 馃敟 鏍稿績淇锛氶鎵弿鎺ュ彛鐗瑰緛銆傚鏋滃瓨鍦?ip verify source锛岃瘉鏄庤繖鏄?Access 涓ユ牸妯″紡
        is_strict_access = 'ip verify source' in output_iface

        # 1. 瑙ｆ瀽鎺ュ彛閰嶇疆
        for line in output_iface.split('\n'):
            line = line.strip()
            
            # 鑾峰彇绔彛鐨勯粯璁?VLAN / PVID
            if line.startswith('port access vlan'):
                parts = line.split()
                if len(parts) >= 4: vlan = parts[3]
            elif line.startswith('port trunk pvid vlan'):
                parts = line.split()
                if len(parts) >= 5: vlan = parts[4]
                
            elif line.startswith('description'):
                parts = line.split(maxsplit=1)
                if len(parts) > 1: description = parts[1].strip()
            
            # 瑙ｆ瀽鎺ュ彛涓嬬殑缁戝畾璁板綍
            if 'source binding' in line and 'ip-address' in line:
                ip_match = re.search(r'ip-address\s+([\d\.]+)', line)
                mac_match = re.search(r'mac-address\s+([\w\-\.]+)', line)
                
                # 灏濊瘯鎻愬彇琛屽熬鐨?vlan 鍙傛暟
                vlan_inline_match = re.search(r'vlan\s+(\d+)', line)

                if ip_match and mac_match:
                    # 鏃犺鏄惁鏈夊熬宸达紝浼樺厛浣跨敤灏惧反涓婄殑 vlan锛屽惁鍒欎娇鐢ㄧ鍙ｉ粯璁?vlan
                    bind_vlan = vlan_inline_match.group(1) if vlan_inline_match else vlan
                    
                    # 馃敟 鏍稿績淇锛氭牴鎹帴鍙ｇ殑鐗╃悊鐗瑰緛鏉ユ墦鏍囩锛屼笉鍐嶈 vlan 灏惧反璇
                    bind_mode = 'access' if is_strict_access else 'trunk'

                    bindings.append({
                        'ip': ip_match.group(1), 
                        'mac': self.format_mac(mac_match.group(1)),
                        'mode': bind_mode,
                        'vlan': bind_vlan
                    })

        # 2. 鍏煎瑙ｆ瀽鍙兘娈嬬暀鐨勫叏灞€閰嶇疆 (闃插尽鎬т唬鐮佷繚鐣?
        target_iface_short = interface_name.replace('Ten-GigabitEthernet', 'XGE')\
                                           .replace('XGigabitEthernet', 'XGE')\
                                           .replace('M-GigabitEthernet', 'MGE')\
                                           .replace('GigabitEthernet', 'GE')

        for line in output_global.split('\n'):
            if 'Static' in line:
                parts = line.split()
                port_col = next((p for p in parts if p.startswith(('GE', 'XG', 'Gi', 'Te', 'BA'))), "")
                port_col_short = port_col.replace('Ten-GigabitEthernet', 'XGE')\
                                         .replace('XGigabitEthernet', 'XGE')\
                                         .replace('M-GigabitEthernet', 'MGE')\
                                         .replace('GigabitEthernet', 'GE')
                
                if port_col_short == target_iface_short:
                    ip_val = next((p for p in parts if p.count('.') == 3), "Unknown")
                    mac_val = next((p for p in parts if '-' in p and len(p) >= 12), "Unknown")
                    vlan_val = next((p for p in parts if p.isdigit() and len(p) <= 4), "Unknown")
                    
                    if ip_val != "Unknown" and mac_val != "Unknown":
                        if not any(b['ip'] == ip_val for b in bindings):
                            bindings.append({
                                'ip': ip_val,
                                'mac': self.format_mac(mac_val),
                                'mode': 'trunk',
                                'vlan': vlan_val
                            })

        return {'vlan': vlan, 'bindings': bindings, 'description': description}, output_iface + "\n\n[Global Bindings]\n" + output_global

    def get_all_bindings(self):
        conn = self._get_connection()
        try:
            config_out = conn.send_command(
                "display current-configuration interface",
                read_timeout=SSH_COMMAND_TIMEOUT,
            )
            global_out = conn.send_command("display ip source binding", read_timeout=SSH_COMMAND_TIMEOUT)
        finally:
            conn.disconnect()

        bindings = []
        current_iface = None
        current_vlan = "1"
        current_mode = "trunk"

        for raw_line in config_out.splitlines():
            line = raw_line.strip()
            if line.startswith("interface "):
                full_name = line.split(" ", 1)[1].strip()
                current_iface = full_name.replace('Ten-GigabitEthernet', 'XGE')\
                                         .replace('XGigabitEthernet', 'XGE')\
                                         .replace('M-GigabitEthernet', 'MGE')\
                                         .replace('GigabitEthernet', 'GE')
                current_vlan = "1"
                current_mode = "trunk"
                continue
            if not current_iface:
                continue
            if line.startswith("port access vlan"):
                parts = line.split()
                if len(parts) >= 4:
                    current_vlan = parts[3]
            elif line.startswith("port trunk pvid vlan"):
                parts = line.split()
                if len(parts) >= 5:
                    current_vlan = parts[4]
            elif line.startswith("ip verify source"):
                current_mode = "access"
            elif "source binding" in line and "ip-address" in line:
                ip_match = re.search(r'ip-address\s+([\d\.]+)', line)
                mac_match = re.search(r'mac-address\s+([\w\-\.]+)', line)
                vlan_match = re.search(r'vlan\s+(\d+)', line)
                if ip_match and mac_match:
                    bindings.append({
                        'ip': ip_match.group(1),
                        'mac': self.format_mac(mac_match.group(1)),
                        'switch_port': current_iface,
                        'vlan': vlan_match.group(1) if vlan_match else current_vlan,
                        'mode': current_mode,
                    })

        known = {(b['ip'], b['mac'], b['switch_port']) for b in bindings}
        for line in global_out.splitlines():
            if 'Static' not in line:
                continue
            parts = line.split()
            port_col = next((p for p in parts if p.startswith(('GE', 'XG', 'Gi', 'Te', 'BA'))), "")
            ip_val = next((p for p in parts if p.count('.') == 3), "")
            mac_val = next((p for p in parts if '-' in p and len(p) >= 12), "")
            if not port_col or not ip_val or not mac_val:
                continue
            port_col_short = port_col.replace('Ten-GigabitEthernet', 'XGE')\
                                     .replace('XGigabitEthernet', 'XGE')\
                                     .replace('M-GigabitEthernet', 'MGE')\
                                     .replace('GigabitEthernet', 'GE')
            mac_val = self.format_mac(mac_val)
            vlan_val = next((p for p in parts if p.isdigit() and len(p) <= 4), "")
            if (ip_val, mac_val, port_col_short) not in known:
                bindings.append({
                    'ip': ip_val,
                    'mac': mac_val,
                    'switch_port': port_col_short,
                    'vlan': vlan_val,
                    'mode': 'trunk',
                })

        return bindings
		
# === 馃洜锔?缁堟瀬瀹岀編鐗堬細閰嶇疆缁戝畾 (鏋佽嚧瀹夊叏涓庣簿绠€) ===
    def configure_port_binding(self, interface_name, vlan_id, bind_ip, bind_mac, mode="access", current_config=None):
        conn = self._get_connection()
        try:
            output_iface = current_config
            if output_iface is None:
                output_iface = conn.send_command(
                    f"display current-configuration interface {interface_name}",
                    read_timeout=SSH_COMMAND_TIMEOUT,
                )
            mac = self.format_mac(bind_mac)
            lines = {line.strip() for line in output_iface.splitlines()}
            existing_bindings = []

            for raw_line in output_iface.splitlines():
                line = raw_line.strip()
                if "source binding" not in line or "ip-address" not in line:
                    continue
                ip_match = re.search(r'ip-address\s+([\d\.]+)', line)
                mac_match = re.search(r'mac-address\s+([\w\-\.]+)', line)
                vlan_match = re.search(r'vlan\s+(\d+)', line)
                if ip_match and mac_match:
                    existing_bindings.append(
                        {
                            'ip': ip_match.group(1),
                            'mac': self.format_mac(mac_match.group(1)),
                            'vlan': vlan_match.group(1) if vlan_match else str(vlan_id or ''),
                        }
                    )

            for item in existing_bindings:
                same_ip = item['ip'] == bind_ip
                same_mac = item['mac'] == mac
                if same_ip and same_mac:
                    return f"目标端口已存在相同绑定，未重复下发: {bind_ip} {mac}"
                if same_ip or same_mac:
                    raise RuntimeError(
                        f"目标端口存在冲突绑定: {item['ip']} {item['mac']}，拒绝继续下发"
                    )

            cmds = [f"interface {interface_name}"]
            if mode == "access":
                if "stp edged-port" not in lines:
                    cmds.append("stp edged-port")
                if f"port access vlan {vlan_id}" not in lines:
                    cmds.append(f"port access vlan {vlan_id}")
                if "ip verify source ip-address mac-address" not in lines:
                    cmds.append("ip verify source ip-address mac-address")
                cmds.append(f"ip source binding ip-address {bind_ip} mac-address {mac}")
            else:
                cmds.append(f"ip source binding ip-address {bind_ip} mac-address {mac} vlan {vlan_id}")
                cmds.extend(["quit", f"vlan {vlan_id}", "arp detection enable"])

            output = conn.send_config_set(cmds)
            self._ensure_command_success(output)
            conn.save_config()
            return output
        finally:
            conn.disconnect()

    def set_interface_description(self, interface_name, description):
        conn = self._get_connection()
        try:
            cmds = [f"interface {interface_name}"]
            text = str(description or "").strip()
            if text:
                cmds.append(f"description {text}")
            else:
                cmds.append("undo description")
            output = conn.send_config_set(cmds)
            self._ensure_command_success(output)
            conn.save_config()
            return output
        finally:
            conn.disconnect()

    def configure_port_bindings_batch(self, interface_name, bindings, mode="access"):
        if not bindings:
            raise ValueError("没有可下发的绑定记录")

        conn = self._get_connection()
        cmds = [f"interface {interface_name}"]

        if mode == "access":
            vlan_values = {str(item.get('vlan', '')).strip() for item in bindings if str(item.get('vlan', '')).strip()}
            if len(vlan_values) != 1:
                raise ValueError("Access 模式下，同一端口的批量绑定必须使用同一个 VLAN")
            vlan_id = next(iter(vlan_values))
            cmds.extend(
                [
                    "stp edged-port",
                    f"port access vlan {vlan_id}",
                    "ip verify source ip-address mac-address",
                ]
            )
            for item in bindings:
                cmds.append(
                    f"ip source binding ip-address {item['bind_ip']} mac-address {self.format_mac(item['mac'])}"
                )
        else:
            vlan_ids = []
            for item in bindings:
                vlan_id = str(item.get('vlan', '')).strip()
                if not vlan_id:
                    raise ValueError("Trunk 模式批量绑定时每条记录都必须提供 VLAN")
                cmds.append(
                    f"ip source binding ip-address {item['bind_ip']} mac-address {self.format_mac(item['mac'])} vlan {vlan_id}"
                )
                if vlan_id not in vlan_ids:
                    vlan_ids.append(vlan_id)
            cmds.append("quit")
            for vlan_id in vlan_ids:
                cmds.extend([f"vlan {vlan_id}", "arp detection enable"])

        output = conn.send_config_set(cmds)
        conn.save_config()
        conn.disconnect()
        return output

    # === 馃洜锔?缁堟瀬瀹岀編鐗堬細鍒犻櫎缁戝畾 (涓嶇暀姝昏) ===
    def delete_port_binding(self, interface_name, del_ip, del_mac, mode="access", vlan_id=None):
        conn = self._get_connection()
        
        if mode == "access":
            cmds = [
                f"interface {interface_name}",
                # Access 妯″紡瑙ｇ粦锛氬共鍑€鍒╄惤
                f"undo ip source binding ip-address {del_ip} mac-address {self.format_mac(del_mac)}"
            ]
        else:
            cmds = [
                f"interface {interface_name}",
                # Trunk 妯″紡瑙ｇ粦锛氱簿鍑嗗尮閰?vlan 鏍?
                f"undo ip source binding ip-address {del_ip} mac-address {self.format_mac(del_mac)} vlan {vlan_id}"
            ]
            
        output = conn.send_config_set(cmds)
        conn.save_config()
        conn.disconnect()
        return output

    def get_acl_rules(self, acl_number=4000):
        conn = self._get_connection()
        output = conn.send_command(f"display acl {acl_number}")
        conn.disconnect()
        
        rules = []
        # 瑙ｆ瀽瑙勫垯: rule 0 permit source aaaa-bbbb-cccc ffff-ffff-ffff
        for line in output.split('\n'):
            if line.strip().startswith('rule'):
                parts = line.split()
                try:
                    rule_id = parts[1]
                    action = parts[2]
                    mac = parts[4] # 绠€鍗曞亣璁?mac 鍦ㄧ5涓綅缃?
                    rules.append({'id': rule_id, 'action': action, 'mac': self.format_mac(mac)})
                except:
                    pass
        return rules

    def _parse_acl_output(self, output, default_acl_number=None):
        import re

        groups = []
        current = None
        header_patterns = [
            re.compile(r'^(?P<type>.+?ACL)\s+(?P<number>\d{4})\b', re.IGNORECASE),
            re.compile(r'^acl\s+(?:mac\s+)?(?P<number>\d{4})\b', re.IGNORECASE),
        ]

        def ensure_group(number, acl_type='ACL'):
            for group in groups:
                if group['number'] == str(number):
                    return group
            group = {'number': str(number), 'type': acl_type.strip(), 'rules': []}
            groups.append(group)
            return group

        if default_acl_number is not None:
            current = ensure_group(default_acl_number, 'ACL')

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            matched_header = None
            for pattern in header_patterns:
                matched_header = pattern.search(line)
                if matched_header:
                    break
            if matched_header:
                acl_type = matched_header.groupdict().get('type') or 'ACL'
                current = ensure_group(matched_header.group('number'), acl_type)
                continue
            if not line.startswith('rule'):
                continue
            if current is None:
                current = ensure_group(default_acl_number or 'unknown', 'ACL')

            parts = line.split()
            if len(parts) < 3:
                continue
            rule = {
                'acl_number': current['number'],
                'acl_type': current['type'],
                'id': parts[1],
                'action': parts[2],
                'mac': '',
                'raw': line,
            }
            mac_match = re.search(r'([0-9a-fA-F]{4}[-:.][0-9a-fA-F]{4}[-:.][0-9a-fA-F]{4})', line)
            if mac_match:
                rule['mac'] = self.format_mac(mac_match.group(1))
            current['rules'].append(rule)

        return groups

    def get_acl_groups(self):
        conn = self._get_connection()
        try:
            output = conn.send_command("display acl all", read_timeout=SSH_LONG_COMMAND_TIMEOUT)
        finally:
            conn.disconnect()
        return self._parse_acl_output(output)

    def add_acl_mac(self, mac, rule_id=None, acl_number=4000):
        cmd = f"rule {rule_id} permit" if rule_id else "rule permit"
        cmd += f" source {self.format_mac(mac)} ffff-ffff-ffff"
        
        config_cmds = [
            f"acl mac {acl_number}",
            cmd
        ]
        conn = self._get_connection()
        output = conn.send_config_set(config_cmds)
        conn.save_config()
        conn.disconnect()
        return output

    def delete_acl_rule(self, rule_id, acl_number=4000):
        config_cmds = [
            f"acl mac {acl_number}",
            f"undo rule {rule_id}"
        ]
        conn = self._get_connection()
        output = conn.send_config_set(config_cmds)
        conn.save_config()
        conn.disconnect()
        return output

    def save_config_to_device(self):
        conn = self._get_connection()
        output = conn.save_config()
        conn.disconnect()
        return output

    def get_full_config(self):
        conn = self._get_connection()
        try:
            # netmiko 浼氳嚜鍔ㄥ鐞嗗垎灞?(--More--)
            config = conn.send_command("display current-configuration")
            return config
        except Exception as e:
            raise e
        finally:
            conn.disconnect()
			
# ==========================================
# 馃殌 鍗庝负浜ゆ崲鏈洪┍鍔ㄥ紩鎿?(缁ф壙鑷?H3CManager)
# ==========================================
class HuaweiManager(H3CManager):
    def __init__(self, ip, username, password, port=22):
        super().__init__(ip, username, password, port)
        # 寮哄埗搴曞眰 netmiko 鍒囨崲涓哄崕涓烘ā寮?(涓嶄粎瑙ｅ喅鍛戒护鎻愮ず绗﹂棶棰橈紝杩樹細鑷姩澶勭悊 save 鏃剁殑 [Y/N] 纭锛?
        self.device_info['device_type'] = 'huawei'

    def _expand_interface_name(self, interface_name):
        name = str(interface_name).strip()
        if name.startswith('GE'):
            return name.replace('GE', 'GigabitEthernet', 1)
        if name.startswith('XGE'):
            return name.replace('XGE', 'XGigabitEthernet', 1)
        if name.startswith('10GE'):
            return name
        if name.startswith('Eth'):
            return name.replace('Eth', 'Ethernet', 1)
        return name
        
    def get_full_config(self):
        conn = self._get_connection()
        try:
            conn.send_command("screen-length 0 temporary", read_timeout=SSH_COMMAND_TIMEOUT)
            config = conn.send_command("display current-configuration")
            return config
        except Exception as e:
            raise e
        finally:
            conn.disconnect()

    # 馃憞 1. 閲嶅啓鍗庝负锛氳幏鍙栫鍙ｈ鎯呬笌宸叉湁缁戝畾璁板綍
    def get_port_info(self, interface_name):
        full_name = self._expand_interface_name(interface_name)
        conn = self._get_connection()
        try:
            output_iface = conn.send_command(
                f"display current-configuration interface {full_name}",
                read_timeout=SSH_COMMAND_TIMEOUT,
            )
            output_global = conn.send_command(
                "display current-configuration | include user-bind",
                read_timeout=SSH_COMMAND_TIMEOUT,
            )
        finally:
            conn.disconnect()

    def get_alarm_logs(self):
        conn = self._get_connection()
        try:
            conn.send_command("screen-length 0 temporary", read_timeout=SSH_COMMAND_TIMEOUT)
            output = conn.send_command("display logbuffer", read_timeout=SSH_LONG_COMMAND_TIMEOUT)
        finally:
            conn.disconnect()
        return output

        vlan = ""
        description = ""
        bindings = []
        
        is_strict_access = (
            'ip source check user-bind enable' in output_iface
            or 'ipv4 source check user-bind enable' in output_iface
        )

        import re
        for line in output_iface.split('\n'):
            line = line.strip()
            
            # 鍗庝负鑾峰彇 Access / Trunk VLAN 鐨勫懡浠ゅ樊寮?
            if line.startswith('port default vlan'): 
                parts = line.split()
                if len(parts) >= 4: vlan = parts[3]
            elif line.startswith('port trunk pvid vlan'):
                parts = line.split()
                if len(parts) >= 5: vlan = parts[4]
            elif line.startswith('description'):
                parts = line.split(maxsplit=1)
                if len(parts) > 1: description = parts[1].strip()
            
            # 瑙ｆ瀽鍗庝负鐨勭粦瀹氳褰? user-bind static ip-address 1.1.1.1 mac-address aaaa-bbbb-cccc
            if 'user-bind' in line and 'ip-address' in line:
                ip_match = re.search(r'ip-address\s+([\d\.]+)', line)
                mac_match = re.search(r'mac-address\s+([\w\-\.]+)', line)
                vlan_inline_match = re.search(r'vlan\s+(\d+)', line)

                if ip_match and mac_match:
                    bind_vlan = vlan_inline_match.group(1) if vlan_inline_match else vlan
                    bind_mode = 'access' if is_strict_access else 'trunk'
                    bindings.append({
                        'ip': ip_match.group(1), 
                        'mac': self.format_mac(mac_match.group(1)),
                        'mode': bind_mode,
                        'vlan': bind_vlan
                    })

        global_bindings = []
        for line in output_global.split('\n'):
            line = line.strip()
            if 'user-bind static ip-address' in line:
                ip_match = re.search(r'ip-address\s+([\d\.]+)', line)
                mac_match = re.search(r'mac-address\s+([\w\-\.]+)', line)
                vlan_inline_match = re.search(r'vlan\s+(\d+)', line)
                if ip_match and mac_match:
                    global_bindings.append({
                        'ip': ip_match.group(1),
                        'mac': self.format_mac(mac_match.group(1)),
                        'mode': 'access' if is_strict_access else 'trunk',
                        'vlan': vlan_inline_match.group(1) if vlan_inline_match else vlan
                    })

        query_scope = 'interface'
        if not bindings and is_strict_access and global_bindings:
            bindings = global_bindings
            query_scope = 'device_global_fallback'

        return {
            'vlan': vlan,
            'bindings': bindings,
            'description': description,
            'query_scope': query_scope
        }, output_iface + "\n\n[Global User-Bind]\n" + output_global

    def get_all_bindings(self):
        conn = self._get_connection()
        try:
            conn.send_command("screen-length 0 temporary", read_timeout=SSH_COMMAND_TIMEOUT)
            config_out = conn.send_command(
                "display current-configuration interface",
                read_timeout=SSH_LONG_COMMAND_TIMEOUT,
            )
        finally:
            conn.disconnect()

        bindings = []
        current_iface = None
        current_vlan = "1"
        current_mode = "trunk"

        for raw_line in config_out.splitlines():
            line = raw_line.strip()
            if line.startswith("interface "):
                full_name = line.split(" ", 1)[1].strip()
                current_iface = full_name.replace('GigabitEthernet', 'GE')\
                                         .replace('XGigabitEthernet', 'XGE')\
                                         .replace('Ten-GigabitEthernet', 'XGE')\
                                         .replace('Ethernet', 'Eth')
                current_vlan = "1"
                current_mode = "trunk"
                continue
            if not current_iface:
                continue
            if line.startswith("port default vlan"):
                parts = line.split()
                if len(parts) >= 4:
                    current_vlan = parts[3]
            elif line.startswith("port trunk pvid vlan"):
                parts = line.split()
                if len(parts) >= 5:
                    current_vlan = parts[4]
            elif "source check user-bind enable" in line:
                current_mode = "access"
            elif "user-bind" in line and "ip-address" in line:
                ip_match = re.search(r'ip-address\s+([\d\.]+)', line)
                mac_match = re.search(r'mac-address\s+([\w\-\.]+)', line)
                vlan_match = re.search(r'vlan\s+(\d+)', line)
                if ip_match and mac_match:
                    bindings.append({
                        'ip': ip_match.group(1),
                        'mac': self.format_mac(mac_match.group(1)),
                        'switch_port': current_iface,
                        'vlan': vlan_match.group(1) if vlan_match else current_vlan,
                        'mode': current_mode,
                    })

        return bindings

    # 馃憞 2. 閲嶅啓鍗庝负锛氶厤缃鍙ｇ粦瀹?
    def configure_port_binding(self, interface_name, vlan_id, bind_ip, bind_mac, mode="access", current_config=None):
        full_name = self._expand_interface_name(interface_name)
        conn = self._get_connection()
        try:
            output_iface = current_config
            if output_iface is None:
                output_iface = conn.send_command(
                    f"display current-configuration interface {full_name}",
                    read_timeout=SSH_COMMAND_TIMEOUT,
                )
            mac = self.format_mac(bind_mac)
            lines = {line.strip() for line in output_iface.splitlines()}

            for raw_line in output_iface.splitlines():
                line = raw_line.strip()
                if "user-bind" not in line or "ip-address" not in line:
                    continue
                ip_match = re.search(r'ip-address\s+([\d\.]+)', line)
                mac_match = re.search(r'mac-address\s+([\w\-\.]+)', line)
                if not ip_match or not mac_match:
                    continue
                old_ip = ip_match.group(1)
                old_mac = self.format_mac(mac_match.group(1))
                same_ip = old_ip == bind_ip
                same_mac = old_mac == mac
                if same_ip and same_mac:
                    return f"目标端口已存在相同绑定，未重复下发: {bind_ip} {mac}"
                if same_ip or same_mac:
                    raise RuntimeError(f"目标端口存在冲突绑定: {old_ip} {old_mac}，拒绝继续下发")

            cmds = [f"interface {full_name}"]
            if mode == "access":
                if "stp edged-port enable" not in lines:
                    cmds.append("stp edged-port enable")
                if f"port default vlan {vlan_id}" not in lines:
                    cmds.append(f"port default vlan {vlan_id}")
                if (
                    "ip source check user-bind enable" not in lines
                    and "ipv4 source check user-bind enable" not in lines
                ):
                    cmds.append("ip source check user-bind enable")
                cmds.append(f"user-bind static ip-address {bind_ip} mac-address {mac}")
            else:
                cmds.append(f"user-bind static ip-address {bind_ip} mac-address {mac} vlan {vlan_id}")

            output = conn.send_config_set(cmds)
            self._ensure_command_success(output)
            conn.save_config()
            return output
        finally:
            conn.disconnect()

    def set_interface_description(self, interface_name, description):
        full_name = self._expand_interface_name(interface_name)
        conn = self._get_connection()
        try:
            cmds = [f"interface {full_name}"]
            text = str(description or "").strip()
            if text:
                cmds.append(f"description {text}")
            else:
                cmds.append("undo description")
            output = conn.send_config_set(cmds)
            self._ensure_command_success(output)
            conn.save_config()
            return output
        finally:
            conn.disconnect()

    def configure_port_bindings_batch(self, interface_name, bindings, mode="access"):
        if not bindings:
            raise ValueError("没有可下发的绑定记录")

        full_name = self._expand_interface_name(interface_name)
        conn = self._get_connection()
        cmds = [f"interface {full_name}"]

        if mode == "access":
            vlan_values = {str(item.get('vlan', '')).strip() for item in bindings if str(item.get('vlan', '')).strip()}
            if len(vlan_values) != 1:
                raise ValueError("Access 模式下，同一端口的批量绑定必须使用同一个 VLAN")
            vlan_id = next(iter(vlan_values))
            cmds.extend(
                [
                    "stp edged-port enable",
                    f"port default vlan {vlan_id}",
                    "ip source check user-bind enable",
                ]
            )
            for item in bindings:
                cmds.append(
                    f"user-bind static ip-address {item['bind_ip']} mac-address {self.format_mac(item['mac'])}"
                )
        else:
            for item in bindings:
                vlan_id = str(item.get('vlan', '')).strip()
                if not vlan_id:
                    raise ValueError("Trunk/Hybrid 模式批量绑定时每条记录都必须提供 VLAN")
                cmds.append(
                    f"user-bind static ip-address {item['bind_ip']} mac-address {self.format_mac(item['mac'])} vlan {vlan_id}"
                )

        output = conn.send_config_set(cmds)
        self._ensure_command_success(output)
        conn.save_config()
        conn.disconnect()
        return output

    # 馃憞 3. 閲嶅啓鍗庝负锛氬垹闄ょ鍙ｇ粦瀹?
    def delete_port_binding(self, interface_name, del_ip, del_mac, mode="access", vlan_id=None):
        conn = self._get_connection()
        if mode == "access":
            cmds = [
                f"undo user-bind static ip-address {del_ip} mac-address {self.format_mac(del_mac)}"
            ]
        else:
            cmds = [
                f"undo user-bind static ip-address {del_ip} mac-address {self.format_mac(del_mac)} vlan {vlan_id}"
            ]
            
        output = conn.send_config_set(cmds)
        self._ensure_command_success(output)
        conn.save_config()
        conn.disconnect()
        return output

    def add_acl_mac(self, mac, rule_id=None, acl_number=4000):
        cmd = f"rule {rule_id} permit" if rule_id else "rule permit"
        cmd += f" source {self.format_mac(mac)} ffff-ffff-ffff"
        config_cmds = [f"acl {acl_number}", cmd]
        conn = self._get_connection()
        output = conn.send_config_set(config_cmds)
        self._ensure_command_success(output)
        conn.save_config()
        conn.disconnect()
        return output

    def get_acl_groups(self):
        conn = self._get_connection()
        try:
            conn.send_command("screen-length 0 temporary", read_timeout=SSH_COMMAND_TIMEOUT)
            output = conn.send_command("display acl all", read_timeout=SSH_LONG_COMMAND_TIMEOUT)
        finally:
            conn.disconnect()
        return self._parse_acl_output(output)

    def delete_acl_rule(self, rule_id, acl_number=4000):
        config_cmds = [f"acl {acl_number}", f"undo rule {rule_id}"]
        conn = self._get_connection()
        output = conn.send_config_set(config_cmds)
        self._ensure_command_success(output)
        conn.save_config()
        conn.disconnect()
        return output


# 馃憞 閲嶅啓鍗庝负锛氳幏鍙栨帴鍙ｅ垪琛?(瑙ｅ喅鎶撳彇鍒板埄鐢ㄧ巼鐧惧垎姣旂殑闂)
    def get_interface_list(self):
        conn = self._get_connection()
        brief_out = conn.send_command("display interface brief")
        config_out = conn.send_command("display current-configuration interface")
        conn.disconnect()

        interfaces = []
        
        # 1. 瑙ｆ瀽 brief 鑾峰彇鎺ュ彛鍚嶅拰鐗╃悊鐘舵€?(UP/DOWN)
        for line in brief_out.split('\n'):
            parts = line.split()
            # 鍗庝负鐨勬帴鍙ｈ閫氬父浠?GigabitEthernet, XGigabitEthernet, GE 绛夊紑澶?
            if len(parts) >= 3 and parts[0].startswith(('GE', 'XGE', 'Gig', 'XGig', '10GE', 'Eth')):
                name = parts[0]
                short_name = name.replace('GigabitEthernet', 'GE')\
                                 .replace('XGigabitEthernet', 'XGE')\
                                 .replace('Ten-GigabitEthernet', 'XGE')\
                                 .replace('Ethernet', 'Eth')
                
                # 鍗庝负鐨勭墿鐞嗙姸鎬佸湪绗簩鍒楋紝鍙兘鏄?up, down, 鎴栬€?*down (绠＄悊down)
                link_status = parts[1].replace('*', '').upper() 
                
                interfaces.append({
                    'name': short_name, 
                    'desc': '', 
                    'link': link_status, 
                    'type': 'Hybrid' # 鍗庝负榛樿閫氬父鏄?Hybrid锛屽悗闈㈤€氳繃 config 绮惧噯瑕嗙洊
                })
        
        # 2. 瑙ｆ瀽 config 鑾峰彇鎻忚堪 (description) 鍜屽噯纭殑妯″紡 (port link-type)
        current_iface = None
        for line in config_out.split('\n'):
            line = line.strip()
            if line.startswith('interface '):
                full_name = line.split(' ')[1]
                current_iface = full_name.replace('GigabitEthernet', 'GE')\
                                         .replace('XGigabitEthernet', 'XGE')\
                                         .replace('Ten-GigabitEthernet', 'XGE')\
                                         .replace('Ethernet', 'Eth')
            elif current_iface:
                if line.startswith('description '):
                    desc_text = line.replace('description ', '').strip()
                    for iface in interfaces:
                        if iface['name'] == current_iface:
                            iface['desc'] = desc_text
                            break
                elif line.startswith('port link-type '):
                    # 鎶撳彇 access 鎴?trunk
                    port_type = line.split(' ')[-1].capitalize() 
                    for iface in interfaces:
                        if iface['name'] == current_iface:
                            iface['type'] = port_type
                            break
        
        # 3. 鏍煎紡鍖栬緭鍑轰緵鍓嶇娓叉煋
        result = []
        for iface in interfaces:
            display_text = f"[{iface['link']}] [{iface['type']}] {iface['name']}"
            if iface['desc']:
                display_text += f" ({iface['desc']})"
            result.append({'value': iface['name'], 'text': display_text})
            
        return result		
