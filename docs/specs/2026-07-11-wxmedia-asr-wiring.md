# wxmedia ASR 接线 设计规格

**日期**: 2026-07-11
**状态**: 已通过设计评审(brainstorming),待写实现计划
**范围**: 接线 `packages/wxmedia` 唯一未接的真实模型缝 `wxmedia/asr.py`(现 `SenseVoiceRunner` 指向不存在的 SenseVoice-GGUF 二进制,`voice_backfill` 真机失败)。**不改** wxmedia 其余部分(SILK 解码 via pilk、voice_source、transcribe 管线、DerivedStore、MCP server 已建+测)。轻改 model-manager 注册表 + wxmedia 依赖。**照搬刚完成并真机验证过的 wxsearch 嵌入接线套路**(用现成 pip 库 fastembed 代替手搓 onnx/二进制)。

---

## 1. 背景与目标

wxmedia 用可注入 AsrRunner 边界建成:`transcribe(wav_path) -> str`;管线 = voice_source 读解密 `media_*.sqlite` 的 `VoiceInfo(svr_id, local_id, voice_data)` → `silk.to_wav`(pilk,已处理微信在标准 SILK v3 前多加的 1 字节)→ `asr.transcribe(wav)` → DerivedStore 写 `wxmedia/derived.sqlite`。整条管线用 fake AsrRunner 测通,**只有真实语音转文字是桩**(`_default_runner_cmd` 指向不存在的 `sense-voice` 二进制)。故 `voice_backfill` 真机失败;插件当前在 daemon 里 `plugin disable`。

**目标**:接上真实本地中文 ASR → `voice_backfill` 把真实语音转成可搜索文本(写 derived.sqlite)。**全本地**(推理不联网;模型首次下载一次)。改动**隔离在 asr.py 这一处** + 依赖 + 注册表微调。

**实测数据契约**:真机 `out/decrypted/media_0.sqlite` 有 **214 条 VoiceInfo 语音 blob**,样本头 `02 23 21 53 49 4C 4B 5F 56 33` = `\x02` + `#!SILK_V3`(证实微信多加的前导字节,`silk.fix_silk` 已正确剥离)。

---

## 2. 关键设计决策(评审已定)

- **引擎 = faster-whisper(CTranslate2 Whisper,pip、无 torch、自管模型下载,强中文)** —— 与 wxsearch 用 fastembed 同模式(现成库代替手搓二进制/onnx;已验证好用)。model-manager 只管选档(zero-URL marker artifacts),faster-whisper 负责下载+运行。放弃现有代码假设的 SenseVoice-GGUF 二进制路(=wxsearch 放弃的 raw-onnx 路)。
- **两档**:轻 = `whisper-small`(faster-whisper `small`,~500MB,CPU int8 快,先接+先验证);高 = `whisper-large-v3`(faster-whisper `large-v3`,~3GB,最好)。asr.py 里 `_WHISPER` 映射注册表 id → faster-whisper 模型名。
- **强制 `language="zh"`** —— Whisper 对极短片段易误判语种/幻觉,钉死中文。
- **保留可注入缝**:`FasterWhisperRunner(model_manager, transcribe_fn=None)`,默认 `_default_transcribe`;测试注入 fake transcribe_fn 免下载。`_WHISPER` 未命中 model_id → `ValueError`,且检查在 `from faster_whisper import` **之前**(无 faster-whisper 也能测该分支)。
- **SILK 解码不动**(pilk 已完成,含微信前导字节处理)。管线、DerivedStore、server 框架不动(server 只换 runner import 一行)。

---

## 3. 组件改动(隔离)

### 3.1 `wxmedia/asr.py`(唯一真实改动)
保留 `AsrRunner` Protocol(`transcribe(wav_path) -> str`)。删除 subprocess 版 `SenseVoiceRunner` + `_default_runner_cmd` + `_parse_output`,换成 faster-whisper 版:
```python
_WHISPER = {"whisper-small": "small", "whisper-large-v3": "large-v3"}
_cache = {}   # model_id -> WhisperModel(加载昂贵,进程内复用)

def _default_transcribe(model_dir, model_id, wav_path):
    if model_id not in _WHISPER:                      # 在 import 之前 -> 可测、清晰报错
        raise ValueError("wxmedia: no faster-whisper mapping for asr model %r" % model_id)
    from faster_whisper import WhisperModel
    if model_id not in _cache:
        _cache[model_id] = WhisperModel(_WHISPER[model_id], device="cpu",
                                        compute_type="int8", download_root=str(model_dir))
    segments, _info = _cache[model_id].transcribe(wav_path, language="zh")
    return "".join(s.text for s in segments).strip()


class FasterWhisperRunner:
    def __init__(self, model_manager, transcribe_fn=None):
        spec = model_manager.resolve("asr")
        self.model_id = spec.id
        self._model_dir = Path(model_manager.ensure("asr"))
        self._fn = transcribe_fn or _default_transcribe

    def transcribe(self, wav_path):
        return self._fn(self._model_dir, self.model_id, wav_path)
```

