# whiteboard-studio

输入一段中文文稿，自动完成**分镜 → 关键词 → 简笔画 → 配音 → 手绘笔迹动画 → 字幕 → MP4**。

全流程在本机跑完，不需要任何 API key 就能出片。

```
文稿  ──▶  分镜切分  ──▶  关键词提取  ──▶  简笔画笔迹
                              │                │
                              ▼                ▼
                          语音合成  ────▶  时间轴装配  ──▶  Remotion 渲染  ──▶  MP4
```

---

## 和 cs-board 的关系

产品形态参考了 [cs-board](https://github.com/ChenShuo2004/cs-board)（MIT）。**代码是独立实现**，
不是它的 fork 或副本。cs-board 的版权与许可证声明保留在 [NOTICE](./NOTICE) 中。

> ⚠️ **Remotion 不是标准开源协议**。个人、非营利组织和 3 人及以下的公司免费；
> 达到规模的公司商用需要购买 Company License，详见 <https://remotion.dev/license>。
> 想规避这一条，见下文「换掉渲染层」。

---

## 快速开始

需要 Node.js ≥ 22.13 和 Python ≥ 3.11。

```bash
# 1. 渲染层
cd renderer && npm install && cd ..

# 2. 后端
cd backend && pip install -e ".[dev]"
uvicorn app.main:app --port 8000 --reload

# 3. 前端（另开一个终端）
cd web && npm install && npm run dev
```

打开 <http://localhost:5173>，粘贴文稿，点「开始渲染」。

一段 17 秒的成片在单核容器里大约 90 秒渲完；渲染是 CPU 密集型，核多会快很多。

### 无头环境 / CI

容器里通常没有 GPU，也不该让 Remotion 每次去下 Chromium：

```bash
export WBS_BROWSER_EXECUTABLE=/path/to/chrome   # 复用已有的 Chromium/headless shell
export WBS_RENDER_CONCURRENCY=1                 # 内存紧张时设为 1
```

渲染器已经在 `remotion.config.ts` 里指定了 `swangle` 软件渲染管线，无 GPU 也不会黑屏。

---

## 只想看分镜，不想等渲染

改文稿的时候没必要每次都渲一遍：

```bash
curl -s -X POST localhost:8000/api/preview \
  -H 'Content-Type: application/json' \
  -d '{"text":"人工智能正在改变软件开发的方式。"}'
```

```json
{"scenes": [{"index": 0, "text": "人工智能正在改变软件开发的方式。",
             "keyword": "人工智能", "concept": "code"}]}
```

前端的「预览分镜」按钮就是它，秒回。

---

## HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 服务状态、TTS provider、渲染器是否就绪 |
| `POST` | `/api/preview` | 只做分镜和关键词，不渲染 |
| `POST` | `/api/jobs` | 创建渲染任务，立即返回任务 ID |
| `GET` | `/api/jobs` | 任务列表 |
| `GET` | `/api/jobs/{id}` | 任务状态与进度 |
| `GET` | `/api/jobs/{id}/plan` | 完整渲染计划（调试用） |
| `GET` | `/api/jobs/{id}/log` | Remotion 的渲染日志尾部 |
| `GET` | `/api/jobs/{id}/video` | 下载成片 |

任务产物都在 `.workspace/jobs/<id>/` 下（`plan.json`、`audio/`、`output.mp4`），
服务重启后历史任务和已渲好的成片仍然读得到。

---

## 目录结构

```
backend/
  app/
    main.py              FastAPI 路由
    jobs.py              任务队列、进度、断点落盘
    render.py            调用 Remotion 的唯一入口
    pipeline/
      script.py          文稿 → 分镜
      keywords.py        分镜 → 关键词
      sketch.py          关键词 → SVG 笔迹（内置 20 个简笔画 + 兜底涂鸦）
      timeline.py        装配成 RenderPlan
      tts/               语音合成 provider
renderer/                Remotion 项目，消费 RenderPlan
web/                     React 前端
```

---

## 换掉默认实现

三个位置是有意留出来的扩展点，签名不变就不用改下游：

**语音合成** —— 默认的 `silent` 只按字数估算时长（4.5 字/秒），不生成音频。
要接声音克隆，配 `WBS_TTS_PROVIDER=indextts` 指向本机的 IndexTTS 服务；
参考音频只在本机传递。写新 provider 就实现 `pipeline/tts/base.py` 里的
`TTSProvider`，在 `pipeline/tts/__init__.py` 注册。

**配图** —— `sketch.py` 里是一张 `关键词 → SVG path` 的表。要接 AI 生图，
在 `strokes_for` 里加分支，把生成的位图矢量化成 path 即可。

**渲染层** —— `render.py` 是唯一和 Remotion 耦合的文件。换 FFmpeg/Canvas
方案只需要另写一个同签名的 `render_video(plan, job_dir, settings, on_log) -> Path`。

**分词** —— `keywords.py` 没有依赖 jieba（体积大、装不上的概率高），
用的是「虚词切分 + 窗口打分」的启发式。要换成真分词或大模型抽取，
替换 `extract_keywords` 即可。

---

## 已知限制

- 中文关键词是**擦除动画**，不是真笔顺书写——真笔顺需要汉字笔画数据集。
- 简笔画目前是内置的 20 个概念 + 哈希涂鸦兜底，还不是 AI 生图。
- `silent` provider 出的片子没有声音，只有按字数估的节奏。
- 关键词提取是启发式的，长句偶尔会挑到不理想的词；先用 `/api/preview` 看一眼最省时间。

## 开发

```bash
cd backend  && pytest              # 25 个用例，覆盖分镜/关键词/笔迹时序/日志解析
cd renderer && npm run typecheck
cd web      && npm run build
```

## 许可证

MIT，见 [LICENSE](./LICENSE)。第三方依赖的授权见 [NOTICE](./NOTICE)。
