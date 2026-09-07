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

### 环境准备

上游要求 **Python 3.10 / 3.11**（`>=3.10,<3.12`），依赖 `torch 2.8.*`，
并且**必须用 [uv](https://docs.astral.sh/uv/) 装**——它的锁文件里钉了 torch
和一堆编译扩展的具体版本，用 pip 装大概率对不上。

```bash
# 1. 拉仓库
git clone https://github.com/index-tts/index-tts.git && cd index-tts

# 2. 装依赖（uv 会自己建 .venv 并装好对应版本的 Python）
pip install -U uv
uv sync --all-extras
#   国内网络慢就换源：
#   uv sync --all-extras --default-index "https://mirrors.aliyun.com/pypi/simple"

# 3. 下模型（0.8B）
uv tool install "huggingface-hub"
hf download IndexTeam/IndexTTS-2.5 --local-dir=checkpoints
#   或者用 modelscope：
#   uv tool install "modelscope"
#   modelscope download --model IndexTeam/IndexTTS-2.5 --local_dir checkpoints
#   HuggingFace 慢就设镜像：export HF_ENDPOINT="https://hf-mirror.com"

# 4. 确认能用上 GPU
uv run tools/gpu_check.py
```

Windows 上如果装依赖时报 CUDA 错误，需要 CUDA Toolkit **12.8 或更新**。

先用官方 WebUI 验一遍模型本身没问题，再接进来：

```bash
uv run webui.py          # 打开 http://127.0.0.1:7860
```

### 接进 whiteboard-studio

**关键点：本项目的后端要跑在 index-tts 的那个虚拟环境里**，因为它是在进程内
`import indextts`。两条路——把本项目的依赖装进 index-tts 的 `.venv`，或者反过来
把 `indextts` 装进本项目的环境（后者容易和 torch 版本打架，不推荐）。

```bash
export WBS_TTS_PROVIDER=indextts_local
export WBS_INDEXTTS_CHECKPOINTS=/abs/path/to/index-tts/checkpoints
export WBS_INDEXTTS_REFERENCE=/abs/path/to/reference.wav   # 5~10 秒干净人声
export WBS_INDEXTTS_LANG=ZH        # ZH / EN / ZHEN / JA / ES
```

参考音频只在本机读取，不上传任何地方。

**嫌麻烦就用方案二**：把 index-tts 单独跑成一个服务，本项目通过 HTTP 调它。
环境彻底隔离，也不用担心 torch 版本冲突。

### 版本差异（这里踩过坑）

三个版本的 `infer()` 签名不一样，参数名错一个就是 `TypeError`：

| 模块 | 类 | 参考音频参数 | `lang` |
| --- | --- | --- | --- |
| `indextts.infer_v2_5` | `IndexTTS2` | `spk_audio_prompt` | **必填位置参数** |
| `indextts.infer_v2` | `IndexTTS2` | `spk_audio_prompt` | 没有这个参数 |
| `indextts.infer` | `IndexTTS` | **`audio_prompt`** | 没有这个参数 |

代码会按签名自动适配：参考音频的参数名在 `spk_audio_prompt` / `audio_prompt`
里挑签名认识的那个；`lang` 只要签名里有就一定传（v2.5 里它没有默认值，不传
直接报错）；`duration_factor` 这类可选参数用 `inspect.signature` 过滤掉当前
版本不认识的。所以换版本一般不用改代码。

这三种签名都钉了测试（`tests/test_indextts_local.py`），桩类的签名逐字抄自上游
源码，不需要下模型就能验。

### 模型加载

模型实例是**懒加载 + 全流程复用**的：首次合成会花几十秒加载，之后每句复用。
（每句话重新加载一次 0.8B 模型会让渲染时间彻底失控。）

## 方案二：`indextts_http`（跑成服务）

**推荐这条。** 模型和本项目各在各的虚拟环境里，不用担心 torch 版本冲突，
模型也能放到另一台有显卡的机器上。

上游不提供 HTTP API，所以仓库里带了一个参考实现：
**[`tools/indextts_server.py`](../tools/indextts_server.py)**。

### 起服务

按[环境准备](#环境准备)把 index-tts 装好、模型下好之后：

```bash
cd /path/to/index-tts

# 1. 服务端额外需要这两个包（装进 index-tts 自己的环境）
uv pip install fastapi uvicorn

# 2. 建参考音频目录。文件名就是音色名，5~10 秒干净人声
mkdir -p characters
cp /path/to/my_voice.wav characters/narrator.wav

# 3. 起服务
uv run python /path/to/whiteboard-studio/tools/indextts_server.py \
    --checkpoints ./checkpoints \
    --voices ./characters \
    --port 8100
```

首次请求会加载模型（几十秒），之后常驻复用。

确认起来了：

```bash
curl -s localhost:8100/health
# {"ok":true,"voices":["narrator"],"voices_dir":"characters"}
```

服务端参数也都能用环境变量给：`WBS_SERVER_CHECKPOINTS`、`WBS_SERVER_VOICES`、
`WBS_SERVER_PORT`、`WBS_SERVER_LANG`、`WBS_SERVER_TOKEN`。

**加鉴权**（服务要暴露到局域网时建议设上）：

```bash
export WBS_SERVER_TOKEN=随便一串足够长的字符串
```

不设就不校验，本机自己用最省事。

### 接进 whiteboard-studio

```bash
export WBS_TTS_PROVIDER=indextts_http
export WBS_TTS_ENDPOINT=http://127.0.0.1:8100   # 换机器就写那台的地址
export WBS_TTS_VOICE=narrator                   # characters/narrator.wav
export WBS_TTS_API_KEY=和上面的 TOKEN 一致        # 服务端没设就留空
```

`/api/health` 会预先验一遍配置，前端顶部直接显示，不用等渲染跑完。

### 接口约定

```
POST {endpoint}/v1/audio/speech
Authorization: Bearer <token>
{"model":"IndexTTS","input":"要合成的文本","voice":"narrator",
 "response_format":"wav","speed":1.0}
-> audio/wav 二进制
```

用 OpenAI 兼容的契约而不是自定义一套，是因为它是事实标准——社区的 IndexTTS
FastAPI 封装（比如 csllpr/index-tts-fastapi）和别的 TTS 服务也实现了它，
想换掉自带的这个服务端直接换就行。

**固定要 wav**：时长是整条流水线的时间基准，必须精确读出来；mp3 得解码才知道
时长。服务端收到别的 `response_format` 会直接返回 400，不做转码——转码会悄悄
引入误差。

### 服务端也做了版本适配

和 `indextts_local` 一样，按 `infer()` 的签名挑参考音频的参数名、决定要不要传
`lang` 和 `duration_factor`，所以 v1 / v2 / v2.5 都能起。

它**故意不 import 本项目的任何代码**——两边在不同虚拟环境里，共享代码只会把
torch 拖进来。代价是这段适配逻辑有一份重复，改的时候两边都要看。

客户端和服务端的契约钉了测试（`tests/test_indextts_server.py`）：用真实的
`IndexTTSHttpProvider` 打真实起在本地的服务，只把模型换成桩。这套接口是本项目
自己定的，两边各写各的最容易悄悄走偏。

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
