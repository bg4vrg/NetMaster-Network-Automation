import openpyxl
import os
import datetime
import json
import csv
import io
import re
from flask import Flask, render_template, request, jsonify, abort
from flask_login import LoginManager, UserMixin, login_required, current_user
from switch_driver import H3CManager, HuaweiManager
import database as db
import traceback
from validators import (
    require_fields,
    normalize_ip,
    normalize_port,
    normalize_vlan,
    normalize_vendor,
    normalize_switch_role,
    normalize_bool_flag,
    validate_password_policy,
    normalize_mac,
    normalize_mode,
    normalize_acl_number,
)
from backup_file_service import (
    backup_root_abs,
    count_backup_days,
    list_backup_config_files,
    read_backup_text,
    resolve_backup_file,
)
from data_package_service import (
    backup_current_db_key as service_backup_current_db_key,
    create_data_package as service_create_data_package,
    preview_data_package as service_preview_data_package,
    restore_data_package as service_restore_data_package,
    write_data_package_to_dir as service_write_data_package_to_dir,
)
from legacy_asset_service import import_legacy_switch_assets as service_import_legacy_switch_assets
from alarm_service import (
    build_alarm_command_suggestions,
    collect_switch_alarm_report as service_collect_switch_alarm_report,
)
from offline_binding_service import import_bindings_from_backup_files as service_import_bindings_from_backup_files
from terminal_sync_service import (
    MacSyncStateStore,
    log_mac_sync_switch_result as service_log_mac_sync_switch_result,
    persist_switch_bindings as service_persist_switch_bindings,
    read_switch_bindings_with_timeout as service_read_switch_bindings_with_timeout,
    run_mac_bindings_sync as service_run_mac_bindings_sync,
    scan_one_switch_for_terminal as service_scan_one_switch_for_terminal,
    sync_all_switch_bindings as service_sync_all_switch_bindings,
    sync_switch_bindings as service_sync_switch_bindings,
    sync_switch_bindings_with_timeout as service_sync_switch_bindings_with_timeout,
)
from blueprints.audit_task import create_audit_task_blueprint
from blueprints.alarm_manage import create_alarm_manage_blueprint
from blueprints.alarm_read import create_alarm_read_blueprint
from blueprints.backup_read import create_backup_read_blueprint
from blueprints.backup_manage import create_backup_manage_blueprint
from blueprints.info_read import create_info_read_blueprint
from blueprints.asset_user_read import create_asset_user_read_blueprint
from blueprints.asset_manage import create_asset_manage_blueprint
from blueprints.system_manage import create_system_manage_blueprint
from blueprints.user_manage import create_user_manage_blueprint
from blueprints.switch_connect import create_switch_connect_blueprint
from blueprints.access_manage import create_access_manage_blueprint
from blueprints.roam_manage import create_roam_manage_blueprint
from blueprints.excel_manage import create_excel_manage_blueprint
from blueprints.terminal_state import create_terminal_state_blueprint
from blueprints.profile_health import create_profile_health_blueprint
from blueprints.task_runtime import create_task_runtime_blueprint
from blueprints.port_snapshot import create_port_snapshot_blueprint
from blueprints.snmp_status import create_snmp_status_blueprint
from blueprints.auth_pages import create_auth_pages_blueprint
from blueprints.compliance_analysis import create_compliance_analysis_blueprint
from runtime_paths import BACKUP_DIR, DATA_PACKAGE_DIR, RESTORE_BACKUP_DIR
from scheduler_service import create_scheduler_service
from xlsx_utils import autosize_worksheet, send_xlsx_workbook

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_h3c_admin_tool_2026'

