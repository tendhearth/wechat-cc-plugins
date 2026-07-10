# 分层模型管理器 + 微信增益插件 —— 设计规格

**日期**: 2026-07-10
**状态**: 已通过设计评审(brainstorming),待写实现计划
**范围**: `wechat-cc-plugins`(开源 monorepo)—— 共享的 model-manager + 三个增益插件的模型分层机制。**不含** wxvault(闭源、独立仓、上游)。

---

## 1. 背景与目标

wxvault 已能解密并读取本地微信历史(macOS/Windows,四个 MCP 工具)。下一步是在其**解密产物**之上做增益:

- **#1 wxmedia — 媒体→文字**:把语音/图片变成可搜索的文本(ASR + OCR + 难图 VLM)。
- **#3 wxsearch — 向量检索**:对全量文本做语义搜索(embedding + FAISS + BM25 + RRF)。
- **#2 wxgraph — 关系图谱/CRM**:从历史结构化出联系人画像与关系图(SQL 聚合 + provider LLM 抽取,向量检索喂抽取)。

三者有**依赖链**:提取(媒体→文本)→ 检索(索引)→ 结构(图谱)。它们都需要**本地跑若干模型**;不同用户机器算力差异大。

**目标**:一套**分层、用户可选**的模型系统——不写死单一模型,给用户选「用哪个」,每个可选能力提供**两档**(轻量/低占用 vs 高精度/高占用),分平台,懒加载。

**隐私模型(硬约束)**:转录/OCR/embedding/向量检索**全本地**(原始音频/图片绝不出机器);只有**派生文本片段**才交给已接入的 provider(DeepSeek/OpenAI-compatible)做 LLM 抽取/深理解。**结构上强制**,不依赖自动脱敏(研究已证伪其可靠性)。

---

## 2. 仓库/架构决策

**两种耦合分开对待:**
- **代码耦合(同仓)**:model-manager(分层下载/选择/缓存)+ 公共工具,三个插件共享 → 住一个 monorepo 一起开发。
- **数据耦合(不同仓)**:增益插件读的是 wxvault 的**解密文件**(`${dataDir}/out/decrypted/*.sqlite`),**不 import wxvault 代码** → 天然不用同仓。

**结论:**
- `wxvault` —— **闭源、独立仓、上游**。含敏感的解密/取 key(frida 注入、SQLCipher);正是让 chatlog / wechat-dump-rs 被 DMCA 的那部分。**不开源、不搬**。
- `wechat-cc-plugins` —— **开源 monorepo + 注册表**。增益插件只处理已解密文本,可放心开源。

```
wechat-cc-plugins/
├── registry.json              # 保持原职:索引所有插件(含第三方)
├── packages/
│   ├── model-manager/         # 共享库:tier 注册表 / 下载 / 缓存 / 按平台解析
│   ├── wxmedia/               # #1 媒体→文字
│   ├── wxsearch/              # #3 向量检索
│   └── wxgraph/               # #2 关系图谱
```
每个 package 仍是**独立插件**(自带 `wechat-cc.plugin.json` + MCP server);monorepo 只是共置源码 + 共享 model-manager。registry.json 照常索引。

---

## 3. 分层的作用范围(哪些能力才需要「选模型」)

YAGNI:不为分层而分层。**真正给用户两档选的只有 3 个**。

| 能力 | 是否 tier | 说明 |
|---|---|---|
| SILK 解码 | ❌ 固定 | 编解码器 `pilk`(`tencent=True`),非模型 |
| **ASR 语音** | ✅ 两档 | 小模型够用 vs 大模型抗噪/方言 |
| OCR | ⚠️ 半个 | mac 用系统 Apple Vision(免下载,无档);Windows 给 small/medium 次要覆盖 |
| **难图 VLM 升级** | ✅ 开/关 | 默认关(只用 OCR);开了才下本地 VLM(重头) |
| **文本 embedding** | ✅ 两档 | 小 vs 大,检索质量 vs 资源 |
| reranker | ❌ 先不做 | 可选增强,默认关 |
| 抽取/图谱 LLM | ❌ 非本地 | 走 provider,不进本地 model-manager |

选择界面只面对 **ASR / embedding / VLM** 三个真旋钮。

---

## 4. 型号盘 + 两个全局预设(分平台)

> ⚠️ **embedding 与 VLM 两条最不确定、变动快**——下方为合理默认,**出货前应拿真实中文聊天数据横评后再定死**。

**三个可选能力:**

| 能力 | 轻量档(默认) | 高精度档 | 备注 |
|---|---|---|---|
| ASR | SenseVoice-Small GGUF q8(~254MB,llama.cpp,mac+Win 同一份,CPU 可跑) | mac: WhisperKit large-v3(CoreML/ANE,~0.6GB)· Win: whisper.cpp large-v3(~1.5GB) | 高精度买抗噪/方言/中英混鲁棒性;都先过 `pilk` 解 SILK |
| embedding | bge-small-zh-v1.5(~100MB,ONNX) | BGE-M3(~2GB,dense+稀疏+多向量) | mac 走 MLX/ONNX,Win 走 ONNX/DirectML。**待横评** |
| VLM 难图 | **关**(只 OCR) | 本地 OCR-专用 VLM(如 PaddleOCR-VL / DeepSeek-OCR 一档,~GB,建议 GPU) | 隐私铁律:**只能本地,原图绝不进 provider**。**待横评** |

