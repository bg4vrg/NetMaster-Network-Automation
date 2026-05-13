import re


def analyze_alarm_log_text(text):
    rules = [
        {'level': 'critical', 'category': '环路/风暴', 'score': 35, 'words': ['loop', 'storm', 'broadcast storm', 'mac-flapping', 'mac address flapping'], 'suggestion': '疑似环路、广播风暴或 MAC 漂移，建议立即检查 STP、下联小交换机、近期新增网线和异常端口。'},
        {'level': 'critical', 'category': '硬件/环境', 'score': 30, 'words': ['fan failed', 'power failed', 'temperature', 'overheat', 'over-temperature', 'voltage', 'psu', 'fatal', 'panic'], 'suggestion': '存在硬件或环境异常，建议检查风扇、电源、温度、机柜散热和设备面板告警。'},
        {'level': 'critical', 'category': '链路/端口中断', 'score': 18, 'words': ['link down', 'line protocol is down', 'interface down', 'changed state to down', 'unreachable'], 'suggestion': '存在链路或端口中断记录，建议核对高频端口的光模块、网线、对端设备和上联链路。'},
        {'level': 'warning', 'category': '链路抖动', 'score': 10, 'words': ['flap', 'updown', 'link up', 'changed state to up', 'port up'], 'suggestion': '存在端口抖动记录，建议按高频端口检查终端、网线、水晶头、光模块和速率双工协商。'},
        {'level': 'warning', 'category': 'STP 变化', 'score': 12, 'words': ['stp', 'spanning tree', 'topology change', 'tc event'], 'suggestion': '存在 STP 拓扑变化，建议确认是否有非法接入、小交换机、环路恢复或上联切换。'},
        {'level': 'warning', 'category': '认证/登录', 'score': 8, 'words': ['login failed', 'authentication failed', 'auth fail', 'password failed', 'invalid user', 'illegal user', 'failed password', 'sshs_auth_fail', 'telnet login failed'], 'suggestion': '存在认证或登录失败，建议核对来源地址、账号权限、弱口令尝试和堡垒机登录记录。'},
        {'level': 'warning', 'category': 'ARP限速/控制平面保护', 'score': 14, 'words': ['softcar drop', 'pkttype=arp'], 'require_all': True, 'suggestion': '发现 ARP 报文触发 SOFTCAR 控制平面保护丢弃，建议优先检查高频端口、源 MAC、ARP 异常、环路或下挂设备广播异常。'},
        {'level': 'warning', 'category': 'ACL/策略丢弃', 'score': 6, 'words': ['acl', 'deny', 'packet filter'], 'suggestion': '存在 ACL 或策略丢弃关键字，建议核对安全策略、命中方向和业务访问是否符合预期。'},
        {'level': 'warning', 'category': '资源/性能', 'score': 10, 'words': ['cpu', 'memory', 'high utilization', 'threshold', 'busy'], 'suggestion': '存在资源或性能告警，建议检查 CPU、内存、广播流量、日志风暴和管理进程状态。'},
        {'level': 'warning', 'category': '超时/管理链路', 'score': 6, 'words': ['timeout', 'timed out', 'ntp', 'snmp', 'radius', 'tacacs'], 'suggestion': '存在超时或管理链路关键字，建议检查管理网络、NTP/SNMP/RADIUS/TACACS 可达性和设备负载。'},
    ]
    lines = [line.strip() for line in str(text or '').splitlines() if line.strip()]
    scan_lines = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if 'softcar drop' in line.lower() and index + 1 < len(lines) and 'pkttype=' in lines[index + 1].lower():
            scan_lines.append(f"{line} {lines[index + 1]}")
            index += 2
            continue
        scan_lines.append(line)
        index += 1
    matched = []
    critical = 0
    warning = 0
    risk_score = 0
    suggestion_map = {}
    category_counts = {}
    port_counts = {}
    port_pattern = re.compile(r'\b(?:GE|XGE|GigabitEthernet|Ten-GigabitEthernet|FortyGigE|Eth|Ethernet|Bridge-Aggregation|Vlan-interface)\s*\d+(?:/\d+){0,3}\b', re.I)

    def normalize_log_port(port):
        text = re.sub(r'\s+', '', str(port or '')).upper()
        replacements = [
            ('TEN-GIGABITETHERNET', 'XGE'),
            ('GIGABITETHERNET', 'GE'),
            ('FORTYGIGE', 'FGE'),
            ('ETHERNET', 'ETH'),
            ('BRIDGE-AGGREGATION', 'BAGG'),
            ('VLAN-INTERFACE', 'VLANIF'),
        ]
        for old, new in replacements:
            if text.startswith(old):
                return new + text[len(old):]
        return text

    for line in scan_lines[-500:]:
        lower = line.lower()
        benign_auth = any(
            word in lower
            for word in [
                'auth_success',
                'authentication succeeded',
                'passed password authentication',
                'logged out',
                'disconnect',
                'connected to the server successfully',
                'sshs_connect',
                'sshs_log',
            ]
        )
        if benign_auth:
            continue
        for rule in rules:
            matched_rule = all(word in lower for word in rule['words']) if rule.get('require_all') else any(word in lower for word in rule['words'])
            if matched_rule:
                level = rule['level']
                category = rule['category']
                if level == 'critical':
                    critical += 1
                else:
                    warning += 1
                risk_score += rule['score']
                category_counts[category] = category_counts.get(category, 0) + 1
                suggestion_map[category] = rule['suggestion']
                ports = [normalize_log_port(port) for port in port_pattern.findall(line)]
                for port in ports:
                    port_counts[port] = port_counts.get(port, 0) + 1
                matched.append({'level': level, 'category': category, 'ports': ports, 'line': line})
                break
    if critical >= 5 or risk_score >= 80:
        risk_level = 'high'
        headline = '高风险：发现多条严重告警，建议优先排查环路、硬件环境和关键链路。'
    elif critical or warning >= 5 or risk_score >= 30:
        risk_level = 'medium'
        headline = '中风险：存在需要关注的告警，建议按分类和高频端口逐项核对。'
    elif warning:
        risk_level = 'low'
        headline = '低风险：发现少量告警关键字，建议观察趋势并核对相关端口。'
    else:
        risk_level = 'normal'
        headline = '正常：未发现明显严重告警关键字，可继续观察。'
    top_ports = [{'port': port, 'count': count} for port, count in sorted(port_counts.items(), key=lambda item: item[1], reverse=True)[:10]]
    suggestions = list(suggestion_map.values())
    if top_ports:
        suggestions.insert(0, f"高频端口：{', '.join([item['port'] + ' x' + str(item['count']) for item in top_ports[:5]])}。建议优先核对这些端口。")
    if not suggestions:
        suggestions.append('未发现明显严重告警关键字，可继续观察。')
    return {
        'total_lines': len(lines),
        'critical': critical,
        'warning': warning,
        'risk_score': min(risk_score, 100),
        'risk_level': risk_level,
        'headline': headline,
        'category_counts': category_counts,
        'top_ports': top_ports,
        'matched': matched[-100:],
        'suggestions': suggestions,
    }


