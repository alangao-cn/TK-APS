# TK_APS 项目方案：自动化选品 + AI 视频素材生成

> 版本 v10 · 2026-10-01
> 技术栈：**Python 3.12**（FastAPI + Playwright + SQLite）
> 开发测试：本地 Mac；部署：**先部署到一台 Windows 机器**（以后可迁 Linux，代码不用改）

## 变更记录

- v10：**第四步（网页）落地**：FastAPI + Jinja2 服务端渲染，`uv run cli.py serve` 启动。五个页面：总览（发起采集子进程 + 任务进度实时轮询）、选品（**按商品勾选确认**写回 selected.json、逐条/批量生成脚本）、脚本（**在线编辑提示词**、重新生成、提交视频）、视频（在线预览、单个下载、勾选 ZIP 批量下载、失败重试）、设置（config.yaml 在线编辑 + 热重载）。登录用 .env 的 `WEB_USERNAME/WEB_PASSWORD`（HMAC 签名 Cookie，无会话表）。确认门槛细化为按商品勾选：`pick_products` 优先读每条商品的 `confirmed`，旧文件的整批字段仍兼容。长任务（采集/脚本/视频）都是内存任务表 + 页面轮询，采集在**子进程**跑（日志 `data/logs/`），不占用服务事件循环。前端手写轻量 CSS，不引 npm/CDN；任务状态有 JSON 接口（`/api/jobs`），以后要上 React+antd 只需加前端层。M1 的 SQLite 暂缓：文件存储已覆盖版本留底/单条重试，任务量上来再迁
- v9：**第三步（视频生成）落地**：`app/video/`（vertex + native 双客户端、提交/轮询/下载/存档），产出 `data/videos/{商品ID}/video_v{N}.mp4` + 完整任务档案；模型名实测定为 `bytedance/doubao-seedance-2.0`；发现并解决"参考图含真人被审核拦截"问题（自动换图重试）；单商品端到端验证通过（脚本→视频 263 秒出片）
- v8：**第二步（视频脚本生成）落地**：`app/llm/`（prompt 拼接 + ZenMux Responses API + `[Video Prompt]` 提取），产出 `data/scripts/{商品ID}/script_v{N}.json` 与 `script_latest.md`（含模型、prompt 哈希、token 用量，可回溯对比）；**目录按步骤归类**：第一步产出 → `data/selection/<时间戳>/`、第二步 → `data/scripts/`、第三步（预留）→ `data/videos/`；防 token 浪费：`gen-scripts` 默认只处理 confirmed=true 的商品，`--product` 单条测试；单商品实测通过（gpt-5，入 3068 / 出 2512 tokens）

- v7：筛选新增**库存门槛** `min_stock`（默认 ≥1；库存来自详情页补抓，补抓后过滤；库存未知时保留，selected.md 里显示库存供人工把关）；详情补抓加缓存（同一批数据重跑 export 不重复访问详情页）；修复重跑 export 时把 selected.json 当原始数据重复解析的问题
- v6：给 GPT 的数据升级为**多张商品图**——筛选后自动逐个补抓商品详情页（`/api/goods/v3/base` 的 `cover_list`，实测每件 3–10 张），附带评分/库存/评论数；详情接口同样没有商品描述字段，描述继续用标题（TikTok 标题即长描述）
- v5：模块一收尾——新增交付物 `selected.json`（第二步 GPT 的程序输入，自带 product_brief）与 `selected.md`（人工确认看板），`confirmed` 字段做人工确认门槛；新增 FastMoss 账号密码**自动登录**（失败自动转人工）；初始化 git；本期范围只做第一步选品
- v4：选品平台从 EchoTik 换成 **FastMoss**——官方 API 费用高，不走官方 API，用浏览器爬虫代替界面手动操作，架构不变；部署确定先上 Windows，部署方式从 Docker + noVNC 改为直接安装 + 远程桌面；URL、类目、实测清单按 FastMoss 更新
- v3：视频生成平台从 RelayDance 改为 **ZenMux**，同时支持 Vertex AI 兼容接口（默认）和原生接口，用配置切换；脚本和视频共用一个 ZenMux Key；商品图改用 base64 直接传，不再需要上传步骤；运行环境补充 Windows 方案；本地 Mac 即可开发测试
- v2：LLM 改为 ZenMux（Responses API，`openai/gpt-5`）；市场确定为巴西站、葡萄牙语口播；确定部署到 Linux 服务器；模型和视频规格全部改为配置项；从参考 Prompt 中提取出第一版模板
- v1：初版

---

## 0. 总览

| 环节 | 方案 | 配置位置 |
|---|---|---|
| 1. FastMoss 选品 | Playwright 驱动真实浏览器 + 截获页面自己请求到的数据（不走官方付费 API） | `config.yaml → selection` |
| 2. 生成视频脚本 | ZenMux Responses API，默认 `openai/gpt-5`，同时传入商品文字信息和主图 | `config.yaml → llm`，`prompts/` |
| 3. 生成视频 | ZenMux 视频接口（默认 Vertex AI 兼容方式，可切换原生方式），默认模型 Seedance 2，带商品图，异步提交后轮询 | `config.yaml → video` |
| 4. 视频下载页 | FastAPI 网页：预览、单个下载、勾选后打包 ZIP 批量下载 | 无 |

