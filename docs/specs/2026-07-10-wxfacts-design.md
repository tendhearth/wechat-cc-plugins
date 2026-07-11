# wxfacts (关系情报 / LLM 抽取层) 设计规格

**日期**: 2026-07-10
**状态**: 已通过设计评审(brainstorming),待写实现计划
**范围**: `wechat-cc-plugins` monorepo 的 `packages/wxfacts` —— 增益插件家族的**抽取/知识层**,建在 wxgraph(结构化图)与 wxsearch(检索)之上。是 wxgraph 设计里点名推迟的「第二阶段 LLM 抽取」。

---

## 1. 背景与目标

wxgraph 第一阶段(纯本地结构化画像 + 关系图)已合并 main。本层把原始聊天历史转成**关于人的结构化断言(claims/facts)**:实体(公司/地点/兴趣)、关系(同事/家人/债权)、义务(承诺/欠钱/待办)、属性、事件。让 agent 能回答「我对某人都知道些什么」「谁欠我钱/我欠谁」「谁是我在 X 公司的同事」。

**核心架构决策(评审已定)= Agent 驱动,插件保持被动本地。** wechat-cc 里的 agent(Claude/DeepSeek)本身已连着用户的 provider;而守护进程刻意不把密钥给插件子进程(F2 防泄露)。故本插件**不自己调 LLM**:它只做本地检索 + 事实存储,真正的 LLM 抽取由 agent 用它自己已连的模型完成,把结构化断言写回插件。

**这消解了 provider 边界问题**:wxfacts **永不联网、永不碰密钥、无 provider SDK**,privacy 结构性满足——插件只把「用户本就有权看的解密文本片段」递给 agent,自己不向外发任何东西;唯一的网络跳是 agent 自己的 provider 调用(agent 既有的信任边界,不是 wxfacts 新引入的)。

**数据来源(纯本地,只读)**:
- **消息**:复用兄弟 `wxgraph.source.iter_messages`(读 wxvault 解密 `out/decrypted/message_*.sqlite`,含 zstd 解压)。
- **联系人**:wxgraph 的 `${dataDir}/wxgraph/graph.sqlite`(contacts + resolve_name),**若存在**用来解析名字/展示名;不存在则回退裸 username(松耦合:wxfacts 只靠 `out/decrypted` 也能跑,wxgraph 只是增强)。
- **输出**:写 `${dataDir}/wxfacts/facts.sqlite`。

---

## 2. 关键设计决策(评审已定)

- **Agent 驱动、插件被动**:插件零网络、零 LLM、零 provider 密钥;抽取智能在 agent 侧。因此**没有 runner/provider 边界要建,测试里也没东西要 fake**。
- **灵活 claim 表(一张表)**:实体/关系/义务/属性/事件统一一行,`kind` 开放词表;按 `(contact, predicate, value)` 去重合并;provenance 回溯 `msg_key`。
- **水位候选馈送(系统回填 + 增量)**:每联系人一个抽取水位 `last_ts`;`extraction_batch` 发下一批未抽取消息,`record_facts` 写事实并推进水位——**零事实的批也推进水位**(处理过即算抽取过),保证 backfill 收敛、增量正确。
- **永不删除**:义务已还 → `resolved`,过时/纠正 → `superseded`;provenance 神圣。
- **依赖极简**:复用兄弟 `wxgraph`(via `_deps`)取消息与联系人;唯一真实依赖 `zstandard`(经 wxgraph.source 传递)。**无网络、无 numpy、无 provider SDK、无 model-manager。**

---

## 3. 存储

`${dataDir}/wxfacts/facts.sqlite`:
```sql
facts(
  id INTEGER PRIMARY KEY,
  contact TEXT,            -- 事实所关于的联系人 username(可经 wxgraph 模糊解析)
  kind TEXT,               -- 开放词表:entity | relation | obligation | attribute | event
  predicate TEXT,          -- 如 works_at / owes_me / birthday / colleague_of
  value TEXT,              -- 宾语:"阿里巴巴" / "500元" / "March 3"
  related_contact TEXT,    -- relation 类指向的另一联系人 username(可空)
  time_ref TEXT,           -- 自由文本时间锚:"2026-08 due" / "since 2019"(可空)
  confidence TEXT,         -- low | med | high(agent 给,比浮点更适合 LLM)
  source_msg_keys TEXT,    -- JSON 数组,回溯 wxvault 消息(provenance)
  status TEXT,             -- active | resolved | superseded(默认 active)
  created_at INTEGER, updated_at INTEGER,
  UNIQUE(contact, predicate, value)
)
extraction_state(contact TEXT PRIMARY KEY, last_ts INTEGER, updated_at INTEGER)
```

**去重/合并**:`record_facts` 按 `(contact, predicate, value)` **upsert**——新断言插入;重复则**合并**:`source_msg_keys` 取并集、`confidence` 取较高、刷新 `updated_at`、`related_contact`/`time_ref` 若新给则更新。同一事实跨多条消息出现会累积 provenance 而非重复。`find_facts`「谁欠我钱」于是每个真实义务一行。

**状态生命周期**:不删除。义务已还 → `resolved`;纠正/过时 → `superseded`。`set_fact_status(id, status)` 驱动;查询默认 `status='active'`。