APP_VERSION = "2.54.5"
APP_RELEASE_DATE = "2026-05-09"
APP_VERSION_INFO = {
    "version": APP_VERSION,
    "release_date": APP_RELEASE_DATE,
    "name": "NetMaster 自动化运维平台",
    "summary": "面向专网环境的多厂商交换机自动化运维工具，重点强化终端绑定、终端漫游、自动备份和审计追踪。",
    "features": [
        "H3C/Huawei 交换机资产管理、连接测试、端口查询和配置保存",
        "ACL 策略组管理、端口 IP/MAC 绑定、解绑和端口描述维护",
        "Excel 批量导入设备与批量绑定，支持同端口多终端聚合下发",
        "终端漫游：定位旧绑定、清理旧端口、部署新端口并更新已绑定终端列表",
        "已绑定终端列表：支持交换机名称展示、CSV 导出、终端更新和冲突保护",
        "配置差异比对：基于本地备份文件对比两次交换机配置变化",
        "任务中心、端口画像、运行健康检查和终端漫游试运行",
        "交换机资产密码本地加密存储，兼容旧明文记录自动迁移",
        "数据备份与恢复：网页导出/导入数据库、密钥和关键清单",
        "离线绑定导入、深度在线健康检查、交换机日志告警采集入库和定时任务可调",
        "每日自动配置备份、备份后保存配置、终端绑定信息定时更新",
        "审计日志和首页看板，支持专网离线运行，无外部 CDN 或远程 API 依赖",
    ],
    "updates": [
        "准入合规分析收紧疑似废弃下线判断：同一 MAC 只要在 IP管理或9200平台存在阈值内近期记录，就不再按废弃下线分流",
        "准入合规分析新增疑似废弃下线判断：IP管理与9200均为超过阈值的旧记录且未入人工台账时优先分流，减少历史残留误报",
        "准入合规分析新增每条风险的判定依据，并同步到页面表格和 CSV 导出",
        "准入合规分析表头支持 IP、MAC、接入设备和更新时间点击排序",
        "同MAC多IP、同IP多MAC在全部类型视图中也显示聚合证据卡片，直接看到关联 IP/MAC",
        "OUI 厂商识别简化为只读取本地 oui.txt，不再提示下载 CSV，保留少量内置常见厂商兜底",
        "OUI 厂商识别兼容 IEEE 根地址保存的 oui.txt",
        "准入合规分析新增离线 OUI 厂商识别：风险表格和组类风险卡片显示 MAC 对应厂商，未知前缀显示无法识别厂商",
        "准入合规分析概要进一步精简，风险类型统计改为可复制文本标签",
        "准入合规分析新增组类风险证据链展示：选择同MAC多IP或同IP多MAC时改为聚合卡片，直观看到关联 IP/MAC、交换机、端口、VLAN 和时间",
        "准入合规分析表格改为前端懒加载，每批渲染 120 条，滚动到底部自动追加，筛选和导出仍基于全量结果",
        "准入合规分析进一步精简：取消参考模板按钮和风险等级列，统一三个平台上传说明，避免与交换机告警等级混淆",
        "准入合规分析风险类型下拉改用全量统计生成，表格最多渲染前 1000 条，筛选和导出仍基于全量风险结果",
        "准入合规分析新增历史记录，可保存每次导入文件、摘要统计和风险明细，便于后续回看与导出",
        "准入合规分析改为默认全量离线分析，不再按时间范围或在线状态跳过导出记录",
        "准入合规分析首页摘要改为可读结论和风险类型分布，隐藏字段识别调试信息，减少无效指标卡片",
        "页面表格和结果区恢复文本选择能力，便于直接复制设备 IP、MAC、端口和准入合规分析结果",
        "准入合规分析放宽 9200 合规判定：保护状态=保护或核心版本包含 9200 即视为合法，不再要求安装状态必须为“是”",
        "准入合规分析三层字段规则落地：IP/MAC 与 9200 状态字段用于判定，责任人、部门、位置、用途、设备类型等只作为风险定位信息展示和导出",
        "准入合规分析风险行会从 9200 或人工台账补充定位字段，便于发现不合规终端后直接找人、找位置、找设备",
        "准入合规分析适配新版群晖固定台账列：rule、设备ip、设备mac、使用/责任人、安装位置、设备用途、设备类型等；比对仍只使用 IP/MAC，定位字段仅随风险结果展示和导出",
        "准入合规分析适配 9200 平台实际 CSV：自动跳过标题行，按“保护状态=保护”或“核心版本包含9200”判定合法终端",
        "准入合规分析适配群晖多工作簿台账：自动识别每个工作簿内表头，支持不同部门工作簿使用不同 MAC 列名",
        "准入合规分析新增 9200 平台和人工审批台账参考模板下载，方便在样本未齐全前先统一字段口径",
        "准入合规分析页面新增风险等级、风险类型、关键词筛选，并支持将当前分析结果导出为 CSV 报告",
        "新增准入合规分析第一版：支持上传 IP 地址管理平台 CSV/XLSX，自动识别 IP、MAC、接入交换机、端口、VLAN、在线状态和最近上线时间",
        "准入合规分析支持可选上传 9200 平台与人工审批台账，预留未安装 9200、未报备入网、IP-MAC 不符、同 IP 多 MAC、同 MAC 多 IP 等风险识别",
        "准入合规分析页面采用本地文件上传和离线计算，不读取交换机，不增加交换机运行负载",
        "运行环境收尾：requirements.txt 移除本机 file:/// 构建路径依赖，packaging 改为标准版本锁定，并补充 openpyxl",
        "源码目录清理：历史源码备份目录已打包归档到上级目录，项目目录仅保留运行数据和当前源码",
        "版本信息弹窗精简为版本摘要、核心能力和最近变化，完整记录保留在 Markdown 维护日志",
        "帮助页改为首屏内置说明，完整 USER_GUIDE.md 通过页面底部按钮按需加载",
        "安全收口：删除旧 add_user.py 旁路脚本，用户创建统一通过 Web 用户管理完成",
        "页面 QA 小修：运维操作员隐藏系统设置内容容器，与左侧菜单和后端权限保持一致",
        "用户/权限复核：运行任务接口补 task.view，深度在线健康检查补 access.write，并增加越权回归检查",
        "terminal_sync_service.py 接管终端漫游主动定位使用的全网扫描和单台扫描包装",
        "terminal_sync_service.py 接管终端绑定同步全网/单台任务编排主流程",
        "terminal_sync_service.py 接管终端同步单台设备审计日志格式化逻辑",
        "terminal_sync_service.py 接管单台交换机终端绑定同步包装和超时读取后的持久化分派",
        "terminal_sync_service.py 接管终端绑定同步状态容器，app.py 保留锁和状态访问包装以兼容蓝图注入",
        "新增 offline_binding_service.py，抽离从本地备份配置解析并导入终端绑定记录的逻辑",
        "terminal_sync_service.py 继续接管终端绑定记录归一、持久化统计和查询匹配逻辑",
        "新增 terminal_sync_service.py，抽离终端绑定同步中的子进程读取和超时保护逻辑",
        "新增 alarm_service.py，抽离告警日志文本分析、告警排查命令建议和交换机告警采集封装",
        "新增 legacy_asset_service.py，抽离旧版 net_assets.db 上传解析、旧密钥读取、旧密码解密和资产导入汇总逻辑",
        "新增 data_package_service.py，抽离完整数据包导出、导入、预览和当前库备份逻辑",
        "新增 backup_file_service.py，抽离本地备份文件路径解析、列表读取和备份天数统计，继续推进 app.py 服务层整理",
        "全页面收尾前完成源码备份，并继续收紧资产导入、数据备份、ACL、端口绑定、终端漫游和改密弹窗的零散按钮",
        "端口画像风险规则细化，增加离线仍绑定、多终端、双/多 VLAN、模式混用、缺少描述和超期巡检权重",
        "资产导入与数据备份区域按钮继续收窄为小尺寸图标按钮，并补充 tooltip",
        "端口画像超期处理入口改名为标记巡检，强调只更新本地巡检记录，不代表故障已修复",
        "端口画像新增风险/状态/搜索筛选和超期确认入口，确认操作只更新本地确认时间并写入审计，不登录交换机",
        "配置差异结果新增轻量摘要，突出新增/删除行数和主要变化类别，避免重新堆叠设备备份状态",
        "Excel 批量部署操作按钮继续收窄为模板、解析预览、一键下发三类明确动作",
        "修复 HuaweiManager.get_port_info 解析代码位置错误，恢复华为设备端口详情和绑定记录返回",
        "恢复近 30 天终端变动完整日期轴，保留无数据日期并弱化显示，避免趋势图缺少日期上下文",
        "新增 validators.py，抽离 IP、端口、VLAN、厂商、角色、MAC、模式、ACL 和密码策略校验函数",
        "调度器蓝图化配套拆分：新增 scheduler_service.py 接管自动备份、终端同步、数据包导出、日志告警采集和 APScheduler 装配",
        "新增 runtime_paths.py，支持通过 NETMASTER_DATA_DIR 外置数据库、密钥、备份和数据包目录；默认仍保持当前目录兼容",
        "继续蓝图拆分：新增 auth_pages.py 接管登录和退出页面路由，app.py 仅保留首页入口和启动调度逻辑",
        "Dashboard 视觉统一：侧栏收窄减重、KPI 卡片压缩、最近绑定变更改为标准表格、趋势图减少无效日期噪声",
        "桌面端左侧菜单改为 fixed left:0，彻底贴齐浏览器左边；首页趋势图和圆环图增加固定图形区与图例区，避免文字遮挡",
        "侧栏和主容器样式选择器提权为 body 直属容器，清除 Bootstrap/Tabler 容器 gutter 干扰；登录页和首页样式表统一增加版本缓存参数",
        "侧栏内部左 padding 清零并给主样式表增加版本参数，确保浏览器加载最新左侧菜单样式",
        "清除浏览器默认 body margin，修复左侧菜单仍有顽固空白的问题",
        "强制清除 Bootstrap container 左侧 gutter/margin，左侧菜单真正贴齐页面左边",
        "左侧侧边栏取消左侧留白并贴左显示，保留右侧圆角；Tabler fluid vertical layout 完整改造纳入后续收尾任务池",
        "左侧菜单改为 Tabler 风格圆角独立侧边栏，收紧宽度和留白，品牌区改为满宽 header 面板",
        "数据备份页面新增配置备份任务模块，提供批量备份配置按钮并继续使用后台任务执行",
        "左侧菜单收紧内边距并彻底移除底部批量备份侧栏按钮，避免 90% 缩放时露出重复入口",
        "页面顶部留白从 12px 收紧到 6px，保留页头上边框可见性",
        "Waitress 线程数提升到 16 并增加连接队列容量，减少刷新页面时的 queue depth 提示；页面顶部增加留白以显示页头上边框",
        "页头信息胶囊改为当前页面名称，并修复页头上边框视觉不明显的问题",
        "全局页头增加轻量中控信息带和柔和背景，改善压缩后过扁的问题",
        "全局页头压缩：版本号移动到标题右侧，移除标题下方描述文字，减少页面顶部留白",
        "任务池 1-4 推进：端口画像接入 SNMP 单端口刷新和维护建议，批量备份/深度健康检查/日志采集新增后台任务启动入口，配置差异新增接口/VLAN/绑定/ACL/路由/管理服务分类统计",
        "新增 SNMP 轻量端口状态查询接口和系统设置项，默认只读团体名为 suyuga0527；端口查询先读 SNMP 状态，再用 SSH 读取配置级绑定详情",
        "端口 IP+MAC 绑定页选择快捷交换机后自动加载端口列表，减少手动刷新步骤；端口快照策略调整为先保留按需触发，后续优先评估 SNMP 轻量实时状态采集",
        "终端漫游目标端口接入缓存快照展示和资产凭据实时复核任务，迁移前可先看缓存再做实时确认",
        "新增端口快照表和后台采集接口，支持按单台交换机或明确全量方式采集端口缓存",
        "端口实时查询改为后台任务启动和轮询进度反馈，选中端口后不再长时间占用前端请求",
        "新增后台任务基础框架和运行中任务查询接口，为端口实时查询、健康检查、备份等耗时操作后台化打底",
        "新增独立终端列表页面，保留终端漫游页简化源终端选择列表，支持全网筛选、异常筛选、导出和带入漫游",
        "清理 app.py 关键分区乱码注释，降低后续维护成本",
        "冒烟脚本写接口边界验证改为临时屏蔽审计写入，避免测试失败记录污染正式审计日志",
        "新增 blueprints.profile_health，迁移端口画像和深度在线健康检查接口；改密接口归入用户管理蓝图",
        "新增 blueprints.terminal_state，迁移终端绑定同步、同步状态和已绑定终端列表接口",
        "新增 blueprints.excel_manage，迁移 Excel 模板、解析、聚合下发和单行下发接口",
        "新增 blueprints.roam_manage，迁移终端定位和终端迁移接口，继续收缩 app.py 写操作体积",
        "新增 blueprints.access_manage，迁移端口描述、端口绑定/解绑和 ACL 查询/新增/删除接口",
        "新增 blueprints.switch_connect，迁移连接测试、接口列表、端口详情和保存配置接口",
        "新增 blueprints.alarm_read，迁移告警报表和告警中心 Dashboard 只读接口",
        "新增 blueprints.alarm_manage，迁移告警日志采集和告警状态更新写接口，并补齐采集接口 alarm.manage 权限",
        "扩展轻量回归验收脚本，增加本地 Tabler 资源、关键菜单、审计/备份接口和运维操作员权限入口检查",
        "统一资产管理、任务中心、审计日志和资产导入预校验表格按钮与状态样式，新增轻量回归验证脚本",
        "用户管理页面新增角色权限说明和权限概览列，系统级入口按管理员权限隐藏",
        "新增 blueprints.backup_manage，迁移数据包导入导出、旧版资产导入、离线绑定导入和手动批量备份接口",
        "审计日志页面操作人、动作类型、目标 IP 筛选改为选择控件，减少手工输入误差",
        "新增 blueprints.asset_manage，迁移资产导出、资产导入预校验/导入、新增、删除、修改和元数据更新接口",
        "资产导出文件补充角色列，和资产导入模板保持一致",
        "左侧菜单用户管理入口图标改为人形图标，避免与横线/列表图标混淆",
        "新增 blueprints.user_manage，迁移用户新增、修改和重置密码写接口",
        "新增 blueprints.system_manage，迁移系统设置写接口 /api/settings/update",
        "权限点细化：新增 system.manage，保护系统设置写入和调度器重载",
        "权限点细化：新增 user.manage、asset.export_sensitive、backup.manage，分别保护用户管理、含密码资产导出和备份管理操作",
        "asset_user_read 蓝图中的用户列表读取改用 user.manage 权限点",
        "新增 blueprints.asset_user_read，迁移资产列表、资产导入模板和用户列表读取接口",
        "修复设备批量导入解析角色列：模板填写 backup 时按备份设备导入，不填仍默认 access",
        "页面右上角移除重复的数据备份按钮，仅保留左侧菜单入口",
        "新增 blueprints.info_read，迁移版本信息、Dashboard 统计、健康检查和系统设置读取接口",
        "Dashboard 绑定变更列表最终样式固化：全宽单行、源/目的标签、普通字体和紧凑行高",
        "Dashboard 绑定变更行视觉增强：收紧列间距、增强行边界，并为源/目的交换机列增加醒目标识",
        "Dashboard 最近 10 次绑定变更去掉每列下方重复说明小字，只保留横向主信息",
        "Dashboard 最近 10 次绑定变更模块改为整行全宽显示，每次变更占用水平完整一行，字段不再在半屏窄栏内换行",
        "Dashboard 最近 10 次绑定变更恢复为纵向列表样式，避免卡片/多列布局导致字段显示不全",
        "左侧菜单调整：任务中心移到告警中心下方并归入总览与告警组，任务与审计分组取消",
        "左侧菜单管理设备改名为资产管理，审计日志归入管理设置组",
        "配置差异页面移除设备备份状态卡片区，保留交换机下拉一键比对和手动新旧配置比对",
        "管理设备页面顶部导入和手动新增区域改为紧凑双列布局，减少无效留白",
        "设备导入模板新增角色列，支持 access/backup；不填角色仍默认按 access 导入",
        "backup 只读/比对接口迁移到 blueprints.backup_read，继续推进 app.py 低风险蓝图拆分",
        "audit/task 路由迁移到 blueprints.audit_task，完成首个低风险蓝图拆分",
        "权限点细化到 access.write、roam.write、alarm.manage，并保护对应端口准入、终端漫游和告警处理接口",
        "用户管理新增角色/状态筛选和最近登录排序",
        "ACL、告警中心、终端列表等表格按钮继续统一为图标按钮加 tooltip",
        "配置差异页面新增按设备卡片化聚合展示最近备份状态，并可点击比对最近两次备份",
        "配置差异比对页移除设备聚合快捷按钮区，仅保留交换机下拉一键比对入口",
        "配置差异比对的一键比对入口改为快捷选择交换机，避免手填 IP 出错",
        "下一阶段改造：用户管理拆成独立页面，数据备份拆成完整数据包、旧版资产导入、资产导入导出三块",
        "端口画像新增端口绑定终端明细下钻，配置差异新增按设备聚合的最近备份状态入口",
        "权限第二阶段建立 permission_required 基座，关键资产维护、交换机下发、审计查看和任务查看接口按权限点保护",
        "新增 blueprints 目录和拆分计划，开始为 app.py 蓝图化拆分做准备",
        "终端漫游 Step 2 右侧新增保存配置按钮，可对目标交换机手动执行 save force",
        "按优先级完成安全与体验增强：旧版资产导入前自动备份当前 DB/KEY，便于回滚",
        "页面剩余浏览器原生 alert 已收口为 Tabler Toast，统一提示体验",
        "Dashboard 顶部指标和看板模块支持点击下钻到管理设备、备份差异、告警中心、任务中心和端口画像",
        "管理设备导入新增预校验接口与页面报告，Excel 批量部署解析后展示行数、交换机数、端口任务数和重复记录",
        "端口画像升级为端口风险画像，按高密度、多 VLAN、Trunk、模式混用和超期确认计算风险分",
        "配置差异新增按交换机 IP 一键比对最近两次备份",
        "审计日志新增操作人、动作、目标 IP、状态和日期过滤，并支持 CSV 导出",
        "任务中心长详情改为详情按钮查看，减少表格横向拥挤",
        "保存配置按钮从页面右上角移动到设备连接与管理模块，紧邻连接测试按钮，降低误操作风险",
        "整理下一阶段改进清单：Dashboard 下钻、端口风险画像、配置差异一键比对、任务/审计普通页面和权限细化",
        "登录页改为更适配 1080p 的 Tabler 大尺寸卡片，并统一 NETMASTER 品牌标识",
        "管理设备导入和 Excel 批量部署新增本地 xlsx 模板下载，离网环境无需外部依赖",
        "Tabler 交互收口第二批：保存配置、端口绑定/解绑、ACL 删除、终端漫游和 Excel 批量下发改为统一确认弹窗",
        "告警处理备注和用户重置密码改为统一输入弹窗，减少浏览器原生 prompt",
        "Tabler 风格交互增强：新增统一 Toast 和高风险操作确认弹窗",
        "删除设备、含密码资产导出、完整数据包导入、旧版资产导入和批量备份改为统一确认流程",
        "账号安全增强：连续登录失败 5 次临时锁定 10 分钟，密码统一要求至少 8 位且包含字母和数字",
        "用户管理增加最后一个启用系统管理员保护，避免误禁用或降级导致无人可管理系统",
        "新增两级用户角色：系统管理员和运维操作员，系统设置、数据备份恢复和用户管理仅管理员可操作",
        "系统设置页新增用户管理，可新增用户、调整角色/状态、重置密码",
        "设备资产编辑修复空密码覆盖风险，密码留空时保留原密码",
        "设备资产导出拆分为普通资产清单和含密码敏感导出，敏感导出仅系统管理员可用并写入审计",
        "数据备份页面新增旧版本资产导入：可从旧 net_assets.db 读取 switches 表并导入交换机资产",
        "Tabler 左侧菜单信息架构调整：设备准入、管理设置分组重新排序",
        "首页 Dashboard 指标继续优化：备份天数、全量保存配置时间、本月绑定变更和最近绑定明细",
        "终端漫游页终端列表支持按当前接入交换机过滤，未选择交换机时才显示全部绑定终端",
        "版本信息弹窗聚焦版本说明，定时备份成功后自动保存开关统一收口到系统设置页",
        "侧边栏品牌标识改为 NETMASTER，并去除重复品牌文字",
        "告警中心新增确认/忽略/备注闭环、近 7 天趋势和状态筛选，顶部重复告警按钮已移除",
        "日志分类修正：SOFTCAR ARP DROP 单独归为 ARP限速/控制平面保护，不再误归 ACL/丢包",
        "首页看板新增当前网络告警卡片，直接展示高危/中风险/采集失败并可打开告警中心",
        "新增告警中心：按设备最新告警聚合、风险排序、Top 优先处理、筛选和折叠原始日志",
        "最近日志分析支持默认折叠查看匹配原始日志，并去除高频端口重复展示",
        "日志告警分析修正：SSH 成功登录/退出不再误判为认证异常，健康检查摘要改为紧凑排版",
        "日志告警分析增强：支持风险评分、风险等级、分类统计、高频端口提取和更细的处置建议",
        "运行健康检查中的任务调度时间改为紧凑时间卡片，任务中心终端更新名称改为汇总/单台设备并优化摘要排序",
        "离线导入预览新增唯一终端和重复记录统计，日志告警支持每日定时采集、分析入库和网页查看",
        "新增离线导入绑定库、深度在线健康检查、交换机日志告警分析、定时任务时间可调和自动数据包导出",
        "新增数据备份/恢复：导出 net_assets.db、net_assets.key、交换机资产清单和已绑定终端清单",
        "新增任务中心、端口画像、运行健康检查、终端漫游试运行、可调系统参数和资产密码本地加密",
        "新增配置差异比对页签，可选择两份本地备份文件查看新增/删除配置行",
        "ACL 管理升级：支持查询交换机全部 ACL 策略组，并可按 ACL 组号维护 MAC 规则",
        "新增系统设置：可控制定时备份成功后是否自动保存设备配置",
        "README 更新为当前离线专网版本说明，并标注后续优化路线",
        "管理设备列表新增按名称、角色、厂商、IP 排序，并支持直接修改设备参数",
        "简化资产角色模型：接入交换机参与终端更新，备份设备只参与配置备份",
        "已绑定终端列表新增搜索、模式筛选、同 IP 多 MAC 和同 MAC 多位置筛选",
        "新增网页可见版本信息入口，集中展示当前版本功能和更新内容",
        "终端列表新增交换机名称列和 CSV 导出功能",
        "终端更新改为发现/新增/更新/未变统计，未变记录刷新确认时间",
        "修正默认 VLAN 1 解析，未显式配置 VLAN 的接入口按 VLAN 1 入库",
        "终端漫游新增 IP 冲突保护、旧端口解绑复核和新端口差异化部署",
        "终端更新采用子进程隔离和并发扫描，减少超时残留并提升速度",
        "定时备份后自动保存配置，并记录每台设备保存结果",
        "首页设备连接区压缩布局，减少快捷连接区域留白",
    ],
    "backup": "project_backup_20260501_114009",
}

