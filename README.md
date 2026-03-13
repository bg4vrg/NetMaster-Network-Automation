🛡️ NetMaster 多厂商自动化网管平台 (v2.5.1 内网高可用版)

一款专为网络工程师打造的轻量级、可视化、高并发的交换机自动化运维管理系统。彻底告别繁琐的命令行敲击，通过 Web 界面实现全网设备的资产可视、一键准入控制、大规模批量割接与自动化灾备。

目前系统已完成**多厂商驱动架构解耦**，原生支持 **H3C (Comware 体系)** 与 **Huawei (VRP 体系)**。
**✅ 本版本已完成深度本地化改造，摆脱所有外部 CDN 依赖，支持在完全断网的物理隔离网络中 100% 完美部署与渲染。**

---

## ✨ 核心特性 (Key Features)

### 📊 1. 可视化数据看板 (Dashboard)
* **全局统筹**：首页直观呈现全网纳管设备总数、今日系统拦截/操作活跃度。
* **灾备监控**：实时追踪最近一次凌晨自动备份任务的状态与战报。

### 🚀 2. 多厂商智能调度与批量引擎
* **动态路由**：底层根据资产厂商标识自动切换 H3CManager 或 HuaweiManager 驱动。
* **标准化导入**：支持上传 Excel 模板，自动解析并渲染前端核对预览表。
* **沉浸式瀑布流终端**：实时滚动渲染并转义底层交换机 SSH 交互回显日志，执行进度一览无余。

### 🛡️ 3. 极严苛的安全与审计机制
* **核心链路保护**：基于关键词（如 Uplink、Core）智能拦截高危端口配置下发，防止全网瘫痪。
* **系统操作审计**：所有变更操作、定时任务均被强制打上时间戳与 IP 烙印，提供溯源弹窗。

### ⏰ 4. 幽灵定时灾备 (Auto Backup)
* **无人值守**：内置 APScheduler 调度引擎，每日凌晨静默唤醒。
* **精准归档**：并发拉取全网配置，按日期建档并追加 %H%M 时间戳后缀，单台失败精准记入审计。

### 📁 5. 智能化资产管理
* **色彩标识**：设备列表自动根据品牌赋予专属色彩徽章（H3C 经典蓝，Huawei 经典红）。
* **智能防呆**：后端强制校验 IP 唯一性，导入时自动跳过重复项。

---

## 📸 界面预览 (Screenshots)

**1. 首页数据看板与资产速连**

![Dashboard](./screenshots/dashboard.png)

**2. Excel 批量自动化部署与瀑布流日志**

![Excel Batch](./screenshots/piliangbushu.png)

**3. 企业级安全审计日志中心**

![Audit Logs](./screenshots/autobackup.png)

**4. 多厂商资产管理控制台**

![Asset Management](./screenshots/devices.png)

**5. 端口安全绑定**

![端口配置](./screenshots/web2-0.png)

![获取端口信息](./screenshots/web2.png)

![设备端口保护](./screenshots/GEprotect.png)

**6. 交换机自动备份**

![配置自动备份](./screenshots/autobackup.png)

**7. 操作时增加进度条**

![操作进度条](./screenshots/jindutiao.png)

---

## 🛠️ 技术栈 (Tech Stack)

* **后端框架**: Python 3.8+ / Flask
* **数据库**: SQLite3 (极轻量，无需额外配置)
* **网络引擎**: Netmiko / Paramiko
* **任务调度**: APScheduler
* **前端渲染**: HTML5 / Bootstrap 5 / 原生 Async JavaScript
* **文件解析**: openpyxl / csv

---

## 📦 快速部署 (Installation)

1. **克隆项目 / 下载源码**
   ```bash
    git clone [https://github.com/yourusername/NetMaster.git](https://github.com/yourusername/NetMaster.git)
    cd NetMaster

2. **创建并激活虚拟环境 (强烈推荐)**
   ```bash
    conda create -n netmaster python=3.10
    conda activate netmaster

3. **安装依赖**
   ```bash
    pip install -r requirements.txt

4. **一键启动服务**
   ```bash
    python run_server.py

**服务启动后，默认监听 [http://0.0.0.0:8080](http://0.0.0.0:8080)，局域网内任意浏览器即可访问。**

---

## 🗺️ 未来路线图 (Roadmap v3.0+)

[1] 华为配置深度验证: 持续在物理隔离网环境验证 HuaweiManager 各项指令的兼容性与稳定性。

[2] Config Diff 历史配置差异比对: 提供类似 Git 的红绿高亮视图，比对昨日与今日的交换机配置变化。

[3] MAC / IP 全网物理定位 (MAC Tracker): 输入 MAC 地址，并发追踪并精准定位其所在的楼层交换机与物理端口。

[4] 密码库高强度加密: SQLite 中的凭证由明文升级为 AES256 密文存储。

---

## ⚠️ 免责声明: 本工具涉及对底层网络设备的直接配置修改，在生产环境中批量下发前，请务必在测试设备上充分验证！

## ⚠️ 特别警告：v2.5.0 版本中，华为 (Huawei) 设备的“获取端口信息”已验证通过，但“端口绑定/解绑”功能尚未经过真机实测！请勿在生产环境的华为设备上贸然执行批量下发操作！