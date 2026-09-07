import React, { useEffect, useRef, useState } from "react";
import { cancelRender, continueRender, delayRender } from "remotion";
import { Pen } from "./Pen";

type Point = { x: number; y: number };

type Props = {
  d: string;
  width: number;
  color: string;
  /** 0~1，这一笔画到哪儿了 */
  progress: number;
  /** 是否显示跟着笔迹走的马克笔 */
  showPen?: boolean;
  penColor?: string;
};

const SAMPLE_COUNT = 160;

/**
 * 一条「正在被画出来」的笔迹。
 *
 * 原理是 stroke-dasharray = 全长、stroke-dashoffset 从全长退到 0，
 * 视觉上就是线条从起点长出来。
 *
 * 笔尖坐标不逐帧调 getPointAtLength：渲染时每一帧都是独立的 React 提交，
 * 逐帧读 DOM 容易在首帧拿不到值而抖动。改成挂载时一次性采样 160 个点存下来，
 * 之后每帧只查表——结果稳定，且同一份计划重渲染的结果完全一致。
 */
export const DrawnPath: React.FC<Props> = ({
  d,
  width,
  color,
  progress,
  showPen = false,
  penColor,
}) => {
  const ref = useRef<SVGPathElement>(null);
  const [handle] = useState(() => delayRender(`测量笔迹 ${d.slice(0, 24)}`));
  const [geometry, setGeometry] = useState<{ length: number; points: Point[] } | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) {
      cancelRender(new Error("笔迹节点未挂载"));
      return;
    }
    try {
      const length = el.getTotalLength();
      const points: Point[] = [];
      for (let i = 0; i <= SAMPLE_COUNT; i++) {
        const p = el.getPointAtLength((length * i) / SAMPLE_COUNT);
        points.push({ x: p.x, y: p.y });
      }
      setGeometry({ length, points });
      continueRender(handle);
    } catch (err) {
      cancelRender(err as Error);
    }
    // d 变了要重新测量；handle 是一次性的，不进依赖
  }, [d, handle]);

  const clamped = Math.max(0, Math.min(1, progress));
  const length = geometry?.length ?? 0;
  const tip =
    showPen && geometry && clamped > 0 && clamped < 1
      ? geometry.points[Math.round(clamped * SAMPLE_COUNT)]
      : null;

  return (
    <>
      <path
        ref={ref}
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={width}
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeDasharray={length || undefined}
        strokeDashoffset={length ? length * (1 - clamped) : undefined}
        // 还没测出长度时先别画，否则第一帧会整条线闪一下
        opacity={geometry ? 1 : 0}
      />
      {tip ? <Pen x={tip.x} y={tip.y} color={penColor ?? color} /> : null}
    </>
  );
};