# 关键端口保护关键词，不区分大小写。
# 端口描述包含这些词时，系统拒绝修改，避免误操作上联、核心和互联端口。
PROTECTED_KEYWORDS = ['Uplink', 'Trunk', 'Core', 'Connect', 'To', 'hexin', 'huiju', 'link']

# 备份文件存放目录
BACKUP_ROOT = str(BACKUP_DIR)
os.makedirs(BACKUP_ROOT, exist_ok=True)

MAC_SYNC_SWITCH_TIMEOUT = 90
MAC_SYNC_MAX_WORKERS = 4
MAC_SYNC_STATE_STORE = MacSyncStateStore()
MAC_SYNC_LOCK = MAC_SYNC_STATE_STORE.lock

# 登录管理器配置
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth_pages.login'

class User(UserMixin):
    def __init__(self, id, username, role='operator', display_name=''):
        self.id = id
        self.username = username
        self.role = role or 'operator'
        self.display_name = display_name or username

    @property
    def is_admin(self):
        return self.role == 'admin'

@login_manager.user_loader
def load_user(user_id):
    user_data = db.get_user_by_id(user_id)
    if user_data:
        return User(
            id=user_data['id'],
            username=user_data['username'],
            role=user_data['role'] if 'role' in user_data.keys() else 'operator',
            display_name=user_data['display_name'] if 'display_name' in user_data.keys() else user_data['username'],
        )
    return None


