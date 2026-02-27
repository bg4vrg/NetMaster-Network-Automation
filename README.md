# H3C Switch Admin Tool v2.2.0

![Python](https://img.shields.io/badge/Python-3.11-blue)
![License](https://img.shields.io/badge/License-GPLv3-green)
![Version](https://img.shields.io/badge/Version-v2.0.0-orange)


基于 Python 3.11 + Flask + Netmiko 开发的企业级 H3C 交换机 Web 运维平台。
本项目致力于在**零额外硬件成本**的前提下，充分挖掘交换机底层安全特性，从早期的单一脚本工具不断进化为集成了 **资产管理**、**安全登录** 、**ACL 极简管理**和 **批量自动化备份** 的综合运维系统，实现堪比商业 NAC（网络准入控制）系统的安全管控能力。

## ✨ v2.2.0 核心架构大升级

本次更新重构了底层的准入控制逻辑，完美解决复杂业务场景下的安全准入难题：
* 🛡️ **双模准入策略 (Dual-Mode NAC)**：
  * **Access 严格模式**：针对纯办公/视频/公安网，下发物理接口级 `ip verify source`，防御力拉满。
  * **Trunk 混合模式**：针对接 AP 的复杂端口（手机需动态 DHCP，电脑需静态绑定）。采用**全局 IP Source Binding + VLAN 级 ARP Detection** 的创新架构，实现同一物理端口下的差异化管控。
* 🔍 **MAC 寻址工具**：支持一键反查 MAC 地址所在的物理端口，并自动联动前端界面进行配置。
* 📡 **智能解析引擎**：彻底重构接口解析逻辑，精准匹配短名/长名，完美兼容万兆口（XGE/Ten-Gigabit），并在下拉框直观显示端口的 `[UP/DOWN]` 状态及 `[Access/Trunk]` 模式。

## 🚀 核心自动化功能

* **一键批量备份 (Batch Backup)**：轮询数据库所有设备，自动并发抓取配置并按日期归档，内置智能容错机制。
* **资产管理 (Asset Management)**：内置 SQLite 数据库，可视化管理全网交换机（支持自定义 SSH 端口）。
* **安全会话控制**：基于 Flask-Login 的认证系统，哈希加密保护资产数据。
* **ACL 极简管理**：将繁琐的 MAC ACL 规则抽象为直观的表格增删改查。

## 📸 运行截图

### 1. 资产管理与批量自动备份
*(请在此处插入你的备份日志截图)*

### 2. 双模端口安全绑定与 MAC 寻址
*(此处插入端口管理、模式选择及 MAC 寻址截图)*



## 🛠️ 环境依赖

本项目基于 **Python 3.11** 开发，请确保你的运行环境符合要求。

```bash
pip install -r requirements.txt
```

**请确保运行环境能通过 SSH 连接到交换机。**

## 🚀 启动方式
```
python run_server.py
```

访问浏览器：http://127.0.0.1:8080

**默认账号**

- 首次启动会自动初始化数据库。
- **用户名**：`admin`
- **初始密码**：`admin888`
- 建议登录后点击右上角修改密码)

## 📂 目录结构说明

```
H3C-Switch-Admin-Tool/
├── backups/             # [自动生成] 存放批量备份的配置文件，按日期归档
├── net_assets.db        # [自动生成] SQLite 数据库，存储用户和资产信息
├── app.py               # Flask 后端核心逻辑
├── switch_driver.py     # H3C 设备交互驱动 (Netmiko 封装)
├── database.py          # 数据库操作模块 (ORM)
├── templates/           # HTML 前端页面
│   ├── index.html       # 主控制台
│   └── login.html       # 登录页面
├── static/              # 静态资源 (CSS/JS)
├── requirements.txt     # 项目依赖列表
└── README.md            # 项目说明文档
```

## ⚠️ 注意事项

- **数据安全**：`net_assets.db` 包含资产信息，请勿上传至公开仓库（`.gitignore` 已默认忽略）。
- **备份文件**：`backups/` 目录包含网络配置敏感信息，请妥善保管。
- **端口说明**：程序默认运行在 **8080** 端口，如需修改请编辑 `app.py`。

## 📜 开源协议

本项目采用 **GNU General Public License v3.0 (GPL-3.0)** 协议。

- 你可以自由地复制、分发和修改本软件。
- 如果你发布了修改后的版本，必须同样基于 GPL-3.0 协议开源。
- 本软件按“原样”提供，不提供任何形式的担保。

## 📸 运行截图

### 1. 资产管理与批量备份日志

*![登录页面](./screenshots/v2-web0.png)*

*![首页](./screenshots/v2-homepage.png)*

*![资产管理](./screenshots/v2-web2.png)*

*![备份日志](./screenshots/v2-backuplog.png)*

### 2. 端口安全绑定

*![端口配置](./screenshots/web2-0.png)*
*![获取端口信息](./screenshots/web2.png)*

### 3. 设备管理列表
*![资产列表](./screenshots/switchlist.png)*

### 4. 设备端口保护
*![设备端口保护](./screenshots/GEprotect.png)*