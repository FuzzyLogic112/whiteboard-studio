import React from "react";
import { Composition } from "remotion";
import { Whiteboard } from "./Whiteboard";
import { demoPlan } from "./demoPlan";
import type { RenderPlan } from "./types";

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Whiteboard"
    component={Whiteboard}
    defaultProps={demoPlan}
    // 分辨率、帧率和总时长全部由后端的渲染计划决定，这里只兜底
    calculateMetadata={({ props }: { props: RenderPlan }) => ({
      width: props.width,
      height: props.height,
      fps: props.fps,
      durationInFrames: Math.max(1, props.total_frames),
    })}
    width={demoPlan.width}
    height={demoPlan.height}
    fps={demoPlan.fps}
    durationInFrames={demoPlan.total_frames}
  />
);
