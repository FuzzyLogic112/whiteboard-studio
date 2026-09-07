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

## 分镜是可编辑的

自动挑的关键词不会每次都合适。与其反复调参数，不如直接改——预览之后，
每一镜的**关键词**和**简笔画**都能在界面上改，改完再渲染：

![分镜编辑](docs/storyboard.png)

改过的行会标出来，「还原」按钮退回自动结果。改了文稿之后分镜下标可能错位，
界面会挡住渲染并提示重新分镜（后端也会用 `script_digest` 二次校验，返回 409）。

## 只想看分镜，不想等渲染

改文稿的时候没必要每次都渲一遍：

```bash
curl -s -X POST localhost:8000/api/preview \
  -H 'Content-Type: application/json' \
  -d '{"text":"人工智能正在改变软件开发的方式。"}'
```

```json
{"scenes": [{"index": 0, "text": "人工智能正在改变软件开发的方式。",
             "keyword": "人工智能", "concept": "code",
             "auto_keyword": "人工智能", "auto_concept": "code"}],
 "script_digest": "bce7db1b8d2a28d3"}
```

`auto_*` 是自动结果，`keyword` / `concept` 是应用修正之后的值——两者分开存
才能显示「已改过」并支持还原。渲染时把修正原样发回：

```bash
curl -s -X POST localhost:8000/api/jobs -H 'Content-Type: application/json' -d '{
  "text": "...", "script_digest": "bce7db1b8d2a28d3",
  "overrides": [{"index": 0, "keyword": "大模型", "concept": "gear"}]
}'
```

前端的「预览分镜」按钮就是它，秒回。

---

## HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 服务状态、标注器/配图器/TTS 配置、渲染器是否就绪 |
| `GET` | `/api/concepts` | 可选的简笔画概念，带笔迹供前端画缩略图 |
| `POST` | `/api/preview` | 只做分镜和关键词，不渲染；返回 `script_digest` |
| `POST` | `/api/jobs` | 创建渲染任务，可带逐镜修正，立即返回任务 ID |
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
      segment.py         中文分词（最大概率分词 + 内置词典）
      keywords.py        分词结果 → 关键词
      sketch.py          内置简笔画（32 个概念 + 兜底涂鸦）与笔迹时间片分配
      vectorize.py       线稿位图 → SVG 中心线笔迹（细化 + RDP + 贝塞尔平滑）
      annotate/          分镜标注器：local（本地启发式）/ glm（智谱）
      illustrate/        配图器：builtin（内置）/ glm_image（智谱生图）
      data/              zh_words.txt.gz：分词词典
      timeline.py        装配成 RenderPlan
      tts/               语音合成 provider
renderer/                Remotion 项目，消费 RenderPlan
web/                     React 前端
```

---

## 换掉默认实现

三个位置是有意留出来的扩展点，签名不变就不用改下游：

**语音合成** —— 默认的 `silent` 只按字数估算时长（4.5 字/秒），不生成音频。
接 IndexTTS 有两条路：`indextts_local`（进程内调用上游 Python API）和
`indextts_http`（OpenAI 兼容的 `/v1/audio/speech`，模型跑在别的机器上）。
参考音频始终留在跑模型的那台机器上。详见 **[docs/tts.md](./docs/tts.md)**。

**配图** —— 两个配图器：`builtin` 用 32 个内置简笔画 + 哈希涂鸦兜底；
`glm_image` 调智谱生图，再用 `vectorize.py` 取中心线骨架转成可绘制的笔迹
（位图没法做「一笔一笔画出来」的动画，这一步是必需的）。
见 **[docs/illustrate.md](./docs/illustrate.md)**。

**渲染层** —— `render.py` 是唯一和 Remotion 耦合的文件。换 FFmpeg/Canvas
方案只需要另写一个同签名的 `render_video(plan, job_dir, settings, on_log) -> Path`。

**分镜标注（挑词 + 选图）** —— 两个标注器：`local` 用自实现的最大概率分词
（约 40 行 DP，词典裁剪自 jieba 的 dict.txt，MIT，6.4 万条）按「词性 × 字数 ×
文档频率」挑词，再靠触发词匹配选图，零依赖；`glm` 调智谱 GLM 一次标注全篇，
按语义选图、不依赖触发词命中。见 **[docs/annotate.md](./docs/annotate.md)**。

---

## 已知限制

- 中文关键词是**擦除动画**，不是真笔顺书写——真笔顺需要汉字笔画数据集。
- 内置简笔画只有 32 个概念，命不中就画兜底涂鸦。`glm` 标注器能明显减少涂鸦
  （按语义选图），`glm_image` 配图器则完全不受概念表限制——代价是每镜一张图、
  按张收费，且实心色块会被中心线法削成骨架线。
- 相邻镜头会尽量避免画同一张图，但当次优候选明显更差时会保留重复——
  画对但重复，好过画错。整段都在讲同一件事时，连着几镜同一张图是正常的。
- 默认出的片子没有声音：`silent` provider 只估节奏。接 IndexTTS 见 [docs/tts.md](./docs/tts.md)。
- 没有做 Gradio provider——Gradio 的 HTTP 接口在大版本间变过，版本耦合太重。
- `local` 标注器是启发式的（词性来自词典、没做上下文消歧），偶尔会挑到不理想的词；
  `glm` 更准但不是每次都赢（实测 local 的「三件事」就比 glm 的「聊清楚」好）。
  这也是分镜可编辑的原因：挑错了直接改，比继续调参数实在。

## 开发

```bash
cd backend  && pytest              # 123 个用例，覆盖分镜/分词/标注/矢量化/配图/接口/外部契约
cd renderer && npm run typecheck
cd web      && npm run build
```

## 许可证

MIT，见 [LICENSE](./LICENSE)。第三方依赖的授权见 [NOTICE](./NOTICE)。
