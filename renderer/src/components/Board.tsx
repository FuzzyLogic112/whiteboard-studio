import React from "react";
import { AbsoluteFill } from "remotion";
import type { Theme } from "../types";

/** 白板底：纯色 + 淡网格 + 四角压暗，避免大面积死白 */
export const Board: React.FC<{ theme: Theme }> = ({ theme }) => (
  <AbsoluteFill style={{ backgroundColor: theme.board }}>
    <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
      <defs>
        <pattern id="grid" width={64} height={64} patternUnits="userSpaceOnUse">
          <path d="M 64 0 L 0 0 0 64" fill="none" stroke={theme.grid} strokeWidth={1} />
        </pattern>
        <radialGradient id="vignette" cx="50%" cy="45%" r="72%">
          <stop offset="60%" stopColor="rgba(0,0,0,0)" />
          <stop offset="100%" stopColor="rgba(0,0,0,0.10)" />
        </radialGradient>
      </defs>
      <rect width="100%" height="100%" fill="url(#grid)" />
      <rect width="100%" height="100%" fill="url(#vignette)" />
    </svg>
  </AbsoluteFill>
);
