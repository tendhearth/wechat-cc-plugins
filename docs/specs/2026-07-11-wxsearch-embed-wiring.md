# wxsearch 嵌入运行时接线 设计规格

**日期**: 2026-07-11
**状态**: 已通过设计评审(brainstorming),待写实现计划
**范围**: 接线 `packages/wxsearch` 唯一未接的真实模型缝 `wxsearch/embed.py` 的 `_default_embed_fn`(现抛 NotImplementedError),让 `index_update` + 语义检索在真实数据上跑起来。**不改** wxsearch 其余部分(index/FTS5/cosine/RRF/staleness/MCP 工具已建+测)。轻改 model-manager 注册表 + wxsearch 依赖。

---

## 1. 背景与目标

wxsearch 用可注入 EmbedRunner 边界建成:`embed_fn(model_dir, texts) -> np.ndarray (n,dim)`,`OnnxEmbedRunner` 经兄弟 model-manager `resolve("embedding").id` / `ensure("embedding")→model_dir` 解析嵌入模型;整条管线用 `FakeEmbedder` 测通,只有真实嵌入向量计算是桩(抛 NotImplementedError)。故 `index_update`(要嵌入)与语义 `search` 目前失败;插件已在 wechat-cc 里 disable 待接线。

**目标**:接上真实本地中文嵌入 → index_update + 向量检索在真实微信数据上工作。**全本地**(推理不联网;模型文件首次按需下载一次)。改动**隔离在 embed.py 这一处** + 依赖 + model-manager 注册表微调。

---

## 2. 关键设计决策(评审已定)

- **fastembed 跑两档,model-manager 只管选档。** fastembed(Qdrant,pip 装,不需 torch)自带 ONNX BGE/中文模型 + tokenizer + 池化 + 归一化(正确性天然保证),`cache_dir` 可指状态目录。model-manager 保留两档(resolve/set_model 选档策略),但嵌入 artifacts 置**零 URL**(不下载、只做 marker):`ensure` 建 marker 目录并返回,fastembed 负责真实下载+运行到该目录。**model-manager=策略(哪档),fastembed=机制(拉+跑)。** 代价:嵌入模型不走 model-manager 下载/字节校验(可接受;fastembed correct-by-construction,避免手写 CLS 池化/attention mask 出错)。
- **两档模型**:轻 = `bge-small-zh-v1.5`(fastembed `BAAI/bge-small-zh-v1.5`,512 维,~90MB,先接+先验证);高 = `jina-embeddings-v2-base-zh`(fastembed `jinaai/jina-embeddings-v2-base-zh`,768 维,~640MB)。
- **边界不变**:`embed_fn(model_dir, texts)` 签名不动 → FakeEmbedder 注入与所有现有测试不受影响。真实实现从 `Path(model_dir).name`(= model-manager 的 `<spec.id>`)取 model_id → 映射 fastembed 模型名。
- **维度切换(512↔768)**已被建成并验证过的换模型 reindex 路径覆盖(`meta['embed_model']` 不符 → 仅 BM25 + stale → `reindex` 清空重嵌新维)。

---

## 3. 组件改动(隔离)

### 3.1 `wxsearch/embed.py`(唯一真实改动)
替换 `_default_embed_fn` 为 fastembed 实现;**不改签名**:
```python
_FE = {"bge-small-zh-v1.5": "BAAI/bge-small-zh-v1.5",
       "jina-embeddings-v2-base-zh": "jinaai/jina-embeddings-v2-base-zh"}
_cache = {}   # model_id -> TextEmbedding(加载昂贵,进程内复用)

def _default_embed_fn(model_dir, texts):
    from fastembed import TextEmbedding
    import numpy as np
    mid = Path(model_dir).name
    if mid not in _FE:
        raise ValueError("wxsearch: no fastembed mapping for embedding model %r" % mid)
    if mid not in _cache:
        _cache[mid] = TextEmbedding(_FE[mid], cache_dir=str(model_dir))  # ONNX 首次下载到此,一次
    return np.array(list(_cache[mid].embed(list(texts))), dtype=np.float32)
```
`OnnxEmbedRunner.embed` 仍在外面 `l2_normalize`(对已归一化向量幂等)。fastembed 内部 tokenize→ONNX session→正确池化→归一化。

