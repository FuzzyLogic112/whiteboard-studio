// 字段名与后端 pydantic 模型保持一致（snake_case），避免两边来回转换时出错。

export type Stroke = {
  d: string;
  width: number;
  /** 该笔迹在本镜头内开始绘制的相对进度 0~1 */
  start: number;
  /** 绘制过程占本镜头时长的比例 */
  span: number;
};

export type Scene = {
  index: number;
  text: string;
  keyword: string;
  concept: string;
  strokes: Stroke[];
  duration_seconds: number;
  duration_frames: number;
  audio_file: string | null;
};

export type RenderPlan = {
  job_id: string;
  width: number;
  height: number;
  fps: number;
  total_frames: number;
  template: string;
  scenes: Scene[];
};

export type Theme = {
  board: string;
  grid: string;
  ink: string;
  accent: string;
  subtitleBg: string;
  subtitleInk: string;
};

export const THEMES: Record<string, Theme> = {
  minimal: {
    board: "#fbfaf7",
    grid: "#e7e3da",
    ink: "#22201d",
    accent: "#e0562d",
    subtitleBg: "rgba(28,26,24,0.86)",
    subtitleInk: "#fdfcf9",
  },
  blueprint: {
    board: "#10243c",
    grid: "#1c3a5c",
    ink: "#e8f1fb",
    accent: "#4fd1c5",
    subtitleBg: "rgba(6,16,28,0.86)",
    subtitleInk: "#e8f1fb",
  },
  warm: {
    board: "#f6efe2",
    grid: "#e3d6bd",
    ink: "#3a2d20",
    accent: "#c2703a",
    subtitleBg: "rgba(58,45,32,0.88)",
    subtitleInk: "#f9f4ea",
  },
};

export const getTheme = (name: string): Theme => THEMES[name] ?? THEMES.minimal;

/** 中文字体栈：容器里通常只有文泉驿，桌面端才有苹方/微软雅黑 */
export const CJK_STACK =
  '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Zen Hei", sans-serif';
