# Tabler 1.4.0 本地资源

本目录保存 NetMaster UI 改造使用的 Tabler 编译后静态资源。

来源：

```text
https://cdn.jsdelivr.net/npm/@tabler/core@1.4.0/dist/css/tabler.min.css
https://cdn.jsdelivr.net/npm/@tabler/core@1.4.0/dist/js/tabler.min.js
```

用途：

- 保证专网/离线环境下无需访问外部 CDN。
- `templates/index.html` 和 `templates/login.html` 本地加载 Tabler 样式。
- NetMaster 专用适配样式继续放在 `static/css/netmaster-tabler.css`。

维护提醒：

- 如需升级 Tabler，请新建版本目录，不要直接覆盖本目录。
- 升级后需要重新验证 Bootstrap 组件、Modal、Tab、Dropdown 和现有业务 JS。