**OCR(非主 tier):** mac = Apple Vision(`ocrmac`,`zh-Hans`,免下载);Windows 默认 PP-OCRv6 small(7.7M),可覆盖 medium(34.5M)。
**固定项:** SILK=`pilk` · reranker=关 · 抽取 LLM=provider。

**两个全局预设(叠加单项覆盖):**

| | 轻量(默认) | 高精度 |
|---|---|---|
| ASR | SenseVoice-q8 254MB | Whisper-large-v3 0.6–1.5GB |
| OCR | Vision / PP-small | PP-medium |
| VLM | 关 | 开(本地 VLM ~GB) |
| embedding | bge-small-zh 100MB | BGE-M3 2GB |
| **本地模型总量** | **~0.4GB,任何笔记本 CPU 可跑** | **数 GB,建议 GPU** |

---

## 5. model-manager 设计 + 下载/选择 UX + 集成

### 5.1 state 目录布局(沿用 wxvault `${dataDir}` 可写状态目录约定)
```
${dataDir}/models/
├── config.json          # 用户选择:preset + 单项覆盖
├── asr/<model-id>/…      # 权重(gitignore)
├── embedding/<model-id>/…
└── vlm/<model-id>/…
```
`config.json`:
```json
{ "preset": "light", "overrides": { "asr": "whisper-large-v3" } }
```

### 5.2 模型注册表(model-manager 内静态清单)
每个模型 = id / 能力 / 档位 / **分平台**产物(URL + 大小 + sha256)/ 运行时(llama.cpp · onnx · mlx · vision)。**下载源 ModelScope 优先**(国内网络),**HuggingFace 兜底**。

### 5.3 选择粒度:全局预设 + 单项覆盖
一个全局档「轻量/高精度」一键设好所有默认;进阶用户可单独改 ASR/embedding/VLM。

### 5.4 用户在哪选(三条路,层层递进)
- **setup 向导(主入口)**:首次问「轻量/高精度?」→ 写 config →(可选)预取。桌面版可渲染为下拉+进度。
- **MCP 工具(agent 可改)**:插件暴露 `models_status` / `set_model(capability, tier)` → 用户可直接对 agent 说「语音换高精度」,它切 config + 按需下载。**契合 wechat-cc 的 agent 定位**。
- **config.json 手改**(高级)。

### 5.5 下载策略:懒加载为主 + 可选预取
- 默认**懒加载**:首次真用到某能力才下对应模型,下前**显示体积并确认**。不用的能力不占盘。
- setup 提供「现在全下(预取)」选项。
- **分平台解析**:用户只选「轻量」,落到哪个模型由 model-manager 按 OS 定(mac→Vision+SenseVoice,Win→PP-small+SenseVoice)。

### 5.6 model-manager 公共接口(monorepo 共享库)
```
resolve(capability)      -> 当前 OS + config 下该用哪个模型
ensure(model_id)         -> 缺就下(带确认/进度),返回本地路径(懒加载)
status()                 -> 各能力当前档 + 下载状态(喂 MCP 工具)
set(capability, tier)    -> 改 config
prefetch(preset)         -> 一次性下齐某预设
```
插件运行时:工具调用 → `resolve` → `ensure`(缺则懒下)→ 跑模型。

### 5.7 依赖跟着档走
llama.cpp / ONNX Runtime / MLX / WhisperKit 等**只装当前 config 需要的**(选轻量 ASR 就不装 WhisperKit)。setup 按解析结果装。

### 5.8 manifest
每个增益插件各自 `wechat-cc.plugin.json`;`setup` = 装依赖 + 选档 + 可选预取;`healthcheck` 只要求 config 存在(模型懒加载,不硬卡)。

---

## 6. 快速变动 / 出货前须定型的点
- **embedding 型号**:bge-small-zh vs BGE-M3 vs Qwen3-Embedding 系列——需在真实中文聊天数据上横评。
- **本地 VLM 型号**:PaddleOCR-VL / DeepSeek-OCR / dots.ocr / Qwen3-VL / GLM-4.6V——2026 变动快,出货时定。
- ASR 速度数字来自数据中心 GPU,消费级笔记本绝对值打折(相对排序不变)。

## 7. 暂不做 / 后续
- **#2 关系图谱层**:技术研究中**无任何已验证方案**支撑,属最大证据缺口。落地前应单独再深研一轮(重点 LightRAG / KuzuDB + 增量抽取)。本 spec 只把它列为 model-manager 的下游消费者占位,不细化。
- reranker、多账号、跨设备同步:后续。

## 8. 推进顺序
先 **model-manager + #1 wxmedia**(证据最硬、可直接落地)→ **#3 wxsearch**(架构已定,差 embedding 横评)→ 最后 **#2 wxgraph**(需先补 Layer 3 研究)。
