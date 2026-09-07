import React from "react";
import { AbsoluteFill, Sequence, useCurrentFrame } from "remotion";
import { Board } from "./components/Board";
import { Scene } from "./components/Scene";
import { getTheme, type RenderPlan } from "./types";

export const Whiteboard: React.FC<RenderPlan> = (plan) => {
  const theme = getTheme(plan.template);
  const frame = useCurrentFrame();

  let offset = 0;
  const sequences = plan.scenes.map((scene) => {
    const from = offset;
    offset += scene.duration_frames;
    return (
      <Sequence key={scene.index} from={from} durationInFrames={scene.duration_frames}>
        <Scene scene={scene} theme={theme} />
      </Sequence>
    );
  });

  const overall = plan.total_frames > 0 ? frame / plan.total_frames : 0;

  return (
    <AbsoluteFill>
      <Board theme={theme} />
      {sequences}
      {/* 顶部细进度条：观众能一眼看出还剩多少 */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          height: 6,
          width: `${overall * 100}%`,
          backgroundColor: theme.accent,
          opacity: 0.85,
        }}
      />
    </AbsoluteFill>
  );
};
