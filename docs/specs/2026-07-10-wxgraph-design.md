# wxgraph (关系图谱 / CRM — 结构化层) 设计规格

**日期**: 2026-07-10
**状态**: 已通过设计评审(brainstorming),待写实现计划
**范围**: `wechat-cc-plugins` monorepo 的 `packages/wxgraph` —— 增益插件家族第 4 层(结构化)的**第一阶段:纯本地结构化聚合**。**不含** LLM 实体/关系/义务抽取(第二个 spec,单独)。

---

## 1. 背景与目标

model-manager(分层模型)、wxmedia(语音→文字)、wxsearch(语义检索)已完成合并 main。wxgraph 是结构化层:把本地微信历史聚合成**每个联系人的关系画像 + 一张以我为中心的关系图**,让 agent 能回答「谁是我最亲近/最疏远的人」「我和某人的互动全貌」「A 和 B 在我的世界里怎么连着」。

**分阶段(评审已定)**:wxgraph 有两个性质迥异的半边——①结构化聚合(纯 SQL 统计,全本地、零网络、零 provider);②LLM 抽取(实体/关系/义务经用户 provider,RAG 用 wxsearch)。**本 spec 只做 ①**。②的 provider 边界与抽取 schema 推迟到第二个 wxgraph spec(那部分研究未验证)。

**隐私(硬约束)**:本阶段**零网络、零 provider 调用**,原始数据不出机器。只读 wxvault 解密产物。

**数据来源(纯本地,只读,不 import 闭源 wxvault)**:
- **联系人真名**:wxvault 解密的 `${dataDir}/out/decrypted/contact.sqlite` 的 `contact(username, remark, nick_name, alias)` —— `display = remark or nick_name or alias or username`。
- **消息**:`${dataDir}/out/decrypted/message_*.sqlite` 的 `Msg_<md5>` 表(`local_id, local_type, real_sender_id, create_time, server_id, message_content`)+ `Name2Id(rowid, user_name, is_session)`(rowid ↔ username,表名 md5 反查会话 username;与 wxsearch 同源同法)。

---

## 2. 关键设计决策(评审已定)

- **只做结构化层**,LLM 抽取单独第二 spec。
- **图的形状 = 以我为中心的星型图(ego)+ 强信号联系人↔联系人边**。个人库只能看到「我↔每个联系人」1:1 聊天 + 群里谁发言;看不到别人私聊。故:
  - `me` 边:我↔联系人,权重 = closeness 总分。
  - `mention` 边:联系人↔联系人,**只用强信号**——群里 A 直接 @提及 / 引用 / 回复 B。**刻意排除**噪声大的「共群共现」当边(共现≠关系;共群数仅作为画像里的一个计数)。
- **打分 = 透明分项 + 一个可解释、可调权重的合成分**(不黑箱,不硬贴分类标签)。
- **1:1 联系人是主节点**;群(`@chatroom`)作为共现/@提及边的上下文 + 一个轻量计数,**不做**完整群分析(推迟)。
- **依赖极简**:**无** model-manager / wxsearch / wxmedia / numpy。唯一新依赖 = **`zstandard`**,且只为解析 `message_content` XML 抽 `mention` 边(其余全读元数据列,不解内容)。
- **刷新 = 按需全量 rebuild**(个人规模几万条 = 秒级);增量按水位是后续易加项,非 v1。

---

## 3. 计算什么(信号 + 打分)

**owner(我)** = 本机账号 username(从 wxvault 解密产物读取;见 §7 出货前须定的 owner 判定)。方向:1:1 聊天里 `real_sender_id` 解析出的 username == owner ⇒ 我发(sent),否则对方发(recv)。

**每个 1:1 联系人的原始信号**(全部来自消息元数据列,不解 content):
- `total`, `sent`, `recv`
- `first_ts`, `last_ts`, `known_days`(= (now − first_ts)/天), `active_days`(有消息的不同自然日数)
- `initiations`(与上一条间隔 > 6 小时后我方发的第一条,近似「我主动发起」次数)
- 按类型计数 `types`(text/voice/video/image/sticker/link/file/call/location/… 由 `local_type` 及 type=49 子类解码,复用 wxvault_mcp 的类型映射逻辑,**只需 local_type + app 子类,不需完整正文**)
- `transfer_in` / `transfer_out`(转账收/发次数;红包同法可并入或单列 —— v1 只计转账+红包次数,不解金额)
- `shared_groups`(我和该联系人**都发过言**的群数)