流程是**半自动**的，有两个人工确认点：选品结果出来后，勾选要做的商品；脚本生成后，可以修改再提交生成视频。

---

## 1. 运行环境

### 1.0 开发测试阶段：本地 Mac 即可

脚本生成和视频生成只是调用 ZenMux 接口，和操作系统无关，在 Mac 上就能开发和测试。爬虫（模块一）同样可以先在 Mac 上开发和测试。

- Python：用 `uv` 固定 Python 3.12（本机是 3.14，部分第三方库可能还不完全支持），不影响系统自带的 Python
- 网络：Mac 需要能访问 `fastmoss.com`（国内网络可直连）和 `zenmux.ai`；如果需要代理，可以在 `.env` 里配置 `HTTPS_PROXY`

### 1.1 部署阶段：先部署到 Windows（已确定）

**先部署到一台常开的 Windows 机器**（普通电脑或 Windows 服务器都行）。代码和 Mac 上完全一样，只多部署这一层：

| 项目 | 内容 |
|---|---|
| 环境 | `uv` 安装 Python 3.12 和依赖；`playwright install chromium`；ffmpeg（网页缩略图用）下载 exe 放进 PATH |
| 自启动 | 任务计划程序设"开机后、用户登录时"启动。不注册成系统服务，保证爬虫的有头浏览器跑在桌面会话里，出问题远程桌面直接看 |
| 手动登录 FastMoss | 远程桌面（RDP）连上机器，在机器上的 Chromium 里登录一次 FastMoss；登录状态持久化在 `browser_profile/`，之后不用再管 |
| 网络 | 机器需能访问 `fastmoss.com`（国内直连）和 `zenmux.ai`（不通则在 `.env` 配 `HTTPS_PROXY`） |
| 注意 | 关闭 Windows 自动更新重启；远程桌面用完选"断开"，不要"注销"（注销会结束桌面会话里的程序和浏览器） |

网页默认只在局域网 / 本机访问（`http://机器IP:8000`），设置登录密码即可，暂不需要域名和 HTTPS。以后需要公网访问时，再加内网穿透或迁到云服务器。

**以后迁 Linux**：代码不用改，部署方式换成 Docker Compose + noVNC（在网页里操作服务器上的浏览器来登录），届时再补细节。

### 1.2 回调还是轮询

Windows 机器没有公网地址，ZenMux 视频接口的 `callback_url` 用不了，**直接用轮询**（每 15 秒查一次）。轮询本身也更稳：不依赖外部能访问进来，服务重启后能从数据库恢复未完成的任务。

---

## 2. 模块一：FastMoss 选品爬虫

### 2.1 评估：能不能用爬虫代替手动选品（官方 API 太贵的问题）

**结论：可行，而且整体架构和原方案完全一样，只是把目标网站从 EchoTik 换成 FastMoss。**

- FastMoss 官方 API 是单独收费的商业接口，费用高 → **不用它**。爬虫走的是另一条路：网页界面自己展示的数据，也是浏览器调 FastMoss 内部接口拿到的 JSON；用 Playwright 打开真实浏览器，把页面自己请求到的 JSON 截获下来即可，**不产生任何 API 费用**
- 爬虫能看到的数据 = 你登录后在界面里能看到的数据，账号有什么权限就能拿到什么，所见即所得
- 价值：把你每周重复的"选周榜 → 选巴西 → 勾类目 → 翻页 → 按佣金和达人数筛 → 进详情页 → 导出信息"整套操作脚本化
- 前提与风险（都可控）：
  - 需要一个能登录的 FastMoss 账号；免费账号能看到哪些字段、热销榜能翻几页，要实测（见 2.4），不够再考虑会员
  - 内部接口可能带签名参数：这不影响"开着浏览器截获"，只影响以后"不开浏览器直接请求接口提速"这个优化项
  - 账号安全：低频（一周一次）、单账号、单标签页、不并发、每步随机等待 3–8 秒；建议专门注册一个账号
  - 兜底不变：爬虫哪天不好使了，在网页上粘贴商品 ID 或上传 CSV 手动导入，后面的流程不受影响

### 2.2 实现方式（2026-09-27 实测定稿）

1. Playwright 打开持久化浏览器（登录状态保存在 `browser_profile/`；首次 `cli.py login` 人工登录一次，验证码/登录弹窗由人工在窗口里处理，脚本自动检测通过后继续）
2. 打开热销榜 `…/hotlist?region=BR`，等页面完成 SPA 二次跳转后，点击"周榜"、逐个点类目
3. 翻页用分页条的**"跳至 N 页"输入框直跳**（比连点"下一页"快得多），每类目最多 50 页 × 每页 10 条
4. 用 `page.expect_response` **截获页面自己请求的接口数据（JSON）**，不去网页上抠文字
5. 接口原始 JSON 全部落盘 `data/raw/<时间戳>/`；解析、筛选、导出是**离线步骤**（`cli.py export`），改筛选规则/字段映射不用重爬
6. 筛选：达人数 30–70 + 单件利润 ≥ 2 元；无佣金率（字段为 "-"）或无达人数的商品直接跳过；通过的商品下载主图到 `data/images/`（实测 CDN 无防盗链）
7. 结果：`products_all.csv`（全部商品，含每条利润）、`products_selected.csv`（通过筛选）

