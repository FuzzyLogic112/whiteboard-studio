import type { RenderPlan } from "./types";

/**
 * `remotion studio` 独立启动时用的样例，也是 Composition 的 defaultProps。
 * 真正出片时这份数据会被后端生成的 plan.json 整体替换。
 */
export const demoPlan: RenderPlan = {
  job_id: "demo",
  width: 1920,
  height: 1080,
  fps: 30,
  total_frames: 180,
  template: "minimal",
  scenes: [
    {
      index: 0,
      text: "白板动画的关键，是让观众看见思考的过程。",
      keyword: "白板动画",
      concept: "idea",
      duration_seconds: 3,
      duration_frames: 90,
      audio_file: null,
      strokes: [
        {
          d: "M 50 20 C 32 20 23 34 30 47 C 33 53 39 57 39 64 L 61 64 C 61 57 67 53 70 47 C 77 34 68 20 50 20 Z",
          width: 2.6,
          start: 0,
          span: 0.4,
        },
        { d: "M 42 71 L 58 71", width: 2.6, start: 0.4, span: 0.11 },
        { d: "M 45 79 L 55 79", width: 2.6, start: 0.51, span: 0.11 },
      ],
    },
    {
      index: 1,
      text: "一句话配一张图，节奏就出来了。",
      keyword: "节奏",
      concept: "time",
      duration_seconds: 3,
      duration_frames: 90,
      audio_file: null,
      strokes: [
        { d: "M 50 16 a 34 34 0 1 0 0.1 0", width: 2.6, start: 0, span: 0.4 },
        { d: "M 50 50 L 50 28", width: 2.6, start: 0.4, span: 0.11 },
        { d: "M 50 50 L 67 59", width: 2.6, start: 0.51, span: 0.11 },
      ],
    },
  ],
};
