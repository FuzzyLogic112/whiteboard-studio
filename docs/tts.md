# 接入 IndexTTS

默认的 `silent` provider 不生成音频，只按 4.5 字/秒估算时长。要让成片有声音，
有两条路。

## 先说一件容易踩的事

**上游的 [index-tts](https://github.com/index-tts/index-tts) 仓库不提供 HTTP API。**
它只有三种用法：Gradio webui（`webui.py`，7860 端口）、Python API（`IndexTTS2` 类）、
以及 vLLM recipe。网上流传的 `POST /tts` 之类的接口都来自第三方封装。

所以这里提供的两个 provider 分别对应：

| provider | 对接的东西 | 什么时候用 |
| --- | --- | --- |
| `indextts_local` | 上游的 Python API，进程内直接调用 | 模型和渲染在同一台机器上 |
| `indextts_http` | OpenAI 兼容的 `/v1/audio/speech` | 模型跑在另一台机器 / 另一个容器 |

没有做 Gradio provider：Gradio 的 HTTP 接口在 4.x / 5.x 之间变过（`/run/predict`
→ `/gradio_api/call/<fn>` + SSE 取结果），版本耦合重，而且它本来就是给界面用的。
要走 Gradio，建议在它前面套一层 FastAPI，然后用 `indextts_http`。

---

## 方案一：`indextts_local`（进程内）

上游官方用法，没有 HTTP 那一层，延迟最低。

```bash
# 1. 按上游说明装好 index-tts 及其 PyTorch 依赖
# 2. 下载模型（0.8B）
hf download IndexTeam/IndexTTS-2.5 --local-dir=checkpoints
```

```bash
export WBS_TTS_PROVIDER=indextts_local
export WBS_INDEXTTS_CHECKPOINTS=/abs/path/to/checkpoints
export WBS_INDEXTTS_REFERENCE=/abs/path/to/reference.wav   # 5~10 秒干净人声
```

参考音频只在本机读取，不上传任何地方。

模型实例是**懒加载 + 全流程复用**的：首次合成会花几十秒加载，之后每句复用。
（每句话重新加载一次 0.8B 模型会让渲染时间彻底失控。）

`infer()` 的签名在 v2 / v2.5 之间有出入，`lang`、`duration_factor` 这些可选参数
会先用 `inspect.signature` 过滤掉当前版本不认识的再传，所以换版本一般不用改代码。

## 方案二：`indextts_http`（远程）

对接实现了 OpenAI 兼容语音接口的封装，比如
[csllpr/index-tts-fastapi](https://github.com/csllpr/index-tts-fastapi)：

```
POST {endpoint}/v1/audio/speech
Authorization: Bearer <token>
{"model":"IndexTTS","input":"要合成的文本","voice":"narrator",
 "response_format":"wav","speed":1.0}
-> audio/wav 二进制
```

```bash
export WBS_TTS_PROVIDER=indextts_http
export WBS_TTS_ENDPOINT=http://192.168.1.10:8100
export WBS_TTS_VOICE=narrator      # 服务端 characters/narrator.wav
export WBS_TTS_API_KEY=your_token  # 服务端没开鉴权就留空
```

选 OpenAI 兼容契约而不是自定义一套，是因为它是事实标准——任何实现了这个接口的
TTS 服务都能直接接上，不止 IndexTTS。

**固定要 wav**：时长是整条流水线的时间基准，必须精确读出来；mp3 得解码才知道时长。

---

## 失败时会怎样

**默认：整个任务失败，并把原因写进任务状态。**

这是有意的。配错地址或音色名的情况远比「模型偶发抽风」常见，而悄悄出一条没声音
的片子是最难排查的失败形态——用户往往要等渲染跑完、点开播放才发现不对。

不想让长任务被单句失败中断：

```bash
export WBS_TTS_FALLBACK_SILENT=1   # 失败的那一镜退回估算时长，继续跑
```

`/api/health` 会预先验一遍配置，前端顶部直接显示错误，不用等渲染跑完：

```json
{"tts_provider": "indextts_http", "tts_ready": false,
 "tts_error": "indextts_http 需要配置 WBS_TTS_VOICE（服务端 characters/ 下的音色名）"}
```

## 时长怎么影响画面

`TTSProvider.synthesize` 返回的时长是整条流水线的时间基准：分镜多长、笔迹画多快、
字幕停多久，全部由它推导。

所以接上真实语音之后，画面节奏会自动跟着语速走，不需要再调任何参数。反过来，
这也意味着**时长必须来自音频本身**，不能退回字数估算——否则字幕和声音会越走越偏。

## 自己写 provider

实现 `pipeline/tts/base.py` 里的 `TTSProvider`（一个 `synthesize(text, out_path)`
方法，返回 `TTSResult(duration, audio_path)`），然后在 `pipeline/tts/__init__.py`
的 `build_provider` 里加一个分支。失败请抛 `TTSError`。

## 怎么测（不用真的跑模型）

`backend/tests/test_tts.py` 起了一个实现同一套契约的 mock HTTP 服务，覆盖成功、
401、空响应、非 wav、连不上、配置缺失、fallback 等情况。契约写错了会被这些用例挡住，
不需要把 0.8B 模型跑起来。