**API 直取不可行**（已实测）：接口请求头带 `fm-sig` / `fm-sign` 签名（页面 JS 按参数生成），裸请求返回 `MSG_SAFE_0001`。所以走上面"真实 UI 操作 + 截获"的路线。

### 2.3 利润计算（和 README 口径一致）

FastMoss 界面上没有"利润"这个值，只有佣金率：

```
单件利润(CNY) = 售价(BRL) × 佣金率 × 汇率(BRL → CNY)
例：R$20 × 10% × 1.3 = 2.6 元 ≥ 2 元 → 通过
```

价格是区间时（如 "R$ 36,90 - R$ 55,90"）取最低价（`price_basis: min`），结果偏保守。汇率在配置里手动维护。

### 2.4 实测结论（2026-09-27，标准会员，全部确认）

- [x] **登录是必须的**：游客调接口返回 `MSG_SAFE_0001`（无数据），页面上表头之外的表格数据也不完整
- [x] **列表接口直接含全部所需字段**：`product_id`、`title`、`real_price`（"R$ 34,99"）、`commission_rate`（"10%"）、`author_count`（关联达人）、`total_author_count`、`sold_count`、`sale_amount`、`cover`（主图）、`all_category_name`、`shop_info.name`、`detail_url`（TikTok 商品页），不需要两阶段筛选
- [x] **参数结构**：`GET /api/goods/popRank?page=1&pagesize=10&order=4,2&region=BR&date_type=2&date_value=2026-38&l1_cid=9`；周榜 `date_type=2`（日 1/周 2/月 3），`date_value` 为 ISO 周号，类目 `l1_cid`（运动与户外 9 / 居家日用 10 / 五金工具 21，来自页面上单选框的 value）
- [x] **有签名**：`fm-sig`/`fm-sign` 请求头（见 2.2），所以不开浏览器直接请求接口不可行，`_time`+`cnonce` 只是防缓存
- [x] **价格币种是 BRL**
- [x] **标准会员可看 50 页/类目**（500 条）；部分商品佣金率显示 "-"（约 3～4 成），按需求直接跳过；升级会员能看到更多
- [x] **榜单名称注意**：README 给的 `hotlist` 在 FastMoss 界面上叫**热推榜**；侧边栏另有"销量榜"（`saleslist`）。若要换成销量榜，只改 `config.yaml` 的 `source_url` 即可，采集逻辑通用

### 2.5 使用方式

```
uv run cli.py login                       # 首次/登录过期时：.env 配了 FASTMOSS_PHONE/PASSWORD 则自动密码登录，失败转人工
uv run cli.py scrape                      # 采集（默认前 max_pages 页）并导出
uv run cli.py scrape --pages 50           # 采全量（每类目 50 页，约 15 分钟）
uv run cli.py scrape --categories 运动与户外   # 只跑指定类目
uv run cli.py export [--raw-dir …]        # 离线重跑解析筛选（改配置/解析后用，不用重爬）
uv run python scripts/diag_request.py     # 诊断：抓真实请求头/分页结构
```

### 2.6 交付物与人工确认门槛

每次采集：接口原始数据在 `data/raw/<时间戳>/`，第一步产出在 `data/selection/<时间戳>/`：

| 文件 | 用途 |
|---|---|
| `products_all.csv` | 全部商品（每条含单件利润），人工核对选品要求用 |
| `products_selected.csv` | 通过筛选的商品，同上 |
| `selected.json` | **第二步（GPT）的程序输入**：标题、**全部商品图**（`image_urls` + 本地路径 `images_local`，来自详情页 cover_list，每件 3–10 张）、价格/佣金/利润、评分/库存/评论数，每条自带拼好的 `product_brief`；`data/selection/selected_latest.json` 是最新一次的稳定副本 |
| `selected.md` | 人工确认看板：**多张主图** + 关键数字 + FastMoss/TikTok 链接 |
| `detail_{商品ID}.json` | 补抓的详情页接口原始数据（`/api/goods/v3/base`） |
| `*_p*.json`、`radio_values.json` | 榜单接口原始数据（改筛选规则不用重爬） |

**流程门槛**：`selected.json` 的 `confirmed` 默认 false；**网页「选品」页按商品勾选**后保存（写每条商品的 `confirmed` 字段并同步 `selected_latest.json`），第二步只消费勾选的商品（`pick_products` 优先读每条的 confirmed；兼容旧版整批字段；CLI 也可手动改 JSON）。

