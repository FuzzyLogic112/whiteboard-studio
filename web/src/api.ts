export type JobStatus =
  | "pending" | "splitting" | "synthesizing" | "sketching" | "rendering" | "done" | "failed";

export type JobView = {
  id: string;
  status: JobStatus;
  progress: number;
  message: string;
  created_at: number;
  updated_at: number;
  error: string | null;
  scene_count: number;
  duration_seconds: number;
  has_video: boolean;
};

export type PreviewScene = {
  index: number;
  text: string;
  keyword: string;
  concept: string;
};

export type Health = {
  ok: boolean;
  tts_provider: string;
  tts_providers: string[];
  tts_ready: boolean;
  tts_error: string | null;
  fps: number;
  resolution: string;
  renderer_ready: boolean;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail ?? `请求失败 (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/api/health"),
  preview: (text: string) =>
    request<{ scenes: PreviewScene[] }>("/api/preview", {
      method: "POST",
      body: JSON.stringify({ text, template: "minimal" }),
    }),
  createJob: (text: string, template: string) =>
    request<JobView>("/api/jobs", {
      method: "POST",
      body: JSON.stringify({ text, template }),
    }),
  getJob: (id: string) => request<JobView>(`/api/jobs/${id}`),
  listJobs: () => request<JobView[]>("/api/jobs"),
  videoUrl: (id: string) => `/api/jobs/${id}/video`,
};

export const STATUS_LABEL: Record<JobStatus, string> = {
  pending: "排队中",
  splitting: "切分文稿",
  synthesizing: "合成语音",
  sketching: "生成笔迹",
  rendering: "渲染视频",
  done: "已完成",
  failed: "失败",
};
