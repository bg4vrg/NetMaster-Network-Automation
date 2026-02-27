import re
import time
from netmiko import ConnectHandler

class H3CManager:
    def __init__(self, ip, username, password, port=22):
        self.device_info = {
            'device_type': 'hp_comware',
            'ip': ip,
            'username': username,
            'password': password,
            'port': port,
            'global_delay_factor': 2, # 增加延时防止超时
        }

    def _get_connection(self):
        return ConnectHandler(**self.device_info)
    
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
                    
        return f"✅ 连接成功！\n设备名称: {hostname}\n设备型号: {model}"

# === 🛠️ 终极修复版：获取接口列表 (解决 XGE 描述丢失问题) ===
    def get_interface_list(self):
        conn = self._get_connection()
        brief_out = conn.send_command("display interface brief")
        config_out = conn.send_command("display current-configuration interface")
        conn.disconnect()

        interfaces = []
        
        # 1. 解析 brief 获取接口名、状态 (UP/DOWN)、模式 (Access/Trunk)
        for line in brief_out.split('\n'):
            parts = line.split()
            if len(parts) >= 5:
                name = parts[0]
                if name.startswith(('GE', 'XGE', 'Gigabit', 'MGE', 'Bridge', 'Ten-Gigabit', 'XGigabit')):
                    # 🔥 修复：先替换长的 (Ten-GigabitEthernet)，再替换短的 (GigabitEthernet)
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
        
        # 2. 解析 config 获取 description
        current_iface = None
        for line in config_out.split('\n'):
            line = line.strip()
            if line.startswith('interface '):
                full_name = line.split(' ')[1]
                # 🔥 修复：保持正确的替换顺序
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
        
        # 3. 格式化输出
        result = []
        for iface in interfaces:
            display_text = f"[{iface['link']}] [{iface['type']}] {iface['name']}"
            if iface['desc']:
                display_text += f" ({iface['desc']})"
            result.append({'value': iface['name'], 'text': display_text})
            
        return result

    # === 🛠️ 终极修复版：获取端口详情 (同步更新替换顺序) ===
    def get_port_info(self, interface_name):
        conn = self._get_connection()
        output_iface = conn.send_command(f"display current-configuration interface {interface_name}")
        output_global = conn.send_command("display ip source binding")
        conn.disconnect()

        vlan = ""
        description = ""
        bindings = []

        # 1. 解析接口配置
        for line in output_iface.split('\n'):
            line = line.strip()
            if line.startswith('port access vlan'):
                parts = line.split()
                if len(parts) >= 4: vlan = parts[3]
            elif line.startswith('port trunk pvid vlan'):
                parts = line.split()
                if len(parts) >= 5: vlan = parts[4]
                
            elif line.startswith('description'):
                parts = line.split(maxsplit=1)
                if len(parts) > 1: description = parts[1].strip()
            
            # Access 模式
            if 'source binding' in line and 'ip-address' in line:
                ip_match = re.search(r'ip-address\s+([\d\.]+)', line)
                mac_match = re.search(r'mac-address\s+([\w\-\.]+)', line)
                if ip_match and mac_match:
                    bindings.append({
                        'ip': ip_match.group(1), 
                        'mac': self.format_mac(mac_match.group(1)),
                        'mode': 'access',
                        'vlan': vlan
                    })

        # 2. 解析全局配置
        # 🔥 修复：同步使用正确的替换顺序
        target_iface_short = interface_name.replace('Ten-GigabitEthernet', 'XGE')\
                                           .replace('XGigabitEthernet', 'XGE')\
                                           .replace('M-GigabitEthernet', 'MGE')\
                                           .replace('GigabitEthernet', 'GE')

        for line in output_global.split('\n'):
            if 'Static' in line:
                parts = line.split()
                port_col = next((p for p in parts if p.startswith(('GE', 'XG', 'Gi', 'Te', 'BA'))), "")
                
                # 🔥 修复：同步使用正确的替换顺序
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
		
# === 🛠️ 最终修复版：配置绑定 ===
    def configure_port_binding(self, interface_name, vlan_id, bind_ip, bind_mac, mode="access"):
        conn = self._get_connection()
        if mode == "access":
            cmds = [
                f"interface {interface_name}",
                "stp edged-port",
                f"port access vlan {vlan_id}",
                "ip verify source ip-address mac-address",
                # Access 模式：在接口下绑定
                f"ip source binding ip-address {bind_ip} mac-address {self.format_mac(bind_mac)}"
            ]
        else: 
            # Trunk 混合模式：不改变端口原有配置，直接下发绑定，并配置 VLAN
            cmds = [
                f"interface {interface_name}",
                # 🔥 核心修改：Trunk 也直接在接口下绑定！但不下发 ip verify source
                f"ip source binding ip-address {bind_ip} mac-address {self.format_mac(bind_mac)}",
                "quit",
                # 进入对应业务 VLAN 开启 ARP 检测
                f"vlan {vlan_id}",
                "arp detection enable"
            ]
            
        output = conn.send_config_set(cmds)
        conn.save_config()
        conn.disconnect()
        return output

    # === 🛠️ 最终修复版：删除绑定 ===
    def delete_port_binding(self, interface_name, del_ip, del_mac, mode="access", vlan_id=None):
        conn = self._get_connection()
        
        # 🔥 核心修改：既然 Access 和 Trunk 都是在接口下绑定的，那解绑逻辑就完全一样了！
        cmds = [
            f"interface {interface_name}",
            f"undo ip source binding ip-address {del_ip} mac-address {self.format_mac(del_mac)}"
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
        # 解析规则: rule 0 permit source aaaa-bbbb-cccc ffff-ffff-ffff
        for line in output.split('\n'):
            if line.strip().startswith('rule'):
                parts = line.split()
                try:
                    rule_id = parts[1]
                    action = parts[2]
                    mac = parts[4] # 简单假设 mac 在第5个位置
                    rules.append({'id': rule_id, 'action': action, 'mac': self.format_mac(mac)})
                except:
                    pass
        return rules

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
            # netmiko 会自动处理分屏 (--More--)
            config = conn.send_command("display current-configuration")
            return config
        except Exception as e:
            raise e
        finally:
            conn.disconnect()