**四个透明分项(各归一化到 0–1,与原始事实一起存)**:

| 分项 | 公式 | 直觉 |
|---|---|---|
| `s_volume` | `log1p(total) / log1p(P95_total)`,clamp [0,1] | 聊得多不多(P95 归一,避免单个离群把大家压平) |
| `s_recency` | `exp(-days_since_last / 90)` | 当下热度(≈90 天 0.37,180 天 0.13) |
| `s_reciprocity` | `1 − |sent − recv| / max(1, sent+recv)` | 互惠 vs 单向 |
| `s_intimacy` | `log1p(n_voice + n_call + n_transfer) / log1p(P95)`,clamp | 亲密互动信号 |

其中 `P95_total` / `P95_intimacy` = 所有 1:1 联系人对应量的 95 百分位(至少为 1,避免除零);`days_since_last = (now − last_ts)/天`,`now` 由调用方传入(可测,不用 `Date.now()` 之外的隐时钟)。

**合成分**(默认权重,存 `meta`,可调):
```
closeness = 0.35·s_recency + 0.30·s_volume + 0.20·s_intimacy + 0.15·s_reciprocity
```

**派生查询**:
- `neglected`(之前亲近、如今疏远)= 按 `(s_volume + s_intimacy)/2 · (1 − s_recency)` 降序。
- `top_contacts(by=…)` 直接按对应列/合成分排序。

---

## 4. 图的边

一张 `edges` 表,两种 `kind`:
- **`me`**:`a = owner`, `b = 联系人 username`, `weight = closeness`。以我为中心的星型。
- **`mention`**:`a`、`b` 均为联系人 username,来自群里 A 对 B 的**强信号**:
  - `@提及`:消息 XML 的 `<atuserlist>` 携带被 @ 的**真实 wxid**(可直接解析到 username)。
  - `引用/回复`:type=49 `<refermsg>` 的 `<chatusr>`(被引用消息发送者 username,若有)优先;退化用 `<displayname>`(昵称,best-effort 匹配 contact 的 nick/remark)。
  - `weight` = A→B 交互次数(方向保留:`(a,b)` 有序)。解析不到对方 username 的丢弃(不猜)。

`mention` 边解析是**唯一**需要读 `message_content`(可能 zstd 压缩)的地方,故引入 `zstandard`(解压逻辑照 wxsearch/wxvault_mcp:BLOB 且前 4 字节 == `\x28\xb5\x2f\xfd` 则解压,再 utf-8 解码)。

---

## 5. 存储

`${dataDir}/wxgraph/graph.sqlite`:
```sql
contacts(
  username TEXT PRIMARY KEY, display TEXT, is_group INTEGER,
  total INTEGER, sent INTEGER, recv INTEGER,
  first_ts INTEGER, last_ts INTEGER, known_days INTEGER, active_days INTEGER,
  initiations INTEGER, transfer_in INTEGER, transfer_out INTEGER, shared_groups INTEGER,
  types TEXT,                         -- 每类型计数的 JSON,如 {"text":1203,"voice":88,...}
  s_volume REAL, s_recency REAL, s_reciprocity REAL, s_intimacy REAL, closeness REAL
)
edges(a TEXT, b TEXT, kind TEXT, weight REAL, PRIMARY KEY(a, b, kind))   -- kind ∈ {'me','mention'}
meta(key TEXT PRIMARY KEY, value TEXT)   -- owner, built_at(epoch), weights(JSON), source_max_mtime
```

`rebuild()` 清空三表重算。`graph_status` 的 **stale** = 任一源 `message_*.sqlite` 的 mtime > `meta.built_at`(或 `source_max_mtime` 变化)。

---

## 6. 组件边界 + 工具面 + 集成(照 wxsearch/wxmedia 模式)

