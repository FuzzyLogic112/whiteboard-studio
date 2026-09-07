import React from "react";
import type { Concept } from "./api";

type Props = {
  concepts: Concept[];
  value: string;
  onChange: (id: string) => void;
};

/**
 * 简笔画选择器：下拉框 + 图形预览。
 *
 * 只列 id 的话没人知道 `funnel` 和 `stack` 长什么样，必须能看见图形——
 * 所以 /api/concepts 会把笔迹一起返回，这里直接画出来。
 */
export const ConceptPicker: React.FC<Props> = ({ concepts, value, onChange }) => {
  const current = concepts.find((c) => c.id === value);

  return (
    <div className="concept-picker">
      <svg viewBox="0 0 100 100" className="concept-thumb" aria-hidden="true">
        {(current?.paths ?? []).map((d, i) => (
          <path
            key={i}
            d={d}
            fill="none"
            stroke="currentColor"
            strokeWidth={4}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
      </svg>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {concepts.map((c) => (
          <option key={c.id} value={c.id}>{c.id}</option>
        ))}
      </select>
    </div>
  );
};
