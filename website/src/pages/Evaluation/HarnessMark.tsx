import { useId } from "react";
import { harnessLogo, harnessLabel, type Row } from "./types";
import { useTranslation } from "react-i18next";

export default function HarnessMark({
  row,
  historical,
  className,
  size = 48,
  x,
  y,
}: {
  row: Row;
  historical: boolean;
  className?: string;
  size?: number;
  x?: number;
  y?: number;
}) {
  const { t } = useTranslation("evaluation");
  const ringId = useId();
  return (
    <svg
      className={className}
      data-mode={row.harness}
      x={x}
      y={y}
      width={size}
      height={size}
      viewBox="0 0 48 48"
      aria-label={`${t(harnessLabel(row.harness))} v${row.sdk_version}`}
    >
      <image href={harnessLogo(row.harness)} width={48} height={48} />
      {row.harness === "qwenpaw-goal" && (
        <circle
          cx={24}
          cy={24}
          r={22.5}
          fill="none"
          stroke="#2563eb"
          strokeWidth={3}
          vectorEffect="non-scaling-stroke"
        />
      )}
      {row.harness === "qwenpaw-code" && (
        <rect
          x={1.5}
          y={1.5}
          width={45}
          height={45}
          rx={6}
          fill="none"
          stroke="#111111"
          strokeWidth={3}
          vectorEffect="non-scaling-stroke"
        />
      )}

      {historical && (
        <g className="evaluation-version-ring">
          <circle
            cx={24}
            cy={24}
            r={21}
            fill="none"
            stroke="white"
            strokeWidth={6}
          />
          <defs>
            <path id={ringId} d="M 3 24 A 21 21 0 0 0 45 24" />
          </defs>
          <text fontSize={9} fontWeight={700} fill="#222222">
            <textPath href={`#${ringId}`} startOffset="50%" textAnchor="middle">
              v{row.sdk_version}
            </textPath>
          </text>
        </g>
      )}
    </svg>
  );
}