**详情补抓与库存过滤**：`scrape` 的完整流程是 达人数/利润初筛 → 逐个补抓详情页（约 4 秒/件，结果缓存在 `detail_{商品ID}.json`，重跑 export 直接用缓存）→ **库存 ≥ min_stock 再过滤**。单独补跑用 `uv run cli.py export --enrich`。FastMoss 榜单和详情接口都**没有商品描述字段**——TikTok 商品标题本身即长描述，已并入 `product_brief`；若 GPT 效果需要真实描述，再考虑抓 TikTok 商品页（另立任务）。

---

## 3. 模块二：用 GPT 生成视频脚本（ZenMux）

### 3.1 接口调用

ZenMux 兼容 OpenAI 接口，使用的是 **Responses API**：

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(base_url=cfg.llm.base_url, api_key=env.ZENMUX_API_KEY)

resp = await client.responses.create(
    model=cfg.llm.model,                 # 默认 "openai/gpt-5"，可在配置里修改
    instructions=system_prompt,          # 由 prompts/ 下的模板拼接而成
    input=[{
        "role": "user",
        "content": [
            {"type": "input_text",  "text": product_brief},   # 商品信息
            {"type": "input_image", "image_url": image_url},  # 商品主图
        ],
    }],
    reasoning={"effort": cfg.llm.reasoning_effort},          # 可选
    max_output_tokens=cfg.llm.max_output_tokens,
)
video_prompt = extract_prompt(resp.output_text)
```

**要点：**

- **图片来源**：使用本地保存的商品主图，转成 base64（`data:image/jpeg;base64,...`）传入，不需要额外的图片托管。不直接用 FastMoss 的 CDN 链接，因为它可能有防盗链。图片会先压缩到长边 1024 像素左右，控制请求大小
- **gpt-5 是推理模型，不支持调整 `temperature`**，所以配置里不设置这个参数。为了让不同商品的开头不雷同，在 Prompt 里明确要求避开常见句式，并把"最近已经用过的开头句"一起传给模型
- **解析输出**：用正则提取 `[Video Prompt]` 后面代码框里的英文内容。提取失败时自动重试一次
- 如果更换成不支持图片输入的模型，程序会自动只传文字

**传给模型的商品信息**（`product_brief`），由程序根据爬到的数据生成：

```
Product title: ...
Category: Sports & Outdoor > ...
Price: R$ 29.90 – 49.90
Key selling points (from title/description): ...
Target market: Brazil (TikTok Shop BR)
Reference image: attached (the product photo)
```

### 3.2 Prompt 模板

按你的要求，从参考 Prompt 中提取了第一版，拆分成"通用规则"和"市场规则"两部分，以后都可以直接修改文件：

| 文件 | 内容 |
|---|---|
| `prompts/director_base.md` | 通用规则：镜头结构、痛点到解决、开箱优先、UGC 风格、防穿帮、产品锁定、物理反馈、满意收尾、输出格式 |
| `prompts/market_BR.md` | 巴西市场：巴西葡萄牙语口播规则、巴西口语词、巴西生活场景 |

程序根据商品所属地区拼接：`director_base.md` + `market_{地区}.md`。以后做墨西哥站，只需要新增一个 `market_MX.md`。

与参考 Prompt 相比主要改了这几处：

1. **市场从墨西哥改为巴西**：口播改为巴西葡萄牙语，口语词换成 `gente, nossa, mano, sério, cara, que isso, demais, top`，场景加入巴西常见的生活环境（阳台、服务区、后院等）
2. **删掉了"日常沟通用中文"这类面向对话的规则**：现在是程序调用，没有来回沟通，模型只需要输出结果
3. **商品指代方式做成配置项**：视频 Prompt 中用 `{{product_ref}}` 指代商品，默认值为 "the product shown in the reference image"。ZenMux 文档没有说明 Prompt 里如何引用参考图，M0 阶段实测后再确定写法（见 4.6）
4. **时长和镜头数用变量表示**：`{seconds}` 等从 `config.yaml` 中读取，改视频时长时 Prompt 会自动跟着变

### 3.3 已实现与用法（2026-09-27 实测）

```
uv run cli.py gen-scripts                          # 只处理 selected.json 里 confirmed=true 的商品
uv run cli.py gen-scripts --product <商品ID>        # 单条测试（忽略确认门槛）
uv run cli.py gen-scripts --all                     # 全部商品（慎用，耗 token）
uv run cli.py gen-scripts --from <selected.json路径> # 指定某次选品结果
```

- 产出：`data/scripts/{商品ID}/script_v{N}.json`（模型、prompt 哈希、原始输出、token 用量、Hook 记录，可回溯对比版本）+ `script_latest.md`（可读版，代码框里直接复制提示词）
- 防重复：自动把最近 N 条（`avoid_recent_hooks`，默认 20）已用 Hook 拼进系统指令
- 实测（gpt-5，传 1 张主图）：入 3068 / 出 2512 tokens；产出 4 镜头 10 秒巴西葡语口播提示词，正确抓住商品侧口袋卖点（"Short Com Bolso"），防穿帮/试穿规则齐全
- 待观察：模型输出有时超过模板要求的 1800 字符（实测 2414），如影响视频效果再收紧；`max_images` 目前 1 张，多图更准但更耗 token

---

## 4. 模块三：生成视频（ZenMux 视频接口）

**脚本和视频共用同一个 ZenMux API Key**，不再需要 RelayDance。

### 4.1 两种调用方式对比

ZenMux 提供两种调用视频模型的方式：

| | **A. Vertex AI 兼容接口** | **B. ZenMux 原生接口** |
|---|---|---|
| 地址 | `https://zenmux.ai/api/vertex-ai/v1/publishers/{厂商}/models/{模型}:predictLongRunning` | `POST https://zenmux.ai/api/v1/videos` |
| 查询进度 | `POST ...:fetchPredictOperation`，body 为 `{"operationName": "..."}` | `GET https://zenmux.ai/api/v1/videos/{id}` |
| 调用方式 | Google 官方 SDK `google-genai`，或直接发 HTTP 请求 | 直接发 HTTP 请求 |
| 支持的模型 | Google Veo 3.1、Seedance 1.5 Pro、Seedance 2，以及通义万相、SkyReels 等，**多家模型用同一套参数** | 文档只列出了 Seedance 2.0，参数是各厂商自己的原生格式 |
| 参数 | 统一字段：`aspectRatio`、`resolution`、`durationSeconds`、`generateAudio`、`negativePrompt`、`seed`、`sampleCount` 等 | Seedance 原生字段：`ratio`、`resolution`、`duration`、`generate_audio`、`seed`、`watermark` 等 |
| 传商品图 | 首帧 `image`、尾帧 `lastFrame`、参考图 `referenceImages`（`referenceType: "asset"`），图片用 base64 | `content` 数组里的 `image_url`，角色可选 `first_frame` / `last_frame` / `reference_image`，支持 http 链接或 base64 |
| 结果 | `done: true` 后读取 `response.videos[]`：下载链接 `gcsUri` 或 base64 数据 `bytesBase64Encoded` | `status: succeeded` 后读取 `content.video_url` |
| 内容审核 | 返回 `raiMediaFilteredCount`，大于 0 表示被审核拦截 | 失败时返回 `error.code` 和 `error.message` |