### 3.2 `model-manager/model_manager/registry.py`
- 轻档 asr `sensevoice-small-q8` → `id="whisper-small"`(capability=asr,tier=light,runtime="whisper.cpp" 保留或改 "faster-whisper",信息字段无所谓)。高档保留 `whisper-large-v3`。
- 两个 asr spec 的 artifacts 置**零 URL**(`Artifact("any", [], size_mb=…)` —— small~500,large-v3~3000),`ensure("asr")` 只 mkdir marker、不下载,faster-whisper 按名下载。set_model asr light/high 切档仍生效。
- **须同步改耦合的 model-manager 测试**(否则 41-测套件变红,已 grep 确认):
  - `tests/test_registry.py::test_sensevoice_is_light_asr_and_cross_platform` 断言轻档 id `== "sensevoice-small-q8"` + 跨平台 artifacts → 改断言 `whisper-small` + zero-URL(`art.source_urls == []`),重命名。
  - `tests/test_manager.py` 第 8 行 `resolve("asr").id == "sensevoice-small-q8"`(light preset)→ `== "whisper-small"`。(第 20 行 high `== "whisper-large-v3"` 不变。)
  - `tests/test_config.py` 用 `overrides={"asr": "sensevoice-small-q8"}` 做 round-trip;Config 只存字符串不校验注册表,技术上仍过,但语义过时 → 顺手改成 `"whisper-small"`。

### 3.3 `wxmedia/wxmedia/server.py`
`main()` 里 `from .asr import SenseVoiceRunner` → `from .asr import FasterWhisperRunner`,构造 `FasterWhisperRunner(manager)`(一行)。

### 3.4 依赖
- `packages/wxmedia/pyproject.toml`:加 `faster-whisper>=1.0`(拉 ctranslate2 + av + tokenizers;pilk 已是依赖)。
- `packages/wxmedia/setup.py`:装 faster-whisper(按需,同现有 pilk/numpy 模式)。

---

## 4. 测试

- **现有管线测试不动**:`transcribe_all` 等注入 fake AsrRunner,边界未动 → 全过,不下模型。
- **重写 `test_asr_runner.py`**(原测 subprocess `SenseVoiceRunner` + `_parse_output` + `runner_cmd`,这些全删):改测 `FasterWhisperRunner` + 注入 fake `transcribe_fn`(断言收到 `(model_dir, model_id, wav_path)`、runner 返回其文本、model_id 来自 resolve);加 `_default_transcribe` 对**未映射 model_id → ValueError**(在 faster-whisper import 之前,无需装库);删掉 `_parse_output`/subprocess 相关用例(那些函数已不存在)。
- **map↔registry 一致性**:断言两个 asr 档 id(`for_capability_tier("asr","light"/"high").id`)都在 `_WHISPER` 键里 —— 挡「改档忘映射」漂移。
- **无 CI 测试下载模型**。真实 ASR 由 VERIFY 步覆盖。
- **VERIFY-AGAINST-REAL(接线后我跑一次,非 CI)**:
  1. 从 `media_0.sqlite` 取几条真实语音 blob → `silk.to_wav`(pilk)→ `FasterWhisperRunner.transcribe`(首次下 whisper-small ~500MB)→ 确认**像样中文**。
  2. 跑整条 `voice_backfill`(voice_source→silk→asr→DerivedStore)→ 转录进 `derived.sqlite`,抽查几条。
  3. **盯 Whisper 已知失效**:对静音/非语音片段幻觉中文(如凭空「谢谢观看/请点赞」)。若频繁 → 升 `medium`(改一行)或加 no-speech 过滤(faster-whisper 的 `vad_filter=True` / segment `no_speech_prob` 门限)。是真验收标准。
  4. 转录像样才 `plugin enable wxmedia`。附带:wxsearch 的 text_source 已 join wxmedia derived 语音文本 → 之后 reindex 让语音消息也可语义搜索。

---

## 5. 快速变动 / 出货前须定
- **轻档型号**:先 whisper-small 验证;真机中文太弱则升 medium(~1.5GB,`_WHISPER["whisper-medium"]="medium"` + registry id)。VERIFY 会给真实质量证据。
- **no-speech 过滤**:faster-whisper `transcribe(..., vad_filter=True)` 或按 segment `no_speech_prob` 丢弃 —— 视 VERIFY 里幻觉是否频繁决定加不加(YAGNI,先不加,验后定)。
- **faster-whisper 读音频**:靠 `av`(PyAV)解 wav;faster-whisper 依赖含 av。我们已产 wav,直接传路径。
- **compute_type**:CPU 默认 int8(faster-whisper 支持),省内存/提速;mac arm64 实测 ctranslate2/av 有 wheel。

## 6. 暂不做 / 后续
- 图片 OCR(wxmedia-image,另一件,需 wxvault 明文图接口)。
- reranker、ASR 型号横评、说话人分离、时间戳。
- 把 derived 语音文本回灌 wxsearch/wxgraph 需手动 reindex(已有路径)。

## 7. 推进顺序
registry(asr 轻档 id + 零 URL + 同步改耦合测试)→ asr.py(FasterWhisperRunner + _WHISPER + 可注入缝 + retarget test_asr_runner + 一致性测试)→ server import + deps(pyproject+setup)→ VERIFY-AGAINST-REAL 真实语音验收。
