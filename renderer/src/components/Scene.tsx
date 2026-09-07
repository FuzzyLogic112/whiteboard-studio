import React from "react";
import { AbsoluteFill, Audio, staticFile, useCurrentFrame } from "remotion";
import { DrawnPath } from "./DrawnPath";
import { Keyword } from "./Keyword";
import { Subtitle } from "./Subtitle";
import type { Scene as SceneData, Theme } from "../types";

type Props = {
  scene: SceneData;
  theme: Theme;
};

/** 关键词出现的时机：简笔画画到七成时开始写字，画面不会一次塞满 */
const KEYWORD_START = 0.62;

export const Scene: React.FC<Props> = ({ scene, theme }) => {
  const frame = useCurrentFrame();
  const progress = Math.max(0, Math.min(1, frame / Math.max(1, scene.duration_frames)));

  // 当前正在画的那一笔才配一支马克笔，否则画面上会同时出现好几支
  const activeIndex = scene.strokes.findIndex(
    (s) => progress >= s.start && progress < s.start + s.span,
  );

  return (
    <AbsoluteFill>
      {scene.audio_file ? <Audio src={staticFile(scene.audio_file)} /> : null}

      <AbsoluteFill
        style={{
          alignItems: "center",
          justifyContent: "flex-start",
          paddingTop: 96,
          gap: 28,
        }}
      >
        <svg
          viewBox="0 0 100 100"
          width={430}
          height={430}
          style={{ overflow: "visible" }}
        >
          {scene.strokes.map((stroke, i) => (
            <DrawnPath
              key={`${scene.index}-${i}`}
              d={stroke.d}
              width={stroke.width}
              color={theme.ink}
              progress={(progress - stroke.start) / Math.max(0.0001, stroke.span)}
              showPen={i === activeIndex}
              penColor={theme.accent}
            />
          ))}
        </svg>

        <Keyword keyword={scene.keyword} theme={theme} progress={progress} start={KEYWORD_START} />
      </AbsoluteFill>

      <Subtitle text={scene.text} theme={theme} progress={progress} />
    </AbsoluteFill>
  );
};