### 4.2 结论：两种都实现，默认用 A（Vertex AI 兼容接口）

**默认用 A 的理由**：你还没确定用哪个视频模型。A 方式下，Veo 和 Seedance 用同一套参数，**换模型只需要改配置里的模型名**，不用改代码，方便对比不同模型的效果和价格。

**同时保留 B 的理由**：B 是 Seedance 的原生格式，参数最完整（比如 `watermark`、`return_last_frame`）。如果 A 方式下某个 Seedance 参数不生效，可以切换到 B。

两种方式都封装在 `app/video/` 下，对外接口相同（提交 → 查询 → 下载），用 `config.yaml` 里的 `video.api: vertex | native` 切换。每种大约 100 行代码，开发成本不高。

**直接发 HTTP 请求，不用 google-genai SDK**：
- SDK 主要为 Google 自家的 Veo 设计，`referenceImages` 这类 Seedance 用的字段不一定能完整传过去
- 直接用 `httpx` 发请求，字段可以完全控制，也和 B 方式写法一致，少一个依赖

### 4.3 A 方式的请求示例

```python
provider, model = cfg.video.model.split("/", 1)       # 例如 "volcengine/doubao-seedance-2"
url = f"{cfg.video.vertex_base_url}/v1/publishers/{provider}/models/{model}:predictLongRunning"

instance = {"prompt": video_prompt}
if cfg.video.image_role == "reference_image":
    instance["referenceImages"] = [{
        "image": {"bytesBase64Encoded": img_b64, "mimeType": "image/jpeg"},
        "referenceType": "asset",
    }]
elif cfg.video.image_role == "first_frame":
    instance["image"] = {"bytesBase64Encoded": img_b64, "mimeType": "image/jpeg"}

body = {
    "instances": [instance],
    "parameters": {
        "aspectRatio": cfg.video.ratio,               # "9:16"
        "resolution": cfg.video.resolution,           # "720p"
        "durationSeconds": cfg.video.duration,        # 10
        "generateAudio": cfg.video.generate_audio,    # true，带口播
        "sampleCount": 1,
        "negativePrompt": cfg.video.negative_prompt,  # 可选
    },
}
op = (await http.post(url, json=body, headers=auth)).json()      # {"name": ".../operations/abc123"}

# 每 15 秒查询一次
res = (await http.post(url.replace(":predictLongRunning", ":fetchPredictOperation"),
                       json={"operationName": op["name"]}, headers=auth)).json()
if res.get("done"):
    v = res["response"]["videos"][0]    # 有 gcsUri 就下载链接，有 bytesBase64Encoded 就直接解码保存
```

### 4.4 B 方式的请求示例