### 3.2 `model-manager/model_manager/registry.py`(两处微调)
- 高档 `bge-m3` → `id="jina-embeddings-v2-base-zh"`,capability=embedding,tier=high,runtime=onnx。
- 两个 embedding spec 的 artifacts 置**零 URL**(`source_urls=()`,`size_mb` 保留作提示),使 `ensure("embedding")` 只 `mkdir` marker 目录(`models_root/embedding/<id>/` + `.done`)并返回,不下载(`download.ensure` 已有零 URL 分支,实测)。set_model embedding light/high 切档仍生效。
- **背景**:注册表当前把轻档 `source_urls` 指向 `Xenova/bge-small-zh-v1.5`(ONNX,附 NOTE 说 BAAI 是 PyTorch-only)——那是为**未完成的 raw-onnx 路**做的推测性准备(多文件 fetcher + tokenize/池化代码都没建)。选了 fastembed 后 fastembed 按**模型名**从自家目录取,忽略我们的 `source_urls`,故这些 Xenova URL 变无用 → 置零。**须同步改这两个 model-manager 测试**(否则 41 passed 变红):`tests/test_registry.py` 里断言轻档 source_urls 含 Xenova/modelscope-first 的用例 → 改成断言零 URL;`tests/test_manager.py` 里 `resolve("embedding")` 高档 `== "bge-m3"` → 改 `== "jina-embeddings-v2-base-zh"`。

### 3.3 依赖
- `packages/wxsearch/pyproject.toml`:加 `fastembed>=0.7`(它拉 onnxruntime+tokenizers+huggingface-hub,比原 numpy-only 重,但是本地嵌入的必要代价)。
- `packages/wxsearch/setup.py`:装 fastembed(按需,同其他插件 setup 装依赖模式)。numpy 仍装。

---

## 4. 测试

- **现有测试不动**:所有管线/index/search 测试注入 FakeEmbedder / fake embed_fn,边界未动 → 全部照过,不联网、不下模型。
- **两个廉价新增(不下载)**:
  1. **map↔registry 一致性**:import model-manager 注册表,断言每个 `embedding` ModelSpec 的 id 都在 `_FE` 里 —— 挡「加/改档忘了加映射」漂移。
  2. **skip-if-unavailable 真实测试**:若 fastembed 可导入且模型已缓存,嵌入 `["中文测试句子","hello world"]`,断言 shape `(2,512)`、float32、有限值;否则 skip(CI 无模型时跳过,环境有则跑)。`_default_embed_fn` 对未映射 model_id 抛清晰 ValueError(非裸 KeyError,已在 3.1)。
- **VERIFY-AGAINST-REAL 验收(在真实数据上跑一次,非 CI)**:
  1. 轻档 `index_update` 真实解密历史 → fastembed 首次下载 bge-small-zh(~90MB 到状态目录),嵌入真实消息建向量。确认 dim=512、向量有限、`embed_model` 记录。
  2. **BM25 单独会漏的语义查询**:一个目标消息里字面没有的近义/改写查询,确认相关消息经向量路走出来(`vectors_stale: False`、消息排进 `search` 结果)。证明真实嵌入相对关键词的增益。
  3. 通过后才算接线,再 `plugin enable wxsearch`。

---

## 5. 快速变动 / 出货前须定
- **fastembed 模型名核对**:实测 fastembed 0.8 supported 列表含 `BAAI/bge-small-zh-v1.5`(512d) 与 `jinaai/jina-embeddings-v2-base-zh`(768d);升级 fastembed 若改名需同步 `_FE`(一致性测试会挡 registry 侧,但 fastembed 侧改名要人工核)。
- **首次下载体验**:第一次 index_update 会阻塞下载 ~90MB(轻档);工具描述/日志应提示「首次建索引会下载嵌入模型」。
- **onnxruntime 平台 wheel**:mac arm64 实测 onnxruntime 1.27 可装;Windows/Linux 走各自 wheel(fastembed 依赖解析处理)。

## 6. 暂不做 / 后续
- wxmedia 的 ASR 接线(单独,下一件)。
- reranker、embedding 型号横评定死(高档就先 jina-zh,后续可换 e5-large/jina-v3 —— 只改 registry id + `_FE` 一行)。
- model-manager 通用 repo-aware fetcher(本方案用 fastembed 绕过,不需要)。

## 7. 推进顺序
registry(高档 id + 零 URL + 同步改 test_registry/test_manager)→ embed.py(真实 fastembed fn + map + map↔registry 一致性测试 + skip-if-unavailable 真实测试)→ deps(pyproject+setup)→ VERIFY-AGAINST-REAL 真实验收(轻档 index_update 真实数据 + BM25 会漏的语义查询)。
