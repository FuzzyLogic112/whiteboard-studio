import React, { useCallback, useEffect, useRef, useState } from "react";
import { ConceptPicker } from "./ConceptPicker";
import {
  api,
  STATUS_LABEL,
  type Concept,
  type Health,
  type JobView,
  type PreviewScene,
  type SceneOverride,
} from "./api";

const SAMPLE = `很多人以为写作是天赋。
其实写作是一门可以练习的手艺。
选题决定了上限，结构决定了下限，修改决定了成品。
今天我们把这三件事聊清楚。`;

const TEMPLATES = [
  { id: "minimal", name: "极简白板" },
  { id: "blueprint", name: "蓝图深色" },
  { id: "warm", name: "暖调纸感" },
];

const POLL_INTERVAL_MS = 1500;
const ACTIVE_STATUSES = ["pending", "splitting", "synthesizing", "sketching", "rendering"];

/** 把编辑过的分镜折算成要发给后端的修正列表 */
const toOverrides = (scenes: PreviewScene[]): SceneOverride[] =>
  scenes
    .filter((s) => s.keyword !== s.auto_keyword || s.concept !== s.auto_concept)
    .map((s) => ({ index: s.index, keyword: s.keyword, concept: s.concept }));

export const App: React.FC = () => {
  const [text, setText] = useState(SAMPLE);
  const [template, setTemplate] = useState("minimal");
  const [health, setHealth] = useState<Health | null>(null);
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [scenes, setScenes] = useState<PreviewScene[]>([]);
  const [digest, setDigest] = useState("");
  const [previewedText, setPreviewedText] = useState("");
  const [job, setJob] = useState<JobView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const timer = useRef<number | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api.concepts().then((r) => setConcepts(r.concepts)).catch(() => setConcepts([]));
  }, []);

  // 任务跑起来后轮询进度，结束就停
  useEffect(() => {
    if (!job || !ACTIVE_STATUSES.includes(job.status)) return;
    timer.current = window.setTimeout(() => {
      api.getJob(job.id).then(setJob).catch((e: Error) => setError(e.message));
    }, POLL_INTERVAL_MS);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [job]);

  const runPreview = useCallback(async () => {
    setError("");
    setBusy(true);
    try {
      // 带上已有的修正，重新预览不会把改过的东西冲掉
      const result = await api.preview(text, toOverrides(scenes));
      setScenes(result.scenes);
      setDigest(result.script_digest);
      setPreviewedText(text);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [text, scenes]);

  const runRender = useCallback(async () => {
    setError("");
    setBusy(true);
    try {
      const overrides = toOverrides(scenes);
      // 没预览过就不传指纹，让后端按自动结果跑
      setJob(await api.createJob(text, template, overrides, digest || undefined));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [text, template, scenes, digest]);

  const patchScene = (index: number, patch: Partial<PreviewScene>) =>
    setScenes((prev) => prev.map((s) => (s.index === index ? { ...s, ...patch } : s)));

  const resetScene = (index: number) =>
    setScenes((prev) =>
      prev.map((s) =>
        s.index === index ? { ...s, keyword: s.auto_keyword, concept: s.auto_concept } : s,
      ),
    );

  const running = job !== null && ACTIVE_STATUSES.includes(job.status);
  // 预览之后又改了文稿：分镜下标可能已经错位，修正不能再用
  const stale = scenes.length > 0 && text !== previewedText;
  const editedCount = toOverrides(scenes).length;

  return (
    <div className="page">
      <header>
        <h1>whiteboard-studio</h1>
        <p className="sub">
          输入中文文稿，自动分镜、配图、手绘笔迹、字幕，导出白板动画 MP4
        </p>
        {health ? (
          <>
            <p className="health">
              标注：{health.annotator} · 语音：{health.tts_provider} ·{" "}
              {health.resolution}@{health.fps}fps ·
              渲染器：{health.renderer_ready ? "就绪" : "未安装依赖"}
            </p>
            {health.tts_error ? (
              <p className="health warn">语音服务不可用：{health.tts_error}</p>
            ) : null}
          </>
        ) : (
          <p className="health warn">后端未连接，请先启动 uvicorn</p>
        )}
      </header>

      <section className="editor">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={10}
          placeholder="把你的口播稿粘进来……"
        />
        <div className="controls">
          <label>
            模板
            <select value={template} onChange={(e) => setTemplate(e.target.value)}>
              {TEMPLATES.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </label>
          <button onClick={runPreview} disabled={busy || !text.trim()}>
            {scenes.length > 0 ? "重新分镜" : "预览分镜"}
          </button>
          <button
            className="primary"
            onClick={runRender}
            disabled={busy || running || stale || !text.trim()}
          >
            {running ? "渲染中…" : "开始渲染"}
          </button>
        </div>
        {stale ? (
          <p className="notice">文稿改过了，分镜可能已经错位。请重新分镜后再渲染。</p>
        ) : null}
        {error ? <p className="error">{error}</p> : null}
      </section>

      {scenes.length > 0 ? (
        <section className="scenes">
          <h2>
            分镜（{scenes.length}）
            {editedCount > 0 ? <span className="badge">已改 {editedCount} 处</span> : null}
          </h2>
          <p className="hint">
            关键词和简笔画都能直接改。自动挑的词不一定合适，改一下比重渲一遍快。
          </p>
          <ol className="storyboard">
            {scenes.map((scene) => {
              const edited =
                scene.keyword !== scene.auto_keyword || scene.concept !== scene.auto_concept;
              return (
                <li key={scene.index} className={edited ? "edited" : ""}>
                  <span className="idx">{scene.index + 1}</span>
                  <input
                    className="kw"
                    value={scene.keyword}
                    maxLength={8}
                    onChange={(e) => patchScene(scene.index, { keyword: e.target.value })}
                  />
                  <ConceptPicker
                    concepts={concepts}
                    value={scene.concept}
                    onChange={(concept) => patchScene(scene.index, { concept })}
                  />
                  <span className="text">{scene.text}</span>
                  <button
                    className="reset"
                    onClick={() => resetScene(scene.index)}
                    disabled={!edited}
                    title="还原为自动结果"
                  >
                    还原
                  </button>
                </li>
              );
            })}
          </ol>
        </section>
      ) : null}

      {job ? (
        <section className="job">
          <h2>任务 {job.id}</h2>
          <div className="bar">
            <div
              className={`fill ${job.status === "failed" ? "failed" : ""}`}
              style={{ width: `${Math.round(job.progress * 100)}%` }}
            />
          </div>
          <p className="status">
            {STATUS_LABEL[job.status]} · {job.message}
            {job.scene_count > 0 ? ` · ${job.scene_count} 镜 / ${job.duration_seconds}s` : ""}
          </p>
          {job.error ? <pre className="error">{job.error}</pre> : null}
          {job.has_video ? <video controls src={api.videoUrl(job.id)} /> : null}
        </section>
      ) : null}
    </div>
  );
};