```python
payload = {
    "model": cfg.video.model,                   # 例如 "bytedance/doubao-seedance-2.0"
    "content": [
        {"type": "text", "text": video_prompt},
        {"type": "image_url", "role": cfg.video.image_role,             # reference_image / first_frame
         "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
    ],
    "duration": cfg.video.duration,
    "ratio": cfg.video.ratio,
    "resolution": cfg.video.resolution,
    "generate_audio": cfg.video.generate_audio,
    "seed": cfg.video.seed,
    "watermark": cfg.video.watermark,
}
job = (await http.post(f"{cfg.video.native_base_url}/videos", json=payload, headers=auth)).json()
# GET /videos/{job["id"]}，status == "succeeded" 时读取 content.video_url
```

### 4.5 商品图怎么传：参考图还是首帧

| 角色 | 效果 | 适合情况 |
|---|---|---|
| **参考图**（默认） | 模型参考商品外观，自由安排镜头 | 我们的 Prompt 是 4 个镜头、UGC 风格、开箱开头，商品图只是用来锁定外观 |
| 首帧 | 视频第一帧就是这张图 | 商品图大多是白底或带海报文字的电商图，作为第一帧会违反 Prompt 中"不要白底、不要海报文字"的规则 |

默认用参考图，配置项 `video.image_role` 可以切换，M0 阶段两种都试。

注意：文档说明 Seedance 2 的"参考音频"不能和首帧同时使用。我们目前不传参考音频，所以没有影响。

### 4.6 实测结论（2026-09-27，单商品验证通过）

1. **模型名称**：`GET /api/v1/models`（203 个模型）确认可用 **`bytedance/doubao-seedance-2.0`**（另有 seedance-2.5、alibaba/wan3.0-video、bfl/flux-3-video）。文档模型表里的 `volcengine/doubao-seedance-2` 实测返回 `invalid_model`，勿用
2. **时长/规格**：10 秒、9:16、720p、generateAudio 在 vertex 方式下全部生效
3. **内容审核（重要）**：参考图里**含真人**会被拦截（`raiMediaFilteredCount`，报 "input image may contain real person"）。服装类商品图几乎全是模特图，已实现**自动换下一张商品图重试**（`max_image_attempts`，默认 3 次）；纯产品图（美妆/工具类）无此问题。选品时也可以偏重图片干净的商品
4. **结果形式**：实测返回 `bytesBase64Encoded`（base64），代码同时兼容 `gcsUri` 下载链接；成功后立即落盘
5. **耗时**：提交后约 4.5 分钟出片（文档口径 30 秒–3 分钟）；单条 10 秒 720p 视频 4.46 MB
6. **价格**：接口不返回费用，从 ZenMux 后台余额核对
7. **Prompt 引用参考图**：写 "the product shown in the reference image" 可用（`product_ref` 配置）

### 4.7 已实现与用法

```
uv run cli.py gen-videos                          # 无参数：只列出可生成的商品（费用保护）
uv run cli.py gen-videos --product <商品ID>        # 单条生成（默认最新成功脚本）
uv run cli.py gen-videos --product <ID> --script-version 2   # 指定脚本版本
uv run cli.py gen-videos --product <ID> --image 3  # 强制用第 3 张商品图做参考图
uv run cli.py gen-videos --all                     # 全部商品（慎用，费用高）
```

- 产出：`data/videos/{商品ID}/video_v{N}.mp4` + `video_v{N}.json`（模型、参数、任务号、每次尝试的图与结果、耗时，全留底）
- 费用保护：必须显式 `--product` 或 `--all`；单批次上限 `max_videos_per_batch`
- 两种接口（vertex / native）都已实现，`video.api` 切换；默认 vertex

### 4.8 其他要点

- **并发控制**：同时最多进行 `max_concurrent` 个任务，其余排队
- **轮询**：每 15 秒查询一次（文档建议值），超过 `timeout_seconds` 标记为超时
- **失败重试**：自动重试 `max_retries` 次；被内容审核拦截的不自动重试，在网页上提示修改 Prompt
- **缩略图**：下载后用 ffmpeg 截一张图，在网页列表中显示
- **成本控制**：单批次最多生成 `max_videos_per_batch` 条，超过就拒绝提交
- **时长校验**：提交前检查配置的时长是否超过当前模型的上限，避免浪费请求

---

## 5. 配置文件

所有可调整的内容集中在两个文件：

- `.env`：密钥，不提交到代码仓库
- `config.yaml`：业务配置，已写好初版，修改后在网页上点"重新加载"或重启服务即可生效

```
# .env
ZENMUX_API_KEY=...        # 脚本和视频共用
WEB_USERNAME=admin
WEB_PASSWORD=...
HTTPS_PROXY=              # 可选，本地访问 zenmux.ai 需要代理时填写
```

`config.yaml` 的结构（完整内容见文件）：

```yaml
selection:  周期、地区、类目、利润门槛、达人数范围、汇率、请求间隔、代理
llm:        base_url、model（openai/gpt-5）、reasoning_effort、max_output_tokens、prompt 模板路径、是否传图
video:      api（vertex/native）、两种接口地址、model、duration、ratio、resolution、generate_audio、
            image_role、product_ref、negative_prompt、seed、watermark、variants_per_product、
            并发数、轮询间隔、超时、重试次数、callback_url、单批次上限
storage:    数据目录、视频保留天数
```