def admin_required(func):
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not getattr(current_user, 'is_admin', False):
            if request.path.startswith('/api/'):
                return json_error('当前账号无系统管理员权限', 403)
            abort(403)
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


ROLE_PERMISSIONS = {
    'admin': {'*'},
    'operator': {
        'switch.write',
        'access.write',
        'roam.write',
        'alarm.manage',
        'asset.manage',
        'audit.view',
        'task.view',
        'backup.view',
    },
}


def has_permission(permission):
    if not current_user.is_authenticated:
        return False
    perms = ROLE_PERMISSIONS.get(getattr(current_user, 'role', 'operator'), set())
    return '*' in perms or permission in perms


def permission_required(permission):
    def decorator(func):
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if not has_permission(permission):
                if request.path.startswith('/api/') or request.path.startswith(('/get_', '/set_', '/bind_', '/del_', '/save_', '/batch_', '/test_')):
                    return json_error(f'当前账号缺少权限：{permission}', 403)
                abort(403)
            return func(*args, **kwargs)
        wrapper.__name__ = func.__name__
        return wrapper
    return decorator

# 交换机驱动和通用辅助函数
def get_manager(data):
    port = int(data.get('port', 22)) 
    # 优先使用请求中的厂商；未提供时按 IP 从资产库读取。
    vendor = data.get('vendor')
    if not vendor:
        target_sw = db.get_switch_by_ip(data['ip'])
        vendor = target_sw.get('vendor', 'h3c') if target_sw else 'h3c'
        
    # 根据厂商选择对应驱动。
    if vendor.lower() == 'huawei':
        return HuaweiManager(data['ip'], data['user'], data['pass'], port)
    return H3CManager(data['ip'], data['user'], data['pass'], port)


