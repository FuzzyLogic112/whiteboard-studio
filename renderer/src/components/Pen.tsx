import React from "react";

type Props = {
  x: number;
  y: number;
  color: string;
};

/**
 * 跟着笔迹走的马克笔。
 *
 * 坐标是 100x100 viewBox 里的，笔尖对准 (x, y)，笔身朝右上斜出去，
 * 和真人握笔的角度接近。
 */
export const Pen: React.FC<Props> = ({ x, y, color }) => (
  <g transform={`translate(${x} ${y}) rotate(-38)`} style={{ pointerEvents: "none" }}>
    {/* 笔尖 */}
    <path d="M 0 0 L -2.4 -5 L 2.4 -5 Z" fill={color} />
    {/* 笔杆 */}
    <rect x={-3.2} y={-24} width={6.4} height={19} rx={1.6} fill={color} opacity={0.92} />
    {/* 笔夹上的高光，纯装饰，但少了它笔杆像根黑棍 */}
    <rect x={-1.2} y={-22} width={1.4} height={13} rx={0.7} fill="#ffffff" opacity={0.35} />
  </g>
);
