# wxsearch embedding ONNX 推理接通 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans. Steps use `- [ ]`.

**Goal:** 接通 `bge-small-zh-v1.5` 的真 ONNX 推理,让 `embed.py:_default_embed_fn` 真能把中文文字变成语义向量——解锁 wxsearch 与未来 memory-search 的语义检索。

**Architecture:** 用 `Xenova/bge-small-zh-v1.5` 现成 ONNX + HF `tokenizers` + onnxruntime,CLS 池化。registry 指向 ONNX 源,setup 装 onnxruntime+tokenizers。

**Tech Stack:** Python,pytest;`onnxruntime`、`tokenizers`、`numpy`。

## Global Constraints

- Spec: `docs/specs/2026-07-11-embedding-onnx-wiring-design.md`。要点:池化 = **CLS**(`last_hidden_state[:,0]`,非 mean);模型 = Xenova `onnx/model.onnx` fp32;tokenizer 用 `tokenizers` 读 `tokenizer.json`;query instruction 本步不加;全本地。
- 保持 `EmbedRunner`/`OnnxEmbedRunner` 接口不变(`embed_fn(model_dir, texts)→(n,dim) np.float32`,未归一化;runner 负责 l2_normalize)。
- **必须真机验证**(下载真模型 + 中文语义 cosine 断言),不只假注入单测。
- 显式 `git add`;pytest 全绿。

### Task 1: registry ONNX 源 + setup 依赖

**Files:** `packages/model-manager/model_manager/registry.py`、`packages/wxsearch/setup.py`(或 model-manager setup — 看 embedding 依赖装在哪合适)、相应 test。

- registry 的 `bge-small-zh-v1.5` 条目 `source_urls` 指向 ONNX 产物:HF `https://huggingface.co/Xenova/bge-small-zh-v1.5`(取 `onnx/model.onnx` + `tokenizer.json` + `vocab.txt` + `config.json`);ModelScope 若有 ONNX 镜像则优先加在前,没有就注明"ONNX 仅 HF"。保留 dim/sha 字段(sha 实现时按真文件填或留 None + 注明)。
- setup:当解析到 embedding 档(onnx runtime)时,`pip install onnxruntime tokenizers`(numpy 已有)。mac 可用 onnxruntime 默认 CPU EP(MLX 留后)。
- [ ] 测试:registry 解析 `bge-small-zh-v1.5` 返回的 spec 含 ONNX 源 + runtime=onnx;(setup 的依赖装配可用 dry-run/mock 断言命令,别真装到断言里)。
- [ ] `pytest packages/model-manager` 绿。
- [ ] Commit: `feat(model-manager): point bge-small-zh at ONNX source + onnxruntime/tokenizers deps`.

### Task 2: `_default_embed_fn` 真 ONNX 推理 + 真机语义验证

**Files:** `packages/wxsearch/wxsearch/embed.py`、`packages/wxsearch/tests/test_embed.py`(+ 一个真机验证测试,标 `@pytest.mark.slow`/`integration` 便于隔离)。

- 实现 `_default_embed_fn(model_dir, texts)`:
  1. 从 `model_dir` 加载 tokenizer:`from tokenizers import Tokenizer; tok = Tokenizer.from_file(str(model_dir/"tokenizer.json"))`。开启 padding(`tok.enable_padding()`)+ truncation(`tok.enable_truncation(max_length=512)`)。
  2. `enc = tok.encode_batch(list(texts))` → 组 batch:`input_ids`、`attention_mask`(有的 tokenizer 需 `type_ids`→`token_type_ids`;bge/BERT 需要,全 0 也要给)。转 `np.int64`。
  3. `import onnxruntime as ort; sess = ort.InferenceSession(str(model_dir/"model.onnx"), providers=["CPUExecutionProvider"])`(缓存 session,别每次建——模块级或 runner 级缓存)。读 `sess.get_inputs()` 的名字动态喂(名字可能是 input_ids/attention_mask/token_type_ids)。
  4. `out = sess.run(None, feeds)`;取 `last_hidden_state`(第一个输出或按 `sess.get_outputs()[0].name`)。
  5. **CLS 池化**:`emb = last_hidden_state[:, 0, :]`(取 [CLS])→ `np.asarray(emb, dtype=np.float32)`,形状 `(n, 512)`。返回(**不**在这归一化;`OnnxEmbedRunner.embed` 已 l2_normalize)。
  - onnxruntime session 与 tokenizer 用模块级/runner 级缓存,避免每次 embed 重载(大文件)。
- [ ] **假注入单测**(现有的保留 + 跑绿):l2_normalize、runner 归一化、model_id。
- [ ] **真机验证测试**(`integration`,需真模型):在测试里(或一个 `scripts/verify_embed.py`)下载真 `Xenova/bge-small-zh-v1.5` ONNX 到临时 model_dir(或用 model-manager ensure),`_default_embed_fn` embed `["今天天气很好","天气不错","我要还信用卡"]`,l2_normalize 后断言 `cos(v0,v1) > cos(v0,v2)` 且都 `(3,512)` float32。**这条必须真跑过、真绿**(证明中文语义有效)。若 CI 无网,标 `@pytest.mark.integration` 便于本地/带网跑;实现者**必须本地真跑一次并在报告里贴 cosine 数值**。
- [ ] `pytest packages/wxsearch`(含 integration,若装好 onnxruntime+tokenizers)绿。
- [ ] Commit: `feat(wxsearch): real ONNX embedding inference for bge-small-zh (CLS pooling)`.

## Self-Review notes

Spec §3 全覆盖:registry 源(T1)、依赖(T1)、_default_embed_fn+CLS(T2)、真机语义验证(T2)。接口不变(embed_fn 契约)。CLS 而非 mean 是最易错点——测试的 cosine 断言会抓 mean-pool 的退化。session/tokenizer 缓存防性能坑。真机验证是本步存在意义,不能只假注入。