def json_error(message, status_code=400):
    return jsonify({'status': 'error', 'msg': message}), status_code


def get_json_data():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('请求体必须为 JSON 对象')
    return data


def get_runtime_settings():
    return db.get_system_settings()


def get_mac_sync_timeout():
    return int(get_runtime_settings().get('mac_sync_timeout') or MAC_SYNC_SWITCH_TIMEOUT)


def get_mac_sync_max_workers():
    return int(get_runtime_settings().get('mac_sync_max_workers') or MAC_SYNC_MAX_WORKERS)


def get_protected_keywords():
    text = str(get_runtime_settings().get('protected_keywords') or '').strip()
    if not text:
        return PROTECTED_KEYWORDS
    return [item.strip() for item in text.replace('\n', ',').split(',') if item.strip()]


def format_switch_log(raw_log):
    if isinstance(raw_log, bytes):
        text = raw_log.decode('utf-8', errors='ignore')
    elif raw_log is None:
        text = '> [System] 配置指令已成功发送（底层函数未返回详细回显）'
    else:
        text = str(raw_log)
    return text.replace('<', '&lt;').replace('>', '&gt;')


def csv_text(headers, rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, '') for key in headers})
    return '\ufeff' + buffer.getvalue()

def get_switch_runtime_data(switch_ip):
    target_sw = db.get_switch_by_ip(switch_ip)
    if not target_sw:
        raise ValueError(f"资产管理库未登记该 IP（{switch_ip}），无法获取设备凭据")
    return {
        'ip': switch_ip,
        'user': target_sw['username'],
        'pass': target_sw['password'],
        'port': target_sw['port'],
        'vendor': target_sw.get('vendor', 'h3c'),
    }