网页上也会提供一个设置页，可以查看当前配置，常用项（模型、视频规格、筛选条件）可以直接在网页上修改。

---

## 6. 模块四：网页（2026-10-01 已落地初版）

| 页面 | 功能 | 状态 |
|---|---|---|
| `/` 总览 | 统计卡片（入选/脚本/视频）、批次历史、**发起选品采集**（子进程跑 `cli.py scrape`，日志落 `data/logs/`）、任务进度实时轮询 | ✅ |
| `/products` | 筛选结果：多图商品卡、价格/佣金/利润/达人/库存、FastMoss/TikTok 链接、脚本/视频进度徽章；**按商品勾选确认**；逐条/批量生成脚本 | ✅ |
| `/scripts` | 每商品最新脚本：**在线编辑提示词**（保存写回 script_v{N}.json 并刷新 latest.md，标 edited）、重新生成（写新版本）、历史版本折叠、提交生成视频；"待生成"区列出已确认无脚本的商品 | ✅ |
| `/videos` | 视频墙：`<video>` 在线预览、失败原因展示 + 重试、**单个下载**、**勾选后批量下载（ZIP，STORED 不二次压缩）**；文件名 `{日期}_{商品ID}_v{版本}.mp4` | ✅ |
| `/settings` | 密钥状态（只显示已配置/未配置）、config.yaml 在线编辑（YAML 校验）、保存/重载即热生效 | ✅ |

- 批量下载用临时文件 + `zipfile`（mp4 已压缩，STORED 模式，量级可控）；任务多后再换 `zipstream-ng` 流式
- 登录：`.env` 的 `WEB_USERNAME/WEB_PASSWORD`，HMAC 签名 Cookie（改密码即全部会话失效），未登录全站 302 到 /login
- 长任务编排：`app/web/jobs.py` 内存任务表（保留最近 100 条）+ `app/web/pipeline.py`；脚本/视频生成直接在服务事件循环里跑（服务层本来就是 async），采集在子进程跑避免有头 Playwright 干扰
- 前端：Jinja2 + 手写 CSS（antd 观感），**不引 npm 构建链和 CDN**（局域网/离线可用，Windows 部署简单）；任务状态已 JSON 化（`/api/jobs`），以后要复杂前端可在同一后端上加 React + antd SPA

### 6.1 用法

```
uv run cli.py serve                        # 本机访问 http://127.0.0.1:8000
uv run cli.py serve --host 0.0.0.0         # 局域网访问 http://机器IP:8000
```

- 登录账号 = `.env` 的 `WEB_USERNAME` / `WEB_PASSWORD`
- 页面顶部有全局任务进度条（每 3 秒轮询）；带自动刷新的页面在任务从"有"变"无"时自动 reload，新产出立即可见
- 费用相关的按钮（生成脚本/视频）都有确认弹窗；生成视频仍然按条收费，参考图的审核换图逻辑与 CLI 一致

---

## 7. 数据模型（SQLite）

```
batches    id, params_json, status, started_at, finished_at               -- 一次选品任务
products   id, batch_id, product_id(FastMoss/TikTok 商品ID), title, category, region, price_min, price_max, currency,
           commission_rate, creators_count, sales_week, profit_cny, image_local,
           raw_json, selected, source(scraper/manual), created_at
scripts    id, product_id, llm_model, prompt_hash, video_prompt, edited, status, error, created_at
videos     id, script_id, variant, model, params_json, job_id, status(queued/running/succeeded/failed/timeout),
           remote_url, local_path, thumb_path, error_code, error_message, retries, created_at, finished_at
```

每一步的处理方式都一样：读取上一步已完成的记录 → 处理 → 更新状态。所以**任何一步失败都能单独重试**，服务重启后也能接着跑。

---

## 8. 目录结构

```
TK_APS/
├── app/
│   ├── main.py              # FastAPI 入口（登录中间件 + 路由组装）
│   ├── config.py            # 读取 .env + config.yaml
│   ├── web/                 # 网页支撑：auth（HMAC 会话）/ jobs（任务表）/ pipeline（后台编排）/ store（文件数据读写）
│   ├── routes/              # 页面与接口：pages / actions / downloads / api / auth
│   ├── templates/           # Jinja2 模板（6 个页面）
│   ├── static/              # 手写 CSS + 任务轮询 JS（无 CDN）
│   ├── scraper/             # 模块一：browser / leaderboard / detail / parser / filter
│   ├── llm/                 # 模块二：client / prompt_builder / parser
│   └── video/               # 模块三：vertex_client / native_client / worker
├── prompts/
│   ├── director_base.md     # ← 已写好初版
│   └── market_BR.md         # ← 已写好初版
├── config.yaml              # ← 已写好初版
├── .env.example
├── cli.py                   # 命令行：login / scrape / export / gen-scripts / gen-videos / serve
├── pyproject.toml           # uv 管理依赖，固定 Python 3.12
├── data/
│   ├── raw/<时间戳>/        # 第一步：接口原始数据（榜单 + 详情缓存）
│   ├── selection/<时间戳>/  # 第一步产出：products_*.csv、selected.json / selected.md
│   │                        #   （最新副本固定在 data/selection/selected_latest.*）
│   ├── scripts/<商品ID>/    # 第二步产出：script_v{N}.json + script_latest.md
│   ├── videos/<商品ID>/     # 第三步产出：video_v{N}.mp4 + video_v{N}.json
│   ├── images/              # 商品图 {商品ID}_{n}.webp
│   └── logs/                # 网页发起的采集子进程日志
└── browser_profile/         # FastMoss 登录状态
```