**文件分解(每个单一职责)**:
```
packages/wxgraph/
├── wxgraph/
│   ├── source.py    # 只读 contact.sqlite + message_*.sqlite 的 reader:联系人 display、
│   │                #   逐消息迭代(username/direction/type/ts)、群共现、mention 原料(zstd 解 content)
│   ├── profile.py   # 聚合 → 原始信号 + 四分项 + closeness(P95 归一、权重可注入);纯函数、易测
│   ├── edges.py     # 从 message_content XML 抽 @atuserlist / refermsg 的 mention 边
│   ├── store.py     # graph.sqlite:建表 + rebuild 写入 + 查询原语(get_contact/top/subgraph/connectors)
│   ├── graph.py     # 编排:build(state_dir, now, weights?) + 各查询封装 + 名字模糊解析
│   └── server.py    # MCP stdio server
├── setup.py  wechat-cc.plugin.json  pyproject.toml  tests/
```
（v1 无兄弟依赖,故 `_deps.py` 可省;若为一致性保留则不引用任何兄弟包。）

**MCP 工具(完整握手 + UTF-8,同 wxmedia/wxsearch 框架)**:
- `contact_profile(name)` → 模糊解析 name → 完整画像:原始事实 + 四分项 + closeness + `types` 明细 + shared_groups + top `mention` 伙伴。
- `top_contacts(by, limit=20, kind="person")` → 排序列表;`by ∈ {closeness, volume, recency, reciprocity, neglected}`;`kind` 过滤 person / group。
- `relationship_subgraph(center?, limit=30)` → nodes + edges(ego 星型 + top-N 之间的强 `mention` 边),给 agent 推理/渲染。
- `connectors(name_a, name_b)` → 两人在我世界里的连接:共群 + 彼此的 mention/引用链。
- `rebuild()` → 从解密库全量重算。
- `graph_status()` → 联系人数 / `built_at` / stale 标志。

**名字解析**:输入先匹 `display`(remark/nick)再匹 `username`;歧义时返回候选短列表,不硬猜。

**集成**:只读 wxvault 解密库;状态目录 `${dataDir}`(`WXVAULT_STATE_DIR`);manifest spawn `python3 -m wxgraph.server` + `PYTHONPATH=${pluginDir}`,`WXVAULT_STATE_DIR=${dataDir}`;healthcheck `requiresPaths: ["${dataDir}/out/decrypted"]`;`setup.py` 只装 `zstandard`(真 PyPI 包),**无模型下载、无兄弟包**。manifest 字段照 wxmedia 逐字段(name/kind/version/minWechatCcVersion/displayName/description/spawn/healthcheck/setup/requires/tools)。

**测试**:纯聚合极易测——tests 建微型 fixture `contact.sqlite` + `message_*.sqlite`(照 wxsearch 做法),断言精确画像统计与分项数学;喂 fixture `refermsg`/`atuserlist` XML 验证边抽取。无网络、无需 fake。`now` 作为参数注入使 recency/known_days 可确定性测试。

---

## 7. 快速变动 / 出货前须定
- **owner(我)判定**:需从 wxvault 解密产物稳定拿到本机账号 username(wxvault_mcp 已有 owner 概念;确认对应文件/字段)。owner 错会把 sent/recv 全反。
- **红包 vs 转账**:v1 计次数不解金额;是否并入 `transfer_*` 或单列,实现时定死。
- **mention 边 displayname→username 的模糊匹配**:昵称可能重名/改名,best-effort,匹配不到就丢;不做跨昵称消歧。

## 8. 暂不做 / 后续
- **LLM 抽取(第二 wxgraph spec)**:实体/关系/义务经 provider,RAG 用 wxsearch —— provider 边界(OpenAI 兼容 endpoint+key 如何注入插件进程,wechat-cc 目前无此约定)与抽取 schema 那时定。
- 完整群分析(最活跃成员、群画像)、增量按水位、转账金额解析、跨账号。

## 9. 推进顺序(本插件内)
source → profile(打分) → edges → store → graph(编排+查询) → server + manifest + setup。