def assert_interface_not_protected(mgr, interface_name):
    info, raw = mgr.get_port_info(interface_name)
    info['_raw_config'] = raw
    desc = info.get('description', '')
    for kw in get_protected_keywords():
        if kw.lower() in desc.lower():
            raise ValueError(f"拒绝执行：该端口描述包含受保护关键字 '{kw}'")
    return info


def normalize_terminal_lookup(query):
    text = str(query or '').strip()
    if not text:
        raise ValueError('请输入 MAC 地址或 IP 地址')
    try:
        return 'ip', normalize_ip(text, '查询 IP')
    except ValueError:
        return 'mac', normalize_mac(text, '查询 MAC')


def get_terminal_binding_record(query, source_switch_ip=None):
    query_type, value = normalize_terminal_lookup(query)
    if source_switch_ip:
        source_switch_ip = normalize_ip(source_switch_ip, '源交换机 IP')
    if query_type == 'ip':
        rows = db.get_bindings_by_ip(value, source_switch_ip)
        if not rows:
            raise ValueError('已绑定终端列表中未找到该终端的绑定记录')
        macs = sorted({normalize_mac(row.get('mac_address', '')) for row in rows})
        if len(macs) > 1:
            details = '; '.join(
                f"{row.get('mac_address')} @ {row.get('switch_ip')} {row.get('port')}"
                for row in rows[:8]
            )
            raise ValueError(
                f"同一 IP {value} 在已绑定终端列表中存在 {len(macs)} 个不同 MAC，不能按 IP 自动迁移。"
                f"请改用明确的 MAC 地址定位，或先清理冲突绑定：{details}"
            )
        binding = rows[0]
    elif query_type == 'mac' and source_switch_ip:
        binding = db.get_mac_binding_on_switch(value, source_switch_ip)
    else:
        binding = db.get_mac_binding(value)
    if not binding:
        raise ValueError('已绑定终端列表中未找到该终端的绑定记录')
    return binding


