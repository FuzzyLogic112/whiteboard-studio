import React from "react";
import { interpolate } from "remotion";
import { CJK_STACK, type Theme } from "../types";

type Props = {
  text: string;
  theme: Theme;
  /** 镜头内进度 0~1 */
  progress: number;
};

export const Subtitle: React.FC<Props> = ({ text, theme, progress }) => {
  // 头尾各留一小段淡入淡出，切镜时不会硬切
  const opacity = interpolate(progress, [0, 0.06, 0.94, 1], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const lift = interpolate(progress, [0, 0.08], [14, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 76,
        display: "flex",
        justifyContent: "center",
        opacity,
        transform: `translateY(${lift}px)`,
      }}
    >
      <div
        style={{
          maxWidth: "78%",
          padding: "18px 34px",
          borderRadius: 14,
          backgroundColor: theme.subtitleBg,
          color: theme.subtitleInk,
          fontFamily: CJK_STACK,
          fontSize: 42,
          lineHeight: 1.45,
          letterSpacing: 1,
          textAlign: "center",
        }}
      >
        {text}
      </div>
    </div>
  );
};