def collect_switch_alarm_report(db_module, get_manager, get_switch_runtime_data, switch_ip):
    runtime = get_switch_runtime_data(switch_ip)
    switch_row = db_module.get_switch_by_ip(switch_ip) or {}
    mgr = get_manager(runtime)
    raw = mgr.get_alarm_logs()
    analysis = analyze_alarm_log_text(raw)
    db_module.add_switch_alarm_report(
        switch_ip=switch_ip,
        switch_name=switch_row.get('name', ''),
        vendor=runtime.get('vendor', ''),
        status='成功',
        analysis=analysis,
    )
    return {'raw': raw, 'analysis': analysis, 'switch': switch_row}


ALARM_COMMAND_GUIDE = {
    '环路/风暴': [
        {'cmd': 'display stp brief', 'desc': '查看 STP 根桥、端口角色和阻塞状态，确认是否存在异常拓扑变化。'},
        {'cmd': 'display mac-address flapping', 'desc': '查看 MAC 漂移记录，定位疑似环路或来回漂移的端口。'},
        {'cmd': 'display interface brief', 'desc': '快速查看端口 up/down 和流量异常端口。'},
    ],
    '链路/端口中断': [
        {'cmd': 'display interface <端口>', 'desc': '查看端口物理状态、错误包、速率双工、收发光功率等详细信息。'},
        {'cmd': 'display transceiver diagnosis interface <端口>', 'desc': '查看光模块诊断信息，排查光功率、温度、电压异常。'},
    ],
    '链路抖动': [
        {'cmd': 'display logbuffer | include <端口>', 'desc': '按端口过滤日志，确认抖动时间和频率。'},
        {'cmd': 'display interface <端口>', 'desc': '检查 CRC、input error、协商状态和端口重启计数。'},
    ],
    'STP 变化': [
        {'cmd': 'display stp brief', 'desc': '查看 STP 端口角色和状态，确认是否频繁变化。'},
        {'cmd': 'display stp history', 'desc': '查看 STP 历史变化记录，定位触发拓扑变化的端口。'},
    ],
    'ARP限速/控制平面保护': [
        {'cmd': 'display interface <高频端口>', 'desc': '检查高频端口广播/错误包/流量状态，确认 ARP 来源方向。'},
        {'cmd': 'display mac-address <源MAC>', 'desc': '定位日志中的源 MAC 当前学习在哪个端口或下游链路。'},
        {'cmd': 'display arp | include <源MAC或IP>', 'desc': '关联源 MAC 与 IP，判断是否为异常终端、网关或下挂设备。'},
        {'cmd': 'display stp brief', 'desc': '确认是否存在环路或 STP 拓扑异常导致 ARP 广播异常。'},
        {'cmd': 'display logbuffer | include SOFTCAR|ARP|<端口>', 'desc': '查看 SOFTCAR ARP DROP 的频率、端口和上下文。'},
    ],
    'ACL/策略丢弃': [
        {'cmd': 'display acl all', 'desc': '查看 ACL 规则，确认是否有误拦截或规则顺序问题。'},
        {'cmd': 'display packet-filter interface <端口>', 'desc': '查看端口方向上绑定的包过滤策略。'},
        {'cmd': 'display traffic classifier user-defined', 'desc': '查看流分类，辅助排查 QoS/安全策略命中。'},
    ],
    '认证/登录': [
        {'cmd': 'display local-user', 'desc': '核对本地账号和权限。'},
        {'cmd': 'display ssh server status', 'desc': '查看 SSH 服务状态和登录限制。'},
        {'cmd': 'display logbuffer | include LOGIN|AUTH|SSHS', 'desc': '过滤登录认证日志，确认是否存在失败尝试。'},
    ],
    '资源/性能': [
        {'cmd': 'display cpu-usage', 'desc': '查看 CPU 使用率和高负载进程。'},
        {'cmd': 'display memory', 'desc': '查看内存使用情况。'},
    ],
    '超时/管理链路': [
        {'cmd': 'ping <网管服务器IP>', 'desc': '验证到网管、认证或日志服务器的连通性。'},
        {'cmd': 'display ntp-service status', 'desc': '检查时间同步状态。'},
    ],
}


def build_alarm_command_suggestions(category_counts):
    commands = []
    seen = set()
    for category in sorted((category_counts or {}).keys(), key=lambda key: category_counts.get(key, 0), reverse=True):
        for item in ALARM_COMMAND_GUIDE.get(category, []):
            if item['cmd'] in seen:
                continue
            seen.add(item['cmd'])
            commands.append({'category': category, **item})
            if len(commands) >= 8:
                return commands
    return commands
