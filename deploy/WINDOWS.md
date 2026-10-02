# TK_APS Windows 部署与维护手册

> 适用版本：v11（React 前端 + FastAPI 后端 + SQLite）
> 架构一句话：**一个 Python 进程**（`uv run cli.py serve`）同时提供网页和 API；数据全部在 `data/` 目录；爬虫用有头浏览器（需要桌面会话，不能做成系统服务）

---

## 1. 你需要准备的东西

| 项目 | 说明 |
|---|---|
| Windows 机器 | 常开的普通电脑或服务器即可，Win10/11 都行；建议 8G 内存以上 |
| 网络 | 能访问 `fastmoss.com`（国内直连）和 `zenmux.ai`（不通则配 `.env` 的 `HTTPS_PROXY`） |
| FastMoss 账号 | 专门注册一个，手机号+密码填到 `.env`（登录过期时自动登录） |
| ZenMux API Key | 一个 Key 同时用于脚本生成（LLM）和视频生成，账户需有余额 |
| 远程桌面 | 你自己的电脑连 Windows 机器用（RDP），首次登录 FastMoss 和排查爬虫问题需要 |

---

## 2. 首次部署（约 20 分钟）

以下命令都在 Windows 机器的 **PowerShell** 里执行。

### 2.1 安装 uv（Python 管理器，会自动装 Python 3.12，不动系统 Python）

```powershell
irm https://astral.sh/uv/install.ps1 | iex
# 关掉 PowerShell 重开一个，验证：
uv --version
```

### 2.2 拿到项目代码

```powershell
# 方式 A：git（推荐）
git clone <你的仓库地址> C:\tk-aps
# 方式 B：直接从 Mac 拷贝整个项目目录到 C:\tk-aps（注意拷贝时排除 node_modules）
```

### 2.3 安装依赖 + 浏览器内核

```powershell
cd C:\tk-aps
uv sync                        # Python 依赖（含 playwright、fastapi 等）
uv run playwright install chromium   # 爬虫用的浏览器内核，约 150MB
```

> 前端页面是构建好的静态文件（`frontend/dist/`），**Windows 上不需要安装 Node**。只有改前端代码时才需要（见 6.4）。

### 2.4 配置密钥

复制 `.env.example` 为 `.env`，填写：

```ini
ZENMUX_API_KEY=sk-ai-v1-xxx        # ZenMux 的 Key（脚本和视频共用）
FASTMOSS_PHONE=138xxxxxxxx         # FastMoss 手机号
FASTMOSS_PASSWORD=xxxxxx           # FastMoss 密码
WEB_USERNAME=admin                 # 网页登录账号
WEB_PASSWORD=xxxxxx                # 网页登录密码（局域网访问也要设）
HTTPS_PROXY=                       # 本机访问 zenmux.ai 不通时填，如 http://127.0.0.1:7890
```

`config.yaml` 一般不用改（视频模型、筛选条件都可以在网页「设置」页改）。

### 2.5 首次登录 FastMoss（只需一次）

```powershell
cd C:\tk-aps
uv run cli.py login
```

会弹出浏览器窗口：输入 FastMoss 账号密码（或手机验证码），脚本检测到登录成功后自动继续，登录状态保存在 `browser_profile/`，以后采集不用再管。**这步必须在 Windows 机器的桌面上做**（用远程桌面连过去操作），不能在系统服务/后台会话里。

### 2.6 启动并验证

```powershell
uv run cli.py serve --host 0.0.0.0 --port 8000
```

- 本机验证：浏览器打开 `http://127.0.0.1:8000`，用 WEB_USERNAME/WEB_PASSWORD 登录
- 局域网访问：其他设备打开 `http://<Windows机器IP>:8000`（不通见 2.7 防火墙）
- 在网页上点「发起选品采集」跑一次小采集（每类目翻页数填 1），验证整条链路

### 2.7 防火墙放行 8000 端口（管理员 PowerShell，只需一次）

```powershell
netsh advfirewall firewall add rule name="TK_APS" dir=in action=allow protocol=TCP localport=8000
```

---

## 3. 日常使用（都在网页上）

每周的典型节奏：

1. **发起选品采集**（批次工作台右上角）：弹参数表单（默认值来自 config.yaml），确认后弹出浏览器窗口自动跑 FastMoss，几分钟出批次卡片
2. **勾选确认**：进批次，勾选要做视频的商品（绿色高亮行），这是人工把关的门槛
3. **生成脚本**：单件在商品详情页点「生成脚本」，或多件点批次页「批量生成脚本」；完成后详情页自动刷新，可在线编辑提示词
4. **生成视频**：详情页点「用此脚本生成视频」（**按条收费**，约 3–5 分钟出片）
5. **视频库下载**：按日期分组，单个下载或勾选打包 ZIP

任务进度看右下角浮标（进行中/已完成分栏）；所有操作按钮都有费用确认弹窗。

---

## 4. 开机自启动

目标：机器重启后服务自动起来，爬虫的浏览器窗口能正常弹出（所以用"登录时启动"，**不注册系统服务**）。

### 4.1 创建启动脚本 `C:\tk-aps\serve.bat`

```bat
@echo off
cd /d C:\tk-aps
uv run cli.py serve --host 0.0.0.0 --port 8000
```

### 4.2 注册计划任务（管理员 PowerShell，只需一次）