**水位**:`extraction_state.last_ts` 是每联系人高水位。`extraction_batch(contact)` 发 `ts > last_ts`(限 `limit`)的消息,返回编码了 `{contact, covers_until_ts}` 的 `batch_id`。`record_facts(batch_id, …)` 写断言并把该联系人 `last_ts` **单调推进**到 `covers_until_ts`——**零事实也推进**(窗口处理过就不再发)。这让 backfill 终止、增量追赶正确:消息一旦其窗口被 agent 处理过就算「已抽取」,无论有没有出事实。

**provenance 由 agent 逐事实给**:每条断言带支撑它的具体 `source_msg_keys`(批次的子集);agent 略去则事实仍记但 provenance 空(标记低可信)。

---

## 4. 组件边界 + 工具面 + 集成(照 wxgraph/wxsearch 模式)

**文件分解(每个单一职责)**:
```
packages/wxfacts/
├── wxfacts/
│   ├── _deps.py     # 解析兄弟 wxgraph(照 wxsearch/wxmedia 解析 model-manager)
│   ├── source.py    # 候选馈送:复用 wxgraph.source.iter_messages 建每联系人未抽取窗口 + batch_id 编解码
│   ├── store.py     # facts.sqlite:facts + extraction_state;upsert 去重/合并、水位推进、查询原语
│   ├── facts.py     # 编排:选批(最大 backlog)、record+推水位、查询、经 wxgraph 解析名字(可选)
│   └── server.py    # MCP stdio server
├── setup.py  wechat-cc.plugin.json  pyproject.toml  tests/
```

**MCP 工具(完整握手 + UTF-8,同框架;全本地,智能在 agent 侧)**:
- `extraction_batch(contact?, limit=40)` → `{batch_id, contact, display, covers_until_ts, messages:[{msg_key, sender, time, text}]}`。无 `contact` 则选**最大 backlog** 联系人(全量回填大头优先)。全部已抽取时返回 `{done: true}`。
- `record_facts(batch_id, facts:[{kind, predicate, value, related_contact?, time_ref?, confidence?, source_msg_keys?}])` → upsert 合并断言 + 推进该批水位。返回 `{recorded, merged, advanced_to}`。`facts` 空列表合法——只推水位(窗口无可留)。
- `contact_facts(name)` → 经 wxgraph 模糊解析 → 该联系人的 active 事实,按 `kind` 分组。
- `find_facts(kind?, predicate?, query?, status="active", limit=50)` → 跨联系人查询(`query` = predicate/value 子串)。「谁欠我钱」= `kind=obligation` + 匹配;「未了承诺」= `kind=obligation status=active`。
- `set_fact_status(id, status)` → `resolved` / `superseded`。
- `extraction_status()` → backlog 概览:每联系人 `{extracted_until, remaining}`、已追平联系人数、按 kind 的事实总数。

**Agent 工作流**:反复调 `extraction_batch`(回填)→ 用自己模型抽取 → 每批 `record_facts`;增量 = 新消息抬高 backlog、agent 追平。节奏与 token 成本由 agent 掌握(它是付费方)。

**集成**:`_deps.ensure_wxgraph()` 解析兄弟 wxgraph;`source.py` import `wxgraph.source.iter_messages`;联系人/展示名/解析优先读 wxgraph `graph.sqlite`,缺失则回退裸 username;写 `${dataDir}/wxfacts/facts.sqlite`;状态目录 `${dataDir}`(`WXVAULT_STATE_DIR`);manifest spawn `python3 -m wxfacts.server` + `PYTHONPATH=${pluginDir}` + `WXVAULT_STATE_DIR=${dataDir}`;healthcheck `requiresPaths: ["${dataDir}/out/decrypted"]`;`setup.py` 装 `zstandard` + 解析兄弟 wxgraph,**无模型下载、无网络**。manifest 字段照 wxmedia 逐字段。

**测试**:agent 驱动的红利——**没东西要 fake**(插件不调 LLM)。tests 建 fixture 解密消息库,断言:批窗口、水位推进(含零事实批不再发)、`record_facts` 按 `(contact,predicate,value)` 的插入-vs-合并去重、provenance 并集、`find_facts`/`contact_facts` 查询、状态生命周期。全确定性。

---

## 5. 快速变动 / 出货前须定
- **batch_id 编码**:无状态编码 `{contact, covers_until_ts}`(JSON/紧凑串);`record_facts` 解码推水位。用户名不含分隔符(wxid_/@chatroom),但仍用 JSON 稳妥。
- **kind/predicate 词表**:开放、agent 定;可在工具描述里给建议词(works_at/owes_me/promised/colleague_of/…)引导一致性,但不强制枚举。
- **最大 backlog 选批**:每次全量扫消息按 1:1 会话分组计 `ts>last_ts` 计数(个人规模 ms 级,可接受;不缓存 = YAGNI)。
- **confidence 语义**:low/med/high 由 agent 判;provenance 空 → 视作低可信(工具描述提示 agent 尽量给 source_msg_keys)。

## 6. 暂不做 / 后续
- 插件自驱 provider 抽取(本设计明确放弃,agent 驱动);后台/定时批抽取(需插件联网,不做)。
- 事实冲突自动消解(留给 agent 用 status superseded 手动处理)、跨账号、群消息里对第三方的事实抽取(v1 只按 1:1 会话联系人建 backlog;群文本可后续作为额外候选)。
- 把事实回灌 wxgraph 的边/画像(可后续:如从 obligation 生成关系强度信号)。

## 7. 推进顺序(本插件内)
_deps → source(候选馈送 + batch_id) → store(facts.sqlite 去重/水位) → facts(编排 + 查询 + 解析) → server + manifest + setup。
