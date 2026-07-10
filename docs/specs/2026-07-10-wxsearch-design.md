# wxsearch (向量/语义检索) 设计规格

**日期**: 2026-07-10
**状态**: 已通过设计评审(brainstorming),待写实现计划
**范围**: `wechat-cc-plugins` monorepo 的 `packages/wxsearch` —— 增益插件家族第 3 层(检索),建在 model-manager + wxmedia 之上。**不含** wxgraph(#2,单独)。

---

## 1. 背景与目标

model-manager(分层模型)与 wxmedia(语音→文字)已完成。wxsearch 是检索层:对本地微信历史做**语义 + 关键词混合检索**,让 agent 能「找那次聊到 X 的消息」。

**隐私(硬约束)**:embedding 与索引**全本地**,原始文本不出机器;**本插件零 provider/网络调用**(LLM 层是 wxgraph,单独)。

**数据来源(纯本地数据契约,不 import 闭源 wxvault)**:
- **文本消息**:wxvault 解密的 `${dataDir}/out/decrypted/message_*.sqlite` 里 `Msg_<md5>` 表的 `message_content` 列(纯文本消息的正文**直接可读**,已实测)。
- **媒体文本**:wxmedia 的 `${dataDir}/wxmedia/derived.sqlite`(语音转录 / 图片 OCR 结果),按 `server_id` join。

---

## 2. 关键设计决策(评审已定)

- **切块单位 = 每条消息一个 chunk**(检索精细、元数据逐条对得上;极短消息语义弱但可接受;3 万条 = 3 万向量,本地可扛)。
- **向量后端 = numpy 精确余弦,无 FAISS**(个人规模几万条 <50ms、召回 100%,少一个重依赖;与研究「FAISS at scale」不矛盾——百万级才上 FAISS)。
- **BM25 = SQLite FTS5 自带 `bm25()`**(零额外依赖)。
- **融合 = Reciprocal Rank Fusion(k=60)**。
- **唯一新依赖 = numpy**(FTS5/sqlite 标准库;embedding 走 model-manager)。
- **无 reranker**(YAGNI,后续可加)。

---

## 3. 索引什么 + 元数据

**只索引「有文本」的消息**:
- 纯文本消息:读 `Msg_<md5>.message_content`,按 `local_type` 过滤文本类型,去掉群聊 `<sender_id>:\n` 前缀。
- 媒体消息(语音/图片):文本从 wxmedia `derived.sqlite` 按 `server_id` join;无派生文本的媒体跳过。
- 链接/文件等富消息:暂不深挖(YAGNI,后续可加链接标题)。

**每条 chunk 的字段**:`msg_key`(稳定唯一键,如 `conversation:local_id` 或 server_id)、`conversation`(表名 md5 → `Name2Id` 反查会话 username)、`sender`(`real_sender_id` → `Name2Id` → username)、`time`(`create_time`)、`type`(文本/语音/图片)、`text`。

**增量**:`msg_key` UNIQUE,已索引跳过,只 embed 新消息。删除的消息暂不处理(append-only,v1 可接受)。

---

## 4. 存储与检索

**`${dataDir}/wxsearch/index.sqlite`**：
- `docs(rowid INTEGER PK, msg_key TEXT UNIQUE, conversation, sender, time INTEGER, type, text, vector BLOB, model_id)` —— 每条一行,`vector`=该模型的 embedding(float32 blob)。
- FTS5 虚拟表 `docs_fts(text)` —— 与 `docs.text` 同步,BM25 用。
- `meta(key, value)` —— 记当前索引用的 embedding 模型 id。

**检索(混合 + RRF)**：
1. 向量：query 过 EmbedRunner → load `docs` 全部向量成 numpy 矩阵(~46MB@3 万×384）→ 余弦 → 向量 top-k。
2. BM25：`docs_fts MATCH query` + `bm25()` → 关键词 top-k。
3. RRF(k=60)融合两路名次 → 最终排序。可选 `conversation` 过滤。

**模型切换处理**:向量模型专属。`meta` 记索引模型 id;若当前选的 embedding 模型 ≠ 索引模型 → `search` **仍跑 BM25**（跨模型有效），向量半失效并提示「跑 `reindex`」；`reindex` 清空重嵌。

---

## 5. 组件边界 + 工具面 + 集成(照 wxmedia 模式)

**EmbedRunner 边界**(照 AsrRunner）：`embed(texts: list[str]) -> np.ndarray`（批量、L2 归一化）+ `model_id`。具体 `OnnxEmbedRunner` 经 model-manager 解析 embedding 模型（bge-small-zh 轻 / BGE-M3 高）、跑 ONNX Runtime——**真实 ONNX 调用隔离此一处**（带 VERIFY-AGAINST-REAL-MODEL 标记）；核心管线用 `FakeEmbedder`（确定性向量）全测。

**MCP 工具（同 wxmedia/wxvault 框架 + 完整握手 + UTF-8）**：
- `search(query, limit?, conversation?)` → `[{conversation, sender, time, type, text, score}]`
- `index_update()` → 增量索引新消息（懒嵌入）
- `reindex()` → 清空重建（换模型档后）
- `index_status()` → 已索引条数 / 索引模型 / 是否 stale
- `models_status` / `set_model`（embedding 档）

**文件分解（每个单一职责）**：
```
packages/wxsearch/
├── wxsearch/
│   ├── _deps.py         # 复用兄弟 model-manager 解析（同 wxmedia）
│   ├── text_source.py   # 读 Msg 表文本 + join wxmedia 派生文本 → chunk dict 迭代器
│   ├── embed.py         # EmbedRunner Protocol + OnnxEmbedRunner（隔离真实 ONNX）
│   ├── index.py         # index.sqlite:docs + FTS5 + meta;upsert/load_vectors/bm25_search/rrf
│   ├── search.py        # 混合检索(余弦+BM25+RRF) + 增量索引管线
│   └── server.py        # MCP server
├── setup.py  wechat-cc.plugin.json  pyproject.toml  tests/
```

**集成**：`_deps.ensure_model_manager()` 解析兄弟包；只读 wxvault 解密库 + wxmedia derived.sqlite；状态目录 `${dataDir}`（`WXVAULT_STATE_DIR`）；manifest spawn `python3 -m wxsearch.server` + `PYTHONPATH=${pluginDir}`，healthcheck `${dataDir}/out/decrypted`。

---

## 6. 快速变动 / 出货前须定
- **embedding 型号**：bge-small-zh vs BGE-M3（vs Qwen3-Embedding）——需真实中文聊天数据横评后定死（同 model-manager 的遗留）。
- **OnnxEmbedRunner 的真实调用**（ONNX Runtime 推理 + 池化/归一化）——接真实模型时定，隔离在 embed.py 一处。

## 7. 暂不做 / 后续
- reranker、删除消息同步、链接/文件富消息文本、跨账号；这些后续。
- **wxgraph(#2 关系图谱)**：下游消费者，单独一层（那层方案研究里未验证）。

## 8. 推进顺序（本插件内）
_deps → text_source → embed(边界+fake) → index(存储/BM25/RRF) → search(混合+增量) → server+manifest+setup。
