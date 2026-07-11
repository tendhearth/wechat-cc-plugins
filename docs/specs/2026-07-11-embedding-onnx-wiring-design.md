# wxsearch embedding ONNX 推理接通 设计规格

**日期**: 2026-07-11
**状态**: 已通过设计讨论,待写实现计划
**范围**: `packages/wxsearch/wxsearch/embed.py` 的 `_default_embed_fn`(真 ONNX 推理)+ `packages/model-manager` 的 bge-small-zh 源/依赖。

## 1. 背景

wxsearch 的检索管线(index/search/RRF)与 model-manager(分层模型)架子已成,但 **`embed.py:_default_embed_fn` 是 `NotImplementedError` 桩**——"把文字变成向量"没接。这是**语义检索的真·前置**,而且 **wxsearch 和(未来的)memory-search 共用**它。本规格只做这一步:接通 `bge-small-zh-v1.5` 的真 ONNX 推理。

**共享定位**:`OnnxEmbedRunner` / `EmbedRunner` Protocol 已是 source-agnostic 的引擎边界(`embed(texts)→归一化向量`)。接通后,任何数据源(微信消息 / 记忆 .md)都能用同一个 embed 引擎。

## 2. 已核实的事实(定 spec 前查清)

- **模型源**:BAAI 官方 `bge-small-zh-v1.5` 仓是 PyTorch,**无 .onnx**。**`Xenova/bge-small-zh-v1.5` 有现成 ONNX**(`onnx/model.onnx` fp32 + `model_int8.onnx` / `model_fp16.onnx`),含 `tokenizer.json` / `vocab.txt`。→ 用现成 ONNX,**不需 optimum/torch 导出**。
- **依赖**:`onnxruntime` + `tokenizers` 当前**未装**(wxsearch 只依赖 numpy)。按 model-manager"只装当前 config 需要的"原则,选 embedding 档时 setup 装这两个。
- **池化 = CLS**:bge-small-zh-v1.5 的 `1_Pooling/config.json` 是 CLS(取 `last_hidden_state[:,0]`),**不是 mean-pool**(桩里的注释写错了)。
- **onnxruntime 输入**:BERT 系需 `input_ids` + `attention_mask` + `token_type_ids`;输出 `last_hidden_state`(取名以实际 model 的输出名为准,实现时读)。

## 3. 关键决策

- **产物 = `Xenova/bge-small-zh-v1.5` 的 `onnx/model.onnx`(fp32)**先求正确;`model_int8.onnx`(~33MB)作为体积优化选项,横评后再定死。dim=512。
- **tokenizer = HF `tokenizers`(Rust 后端,读 `tokenizer.json`)**——快、无需 transformers/torch。
- **query instruction**:bge-*-**v1.5** 的检索 query 前缀("为这个句子生成表示…")是**可选**小增益;本步 embed 层**对称、不加前缀**;若日后检索质量需要,在 **search 层**给 query 侧单独加(不在 embed 引擎里)。记为后续。
- **registry 源更新**:`bge-small-zh-v1.5` 的 `source_urls` 指向 ONNX 产物。ModelScope 优先(国内),但 ModelScope 若无 ONNX 镜像则 HF `Xenova` 兜底——实现时确认 ModelScope 有无 ONNX;没有就 HF 为主并注明。
- **隐私不变**:全本地推理,零网络(除首次下载模型)。

## 4. 非目标(本步)

engine 抽取(index/search 泛化成通用 chunk — step 2);memory-search 的 .md 源与工具(step 3);daemon 接线(step 4);BGE-M3 高精档;reranker;query instruction 的实际接入。

## 5. 测试(关键:必须真机验证,不只假注入)

- 保留现有 `test_embed.py` 的假注入单测(l2_normalize / runner 归一化 / model_id)。
- **真模型验证(硬要求)**:下载真 `bge-small-zh-v1.5` ONNX,`_default_embed_fn` embed 一组中文句子,断言 **语义合理**:`cos("今天天气很好","天气不错") > cos("今天天气很好","我要还信用卡")`,且输出 `(n,512)` float32。这条证明"真能把中文变成有意义的向量",是本步的存在意义。
- onnxruntime + tokenizers 装好后 `pytest packages/wxsearch` 全绿。