主要依赖：`fastapi`、`uvicorn`、`jinja2`、`python-multipart`（网页）、`openai`（调用 LLM）、`httpx`（调用视频接口，两种方式都直接发 HTTP 请求）、`playwright`、`pyyaml`、`pillow`（压缩图片）。

---

## 9. 开发里程碑

| 阶段 | 内容 | 在哪里做 | 预估 |
|---|---|---|---|
| **M0 核心流程** | 写好模块二、三的核心代码，提供命令 `cli.py run --product 商品.json`，用 3–5 个手动输入的商品跑通"脚本 → 视频"。同时逐项确认第 4.6 节的问题（模型名称、参考图和首帧哪个效果好、Prompt 中如何引用参考图、9:16 和口播、单条视频价格和耗时），有条件的话对比 Seedance 2 和 Veo 3.1 的效果；根据生成效果调整 Prompt | 本地 Mac | 1 天 |
| **M1 完善模块二、三** | ~~数据库~~（暂缓：文件存储已覆盖版本留底/单条重试，量级上来再迁 SQLite）、手动导入商品、服务重启后恢复未完成任务（当前任务表在内存，重启丢进度但产出不丢） | 本地 Mac | 1–2 天 |
| **M2 网页** | **初版已完成**（2026-10-01，见第 6 节）：5 个页面、登录密码、任务进度、批量下载。待办：手动导入商品入口、缩略图（ffmpeg）、`variants_per_product` 多版本对比 | 本地 Mac | — |
| **M3 部署** | 部署到 Windows 机器：uv 装环境、任务计划自启、远程桌面登录 FastMoss、局域网访问网页 | Windows 机器 | 1 天 |
| **M4 爬虫** | FastMoss 选品爬虫——**初版已完成并实测跑通**（2026-09-27，标准会员；见 2.2–2.5）。待办：全量 50 页跑一次验证 30–70 达人段；确认用热推榜还是销量榜 | 本地 Mac 已测，Windows 同一套命令 | — |
| **M5 完善** | 定时任务（比如每周一自动选品）、费用统计、日志、异常通知 | Windows 机器 | 1–2 天 |

**说明**：M0 就是正式开发的第一步，写出来的代码会直接用在正式系统里，不是用完就扔的测试脚本。之所以先做这一小块，是因为有几项参数只有实际调用才能确定，会影响后面的写法。爬虫放到最后，因为它能否成功还不确定，而其他模块不依赖爬虫。

---

## 10. 风险清单

| 风险 | 应对 |
|---|---|
| FastMoss 免费账号能看的字段或翻页数不够 | 先按免费账号实测（2.4 节）；不够再考虑会员；手动导入兜底 |
| 账号被风控或因自动化受限 | 一周一次、单账号、不并发、随机等待；专门注册一个账号；不行就退回手动导入 |
| IP 被 FastMoss 拦截 | Windows 机器用家庭/办公宽带 IP，比云机房 IP 更稳；配置里预留了 `proxy` |
| FastMoss 改版 | 截获接口数据而不是抠网页文字；字段对应关系集中在 `parser.py` 一个文件里 |
| 视频费用超出预期 | 人工勾选后才生成；单批次上限；记录每条视频的费用 |
| 生成的视频中商品变形、多出手等问题 | 传参考图；Prompt 里的防穿帮规则；可以把 `variants_per_product` 调成 2，从两个版本里挑 |
| 视频链接或任务过期 | 成功后立即下载到本地（任务过期后查询会返回 404） |
| 视频模型时长上限（Seedance 10 秒、Veo 8 秒） | 目前需求是 10 秒；换 Veo 要改成 8 秒；以后要更长的视频，需要拼接多段 |
| 只依赖 ZenMux 一家平台 | 模型和接口地址都是配置项；视频调用封装在 `app/video/` 下，以后换平台只需新增一个实现 |
| TikTok 对 AI 生成内容的标注要求 | 发布时按平台要求打 AI 生成标签 |

---

## 11. 还需要你提供或确认的事项

1. **API Key**：M0 开始前，在本地项目目录新建 `.env`，填上 `ZENMUX_API_KEY`（不要发在聊天里），并确认账户里有余额
2. **FastMoss 账号**：专门注册一个账号；先按免费权限实测 2.4 节的清单，再决定要不要开会员
3. **测试商品**：准备 3–5 个 FastMoss 商品链接（热销榜上的），最好覆盖不同类目（运动户外、居家、五金各一两个）
4. **Prompt**：`prompts/` 下的两个文件是第一版，M0 试跑后再一起调整
