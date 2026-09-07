import React, { useCallback, useEffect, useRef, useState } from "react";
import { api, STATUS_LABEL, type Health, type JobView, type PreviewScene } from "./api";

const SAMPLE = `很多人以为写作是天赋。
其实写作是一门可以练习的手艺，只要方法对，谁都能进步。
今天我们聊三件事：如何选题，如何搭结构，以及如何修改。`;

const TEMPLATES = [
  { id: "minimal", name: "极简白板" },
  { id: "blueprint", name: "蓝图深色" },
  { id: "warm", name: "暖调纸感" },
];

const POLL_INTERVAL_MS = 1500;
const ACTIVE_STATUSES = ["pending", "splitting", "synthesizing", "sketching", "rendering"];

export const App: React.FC = () => {
  const [text, setText] = useState(SAMPLE);
  const [template, setTemplate] = useState("minimal");
  const [health, setHealth] = useState<Health | null>(null);
  const [scenes, setScenes] = useState<PreviewScene[]>([]);
  const [job, setJob] = useState<JobView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const timer = useRef<number | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
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
      const result = await api.preview(text);
      setScenes(result.scenes);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [text]);

  const runRender = useCallback(async () => {
    setError("");
    setBusy(true);
    try {
      setJob(await api.createJob(text, template));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [text, template]);

  const running = job !== null && ACTIVE_STATUSES.includes(job.status);

  return (
    <div className="page">
      <header>
        <h1>whiteboard-studio</h1>
        <p className="sub">
          输入中文文稿，自动分镜、配图、手绘笔迹、字幕，导出白板动画 MP4
        </p>
        {health ? (
          <p className="health">
            语音：{health.tts_provider} · {health.resolution}@{health.fps}fps ·
            渲染器：{health.renderer_ready ? "就绪" : "未安装依赖"}
          </p>
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
            预览分镜
          </button>
          <button className="primary" onClick={runRender} disabled={busy || running || !text.trim()}>
            {running ? "渲染中…" : "开始渲染"}
          </button>
        </div>
        {error ? <p className="error">{error}</p> : null}
      </section>

      {scenes.length > 0 ? (
        <section className="scenes">
          <h2>分镜（{scenes.length}）</h2>
          <p className="hint">改文稿后重新预览很快，不必等一次完整渲染。</p>
          <ol>
            {scenes.map((s) => (
              <li key={s.index}>
                <span className="keyword">{s.keyword}</span>
                <span className="concept">{s.concept}</span>
                <span className="text">{s.text}</span>
              </li>
            ))}
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
          {job.has_video ? (
            <video controls src={api.videoUrl(job.id)} />
          ) : null}
        </section>
      ) : null}
    </div>
  );
};