def assert_no_ip_conflict(ip_address, selected_mac):
    rows = db.get_bindings_by_ip(ip_address)
    conflicts = [
        row for row in rows
        if normalize_mac(row.get('mac_address', '')) != normalize_mac(selected_mac)
    ]
    if conflicts:
        details = '; '.join(
            f"{row.get('mac_address')} @ {row.get('switch_ip')} {row.get('port')}"
            for row in conflicts[:8]
        )
        raise ValueError(
            f"检测到同一 IP {ip_address} 还绑定到其他 MAC，已拒绝迁移以避免残留冲突。"
            f"请先确认并删除冲突绑定，或改用正确 MAC 重新定位。冲突记录：{details}"
        )


def port_has_binding(mgr, interface_name, ip_address, mac_address):
    info, _ = mgr.get_port_info(interface_name)
    target_ip = normalize_ip(ip_address, '绑定 IP')
    target_mac = normalize_mac(mac_address, '绑定 MAC')
    for binding in info.get('bindings', []):
        try:
            if (
                normalize_ip(binding.get('ip'), '绑定 IP') == target_ip
                and normalize_mac(binding.get('mac'), '绑定 MAC') == target_mac
            ):
                return True
        except ValueError:
            continue
    return False


def save_binding_state(switch_ip, interface_name, vlan, bind_ip, mac, mode):
    return db.upsert_mac_binding(
        mac_address=normalize_mac(mac),
        ip_address=normalize_ip(bind_ip, '绑定 IP'),
        switch_ip=normalize_ip(switch_ip, '交换机 IP'),
        port=str(interface_name).strip(),
        vlan=str(vlan or '').strip(),
        mode=normalize_mode(mode),
    )


def persist_switch_bindings(switch_row, all_bindings, query_type=None, query_value=None):
    return service_persist_switch_bindings(
        switch_row,
        all_bindings,
        save_binding_state,
        query_type,
        query_value,
    )


def sync_switch_bindings(switch_row, query_type=None, query_value=None):
    return service_sync_switch_bindings(
        switch_row,
        get_manager,
        persist_switch_bindings,
        query_type,
        query_value,
    )


def sync_all_switch_bindings(query_type=None, query_value=None):
    return service_sync_all_switch_bindings(
        db,
        sync_switch_bindings_with_timeout,
        query_type,
        query_value,
    )


def scan_one_switch_for_terminal(source_switch_ip, query):
    return service_scan_one_switch_for_terminal(
        db,
        source_switch_ip,
        query,
        normalize_ip,
        normalize_terminal_lookup,
        sync_switch_bindings_with_timeout,
    )


def read_switch_bindings_with_timeout(sw, timeout=None):
    timeout = timeout or get_mac_sync_timeout()
    return service_read_switch_bindings_with_timeout(sw, timeout)


def sync_switch_bindings_with_timeout(sw, query_type=None, query_value=None, timeout=None):
    timeout = timeout or get_mac_sync_timeout()
    return service_sync_switch_bindings_with_timeout(
        sw,
        lambda switch_row: read_switch_bindings_with_timeout(switch_row, timeout),
        persist_switch_bindings,
        query_type,
        query_value,
    )


def update_mac_sync_state(**kwargs):
    return MAC_SYNC_STATE_STORE.update(**kwargs)


def get_mac_sync_state_snapshot():
    return MAC_SYNC_STATE_STORE.snapshot()


def log_mac_sync_switch_result(actor, client_ip, sw, result=None, error=None):
    return service_log_mac_sync_switch_result(db, actor, client_ip, sw, result, error)


def run_mac_bindings_sync(actor, client_ip, switch_ip=''):
    return service_run_mac_bindings_sync(
        actor,
        client_ip,
        switch_ip,
        MAC_SYNC_LOCK,
        MAC_SYNC_STATE_STORE,
        db,
        normalize_ip,
        sync_switch_bindings_with_timeout,
        read_switch_bindings_with_timeout,
        persist_switch_bindings,
        log_mac_sync_switch_result,
        get_mac_sync_max_workers,
    )


def internal_error(message, exc):
    error_id = datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')
    try:
        app.logger.error('internal_error[%s] %s: %s', error_id, message, exc, exc_info=True)
    except Exception:
        traceback.print_exc()
    payload = {'status': 'error', 'msg': message, 'error_id': error_id}
    if app.debug:
        payload['debug'] = str(exc)
    return jsonify(payload), 500