```powershell
schtasks /Create /TN "TK_APS 网页服务" /TR "C:\tk-aps\serve.bat" /SC ONLOGON
```

以后开机登录就自动启动。想开机就运行而不等登录，需要机器设置了自动登录（可选项，按你的安全偏好决定）。

### 4.3 两个 Windows 注意事项

- **远程桌面用完选"断开"，不要"注销"**——注销会杀掉桌面会话里的网页服务和爬虫浏览器
- **关闭 Windows 自动更新自动重启**（设置 → Windows 更新 → 活动时间），防止采集/生成视频跑到一半被重启

---

## 5. 数据与备份

| 内容 | 位置 | 说明 |
|---|---|---|
| 数据库（商品/脚本/视频/任务记录） | `data/db.sqlite` | 单文件，启动时自动从文件产物同步 |
| 视频/图片/原始采集数据 | `data/videos/`、`data/images/`、`data/raw/` | 体积大头，每条视频约 5–12MB |
| 采集日志 | `data/logs/scrape_*.log` | 排查采集问题 first stop |
| FastMoss 登录状态 | `browser_profile/` | 备份它可免重新登录 |
| 密钥 | `.env` | 不在 git 里，单独保管 |

**备份 = 复制 `data/` + `.env` + `browser_profile/` 三个目录**（服务运行中也可复制，SQLite 建议停服后复制更稳）。示例（备份到 D 盘）：

```powershell
robocopy C:\tk-aps\data D:\tk-aps-backup\data /MIR
copy C:\tk-aps\.env D:\tk-aps-backup\
```

建议每周采集后备份一次；磁盘紧张时可以清理 `data/raw/`（历史原始数据，删了不影响已出视频，只影响"离线重筛"的历史回溯）。

---

## 6. 维护手册

### 6.1 常用命令（都在 `C:\tk-aps` 下）

```powershell
uv run cli.py serve                 # 启动网页（日常由计划任务自动跑）
uv run cli.py login                 # FastMoss 登录过期时重新登录
uv run cli.py sync-db               # 手动把 data/ 文件产物同步进数据库（一般不用，自动的）
uv run cli.py export --raw-dir data/raw/<时间戳>   # 改筛选条件后离线重筛（不用重爬）
```

### 6.2 常见问题排查

| 现象 | 原因与处理 |
|---|---|
| 采集弹出的浏览器停在登录页 | FastMoss 登录过期且自动登录失败 → 远程桌面连到机器，`uv run cli.py login` 手动登一次 |
| 采集完成但筛选 0 条 | 筛选参数过严（最常见：达人区间，榜单头部商品普遍 400–1600）→ 任务日志里有明确警告；改参数后跑 `cli.py export --raw-dir <该次raw目录>` 离线重筛，不用重爬 |
| 视频被"内容审核拦截" | 参考图含真人模特 → 系统会自动换图重试 3 次；反复拦截就换图片干净的商品，或在详情页重试 |
| 换视频模型后提交 404 | 模型在当前接口通道不可用 → 系统会自动换通道重试，一般无感；两条通道都不支持说明模型名有误，以设置页能查的模型列表为准 |
| 网页打不开 | 服务没起来：看计划任务是否运行；端口被占：`netstat -ano | findstr 8000`，找到 PID 结束或改端口 |
| 页面是旧版本 | 浏览器强刷 `Ctrl+Shift+R`；前端更新后需重新构建（见 6.4） |
| 生成脚本失败 | 多为 LLM 输出格式解析失败，会留 parse_failed 版本；直接再点一次生成即可 |

### 6.3 日志在哪

- **采集**：`data/logs/scrape_*.log`（每次采集一个文件，参数留底在同名 `_params.json`）
- **任务（脚本/视频）**：网页右下角任务浮标 → 抽屉里看实时日志；数据库也有留底
- **服务本身**：计划任务启动的话看 `serve.bat` 窗口；手动跑的话就在当前终端

### 6.4 升级项目

```powershell
cd C:\tk-aps
git pull                           # 拉新代码
uv sync                            # 依赖有更新时
# 如果更新包含前端改动（frontend/src 变了）且拿到的是源码：
#   需要 Node：安装后 cd frontend && npm install && npm run build
#   或者直接从开发机拷贝新的 frontend/dist 覆盖（推荐，机器上不用装 Node）
# 重启服务：结束 serve.bat 窗口或重启机器（计划任务自启）
```

数据库结构有变化时启动会自动建表/同步，无需手动迁移。

### 6.5 费用相关（心里有数）

- **生成脚本**：约 3.5K tokens/件（gpt-5）
- **生成视频**：按条收费，seedance 2.0 / wan3.0 约 $0.1–0.5/条（10 秒），接口不返回费用明细，定期去 ZenMux 后台核对余额
- 防误触机制：所有生成类按钮有确认弹窗；单批次视频上限 30 条

---

## 7. 快速参考卡片

```
启动/重启服务     重启机器（自启）或双击 C:\tk-aps\serve.bat
访问网页          http://<机器IP>:8000（账号密码在 .env）
重新登录 FastMoss uv run cli.py login
备份数据          复制 data/ + .env + browser_profile/
采集日志          data/logs/
排不了的问题      任务浮窗日志 + data/logs/ + serve 窗口报错，截图留档
```
