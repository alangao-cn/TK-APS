# TK_APS 项目方案：自动化选品 + AI 视频素材生成

> 版本 v4 · 2026-09-27
> 技术栈：**Python 3.12**（FastAPI + Playwright + SQLite）
> 开发测试：本地 Mac；部署：**先部署到一台 Windows 机器**（以后可迁 Linux，代码不用改）

## 变更记录

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

每次采集的产出都在 `data/raw/<时间戳>/`：

| 文件 | 用途 |
|---|---|
| `products_all.csv` | 全部商品（每条含单件利润），浏览核对用 |
| `products_selected.csv` | 通过筛选的商品，同上 |
| `selected.json` | **第二步（GPT 生成视频脚本）的程序输入**：标题、图片本地路径、价格/佣金/利润等，每条自带拼好的 `product_brief`；`data/selected_latest.json` 是最新一次的稳定副本 |
| `selected.md` | 人工确认看板：主图 + 关键数字 + FastMoss/TikTok 链接 |
| `*_p*.json`、`radio_values.json` | 接口原始数据（改筛选规则不用重爬） |

**流程门槛**：`selected.json` 的 `confirmed` 默认 false；人工确认后才置 true，第二步只消费 confirmed=true 的数据（现阶段手动改，M2 网页阶段做成勾选）。榜单接口没有商品描述字段，`description` 暂为空——TikTok 商品标题本身即长描述，已并入 `product_brief`；若 GPT 效果不够再从详情页补抓。

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

### 3.3 版本管理

数据库里会记录每条脚本使用的模型和 Prompt 文件版本（文件内容的哈希值），以后可以按效果对比不同版本。

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

### 4.6 需要在 M0 阶段实测确认的问题

1. **模型名称**：Vertex 文档中 Seedance 2 有两种写法，表格里是 `volcengine/doubao-seedance-2`，示例里是 `bytedance/doubao-seedance-2.0`。需要去 ZenMux 模型列表确认，两种接口的模型名可能也不同
2. **时长**：Seedance 最长 10 秒，**Veo 3.1 最长 8 秒（只支持 5 或 8 秒）**。如果换成 Veo，时长要改成 8 秒，Prompt 模板的镜头时间会自动跟着变
3. **Prompt 里怎么引用参考图**：文档没有说明。Prompt 模板里用变量 `{{product_ref}}` 指代商品，默认写成 "the product shown in the reference image"，实测后再调整
4. **9:16、720p、口播**：在 A 方式下是否都生效
5. **结果形式**：返回的是下载链接还是 base64 数据，链接能保存多久（程序两种情况都会处理，并且成功后立即保存到本地）
6. **价格和耗时**：文档没写价格，从 ZenMux 后台查看实际扣费；耗时文档说一般 30 秒到 3 分钟

### 4.7 其他要点

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

## 6. 模块四：网页

| 页面 | 功能 |
|---|---|
| `/` 首页 | 发起选品任务，查看各阶段的进度；需要人工登录时显示提示（远程桌面连到 Windows 机器处理） |
| `/products` | 筛选结果：图片、价格、佣金、单件利润、达人数、FastMoss 商品链接；**勾选**后生成脚本；支持手动导入商品 |
| `/scripts` | 每个商品的视频 Prompt，**可以在线修改**，也可以重新生成，确认后提交生成视频 |
| `/videos` | 视频列表：在线预览、状态、**单个下载**、**勾选后批量下载（ZIP）**、失败重试 |
| `/settings` | 查看和修改配置 |

- 批量下载用流式 ZIP（`zipstream-ng`），边打包边下载，不占太多内存
- 文件命名规则：`{日期}_{商品ID}_v{版本号}.mp4`
- 整个网页设置登录密码（虽然是局域网访问，也避免同网络的人误触）

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
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 读取 .env + config.yaml（pydantic 校验）
│   ├── models.py / db.py    # SQLModel
│   ├── scraper/             # 模块一：browser / leaderboard / detail / parser / filter
│   ├── llm/                 # 模块二：client / prompt_builder / parser
│   ├── video/               # 模块三：vertex_client / native_client / worker
│   ├── pipeline.py          # 编排、后台任务、启动时恢复未完成任务
│   ├── routes/              # 页面与接口
│   └── templates/           # Jinja2 + HTMX
├── prompts/
│   ├── director_base.md     # ← 已写好初版
│   └── market_BR.md         # ← 已写好初版
├── config.yaml              # ← 已写好初版
├── .env.example
├── cli.py                   # 命令行：scrape / gen-scripts / gen-videos / run / serve
├── pyproject.toml           # uv 管理依赖，固定 Python 3.12
├── deploy/                  # Windows：环境安装、任务计划自启脚本（以后迁 Linux 再补 Docker / noVNC）
├── data/                    # raw/ images/ videos/ db.sqlite
└── browser_profile/         # FastMoss 登录状态
```

主要依赖：`fastapi`、`uvicorn`、`openai`（调用 LLM）、`httpx`（调用视频接口，两种方式都直接发 HTTP 请求）、`playwright`、`sqlmodel`、`pyyaml`、`pillow`（压缩图片）、`zipstream-ng`。

---

## 9. 开发里程碑

| 阶段 | 内容 | 在哪里做 | 预估 |
|---|---|---|---|
| **M0 核心流程** | 写好模块二、三的核心代码，提供命令 `cli.py run --product 商品.json`，用 3–5 个手动输入的商品跑通"脚本 → 视频"。同时逐项确认第 4.6 节的问题（模型名称、参考图和首帧哪个效果好、Prompt 中如何引用参考图、9:16 和口播、单条视频价格和耗时），有条件的话对比 Seedance 2 和 Veo 3.1 的效果；根据生成效果调整 Prompt | 本地 Mac | 1 天 |
| **M1 完善模块二、三** | 数据库、并发、重试、断点恢复、手动导入商品 | 本地 Mac | 1–2 天 |
| **M2 网页** | 5 个页面、批量下载、登录密码 | 本地 Mac | 2–3 天 |
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