app.register_blueprint(create_audit_task_blueprint(db, permission_required, internal_error, csv_text))
app.register_blueprint(create_alarm_manage_blueprint(
    db,
    get_json_data,
    normalize_ip,
    lambda switch_ip: service_collect_switch_alarm_report(db, get_manager, get_switch_runtime_data, switch_ip),
    json_error,
    internal_error,
    permission_required,
))
app.register_blueprint(create_alarm_read_blueprint(
    db,
    build_alarm_command_suggestions,
    internal_error,
))
app.register_blueprint(create_backup_read_blueprint(
    list_backup_config_files,
    read_backup_text,
    get_json_data,
    require_fields,
    normalize_ip,
    json_error,
    internal_error,
    permission_required,
))
app.register_blueprint(create_backup_manage_blueprint(
    db,
    H3CManager,
    HuaweiManager,
    BACKUP_ROOT,
    lambda: service_create_data_package(db, APP_VERSION),
    lambda upload: service_restore_data_package(db, RESTORE_BACKUP_DIR, upload),
    service_preview_data_package,
    lambda reason='manual': service_backup_current_db_key(db, RESTORE_BACKUP_DIR, reason),
    lambda upload, key_storage=None, apply=False: service_import_legacy_switch_assets(db, RESTORE_BACKUP_DIR, upload, key_storage, apply),
    lambda limit=2000, apply=False: service_import_bindings_from_backup_files(
        list_backup_config_files,
        read_backup_text,
        save_binding_state,
        limit,
        apply,
    ),
    get_json_data,
    json_error,
    internal_error,
    permission_required,
))
app.register_blueprint(create_info_read_blueprint(
    db,
    APP_VERSION_INFO,
    count_backup_days,
    list_backup_config_files,
    internal_error,
    admin_required,
))
app.register_blueprint(create_auth_pages_blueprint(db, User))

# 页面路由

@app.route('/')
@login_required 
def index():
    return render_template(
        'index.html',
        username=current_user.username,
        user_role=current_user.role,
        is_admin=current_user.is_admin,
    )


app.register_blueprint(create_asset_user_read_blueprint(
    db,
    send_xlsx_workbook,
    autosize_worksheet,
    internal_error,
    permission_required,
))
app.register_blueprint(create_asset_manage_blueprint(
    db,
    get_json_data,
    require_fields,
    normalize_ip,
    normalize_port,
    normalize_vendor,
    normalize_switch_role,
    json_error,
    internal_error,
    permission_required,
    has_permission,
))
app.register_blueprint(create_user_manage_blueprint(
    db,
    get_json_data,
    require_fields,
    validate_password_policy,
    json_error,
    internal_error,
    permission_required,
))
app.register_blueprint(create_switch_connect_blueprint(
    db,
    get_json_data,
    require_fields,
    normalize_ip,
    normalize_port,
    normalize_vendor,
    get_manager,
    json_error,
    internal_error,
    permission_required,
))
app.register_blueprint(create_access_manage_blueprint(
    db,
    get_json_data,
    require_fields,
    normalize_ip,
    normalize_port,
    normalize_vendor,
    normalize_mac,
    normalize_mode,
    normalize_vlan,
    normalize_acl_number,
    get_manager,
    assert_interface_not_protected,
    save_binding_state,
    format_switch_log,
    json_error,
    internal_error,
    permission_required,
))
app.register_blueprint(create_roam_manage_blueprint(
    db,
    get_json_data,
    require_fields,
    normalize_ip,
    normalize_mac,
    normalize_mode,
    normalize_vlan,
    get_terminal_binding_record,
    get_mac_sync_state_snapshot,
    MAC_SYNC_LOCK,
    scan_one_switch_for_terminal,
    normalize_terminal_lookup,
    sync_all_switch_bindings,
    assert_no_ip_conflict,
    get_switch_runtime_data,
    get_manager,
    assert_interface_not_protected,
    port_has_binding,
    save_binding_state,
    format_switch_log,
    json_error,
    internal_error,
    permission_required,
))
app.register_blueprint(create_excel_manage_blueprint(
    db,
    get_json_data,
    require_fields,
    normalize_ip,
    normalize_mac,
    normalize_mode,
    normalize_vlan,
    get_switch_runtime_data,
    get_manager,
    assert_interface_not_protected,
    save_binding_state,
    format_switch_log,
    send_xlsx_workbook,
    autosize_worksheet,
    json_error,
    internal_error,
    permission_required,
))
app.register_blueprint(create_terminal_state_blueprint(
    db,
    normalize_ip,
    get_json_data,
    get_mac_sync_state_snapshot,
    MAC_SYNC_LOCK,
    run_mac_bindings_sync,
    json_error,
    internal_error,
    permission_required,
))
app.register_blueprint(create_profile_health_blueprint(
    db,
    get_json_data,
    get_manager,
    internal_error,
    permission_required,
))
app.register_blueprint(create_task_runtime_blueprint(permission_required))
app.register_blueprint(create_snmp_status_blueprint(
    db,
    get_json_data,
    require_fields,
    normalize_ip,
    json_error,
    internal_error,
    permission_required,
))
app.register_blueprint(create_port_snapshot_blueprint(
    db,
    get_json_data,
    normalize_ip,
    get_switch_runtime_data,
    get_manager,
    json_error,
    internal_error,
    permission_required,
))
app.register_blueprint(create_compliance_analysis_blueprint(internal_error))


scheduler_service = create_scheduler_service(
    db=db,
    h3c_manager_cls=H3CManager,
    huawei_manager_cls=HuaweiManager,
    backup_root=BACKUP_ROOT,
    write_data_package_to_dir=lambda target_dir=None: service_write_data_package_to_dir(db, APP_VERSION, DATA_PACKAGE_DIR, target_dir),
    run_mac_bindings_sync=run_mac_bindings_sync,
    collect_switch_alarm_report=lambda switch_ip: service_collect_switch_alarm_report(db, get_manager, get_switch_runtime_data, switch_ip),
)
configure_scheduler = scheduler_service['configure_scheduler']
start_scheduler = scheduler_service['start_scheduler']


app.register_blueprint(create_system_manage_blueprint(
    db,
    get_json_data,
    json_error,
    internal_error,
    permission_required,
    configure_scheduler,
))

start_scheduler()
# ============================================



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)

