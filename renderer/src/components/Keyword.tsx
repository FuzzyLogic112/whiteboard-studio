import React from "react";
import { interpolate } from "remotion";
import { CJK_STACK, type Theme } from "../types";

type Props = {
  keyword: string;
  theme: Theme;
  /** 镜头内进度 0~1 */
  progress: number;
  /** 关键词开始出现的进度 */
  start: number;
};

/**
 * 白板上「写」出来的关键词。
 *
 * 中文没法像英文那样按笔顺描出来（要真正的笔画数据），所以用一条从左到右
 * 的擦除动画代替：视觉上仍然是「一个字一个字写出来」的节奏，而且文字是
 * 真实文本节点，字幕组和 OCR 都读得到。
 */
export const Keyword: React.FC<Props> = ({ keyword, theme, progress, start }) => {
  const wipe = interpolate(progress, [start, start + 0.18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const underline = interpolate(progress, [start + 0.14, start + 0.3], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
      <div
        style={{
          fontFamily: CJK_STACK,
          fontSize: 104,
          fontWeight: 700,
          color: theme.ink,
          letterSpacing: 6,
          lineHeight: 1.1,
          whiteSpace: "nowrap",
          // 从左往右揭开，比整体淡入更像「写」的过程
          clipPath: `inset(0 ${(1 - wipe) * 100}% 0 0)`,
        }}
      >
        {keyword}
      </div>
      <div
        style={{
          height: 8,
          borderRadius: 4,
          backgroundColor: theme.accent,
          width: `${underline * 100}%`,
          alignSelf: "stretch",
          transformOrigin: "left center",
        }}
      />
    </div>
  );
};
