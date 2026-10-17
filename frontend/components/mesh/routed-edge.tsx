"use client";

import { memo, useSyncExternalStore } from "react";
import { BaseEdge, getBezierPath, type EdgeProps } from "@xyflow/react";

import { useMeshHighlight } from "@/components/mesh/highlight";
import { labelPoint, roundedPath, type Point, type RelationshipGroup } from "@/lib/mesh";

// Quiet by default; the path lights up when it matters.
export const EDGE_STYLE: Record<RelationshipGroup, { stroke: string; width: number; dash?: string }> = {
  flow: { stroke: "#AEB3BD", width: 1.5 },
  storage: { stroke: "#AEB3BD", width: 1.3, dash: "5 4" },
  depends_on: { stroke: "#B9B4E6", width: 1.3, dash: "4 4" },
  containment: { stroke: "transparent", width: 0 },
  pipeline: { stroke: "transparent", width: 0 },
};
const PATH_COLOR = "#5148E0";
const DIM_COLOR = "#EBEDF0";

/** Data travelling along the lit path, as in the film; off for reduced motion. */
const REDUCE = "(prefers-reduced-motion: reduce)";
const subscribe = (cb: () => void) => {
  const m = window.matchMedia?.(REDUCE);
  m?.addEventListener("change", cb);
  return () => m?.removeEventListener("change", cb);
};
const useReducedMotion = () =>
  useSyncExternalStore(subscribe, () => window.matchMedia?.(REDUCE).matches ?? false, () => false);

export interface RoutedEdgeData {
  points?: Point[];
  group: RelationshipGroup;
  /** How many relationships this edge stands for (rolled up from closed bundles). */
  count: number;
}

/** A small filled arrowhead at the route's end, pointing along its last segment. */
function arrowhead(points: Point[], size = 5.5): string {
  const end = points[points.length - 1];
  const prev = points[points.length - 2];
  const len = Math.hypot(end.x - prev.x, end.y - prev.y) || 1;
  const ux = (end.x - prev.x) / len;
  const uy = (end.y - prev.y) / len;
  const bx = end.x - ux * size * 1.6;
  const by = end.y - uy * size * 1.6;
  return `M ${end.x} ${end.y} L ${bx - uy * size} ${by + ux * size} L ${bx + uy * size} ${by - ux * size} Z`;
}

/**
 * Draws the route ELK computed — through the gaps between layers, never across
 * a card — as an orthogonal line with rounded corners. Styles itself from the
 * highlight context, so hovering never rebuilds React Flow's edges.
 */
function RoutedEdgeImpl(props: EdgeProps) {
  const d = props.data as unknown as RoutedEdgeData;
  const h = useMeshHighlight();
  const reduce = useReducedMotion();
  const style = EDGE_STYLE[d.group];
  const onPath = h.pathEdges.has(props.id);
  const active = h.focusId !== null;
  const stroke = onPath ? PATH_COLOR : active ? DIM_COLOR : style.stroke;

  const pts =
    d.points && d.points.length >= 2
      ? d.points
      : [
          { x: props.sourceX, y: props.sourceY },
          { x: props.targetX, y: props.targetY },
        ];
  const routed = Boolean(d.points && d.points.length >= 2);
  const path = routed ? roundedPath(pts) : getBezierPath(props)[0];
  const label = routed ? labelPoint(pts) : { x: (props.sourceX + props.targetX) / 2, y: (props.sourceY + props.targetY) / 2 };

  return (
    <>
      <BaseEdge
        id={props.id}
        path={path}
        style={{ stroke, strokeWidth: onPath ? style.width + 0.6 : style.width, strokeDasharray: style.dash }}
        interactionWidth={12}
        label={d.count > 1 ? String(d.count) : undefined}
        labelX={label.x}
        labelY={label.y}
        labelStyle={{ fontSize: 10, fill: onPath ? PATH_COLOR : "#737780", fontWeight: 600, fontFamily: "var(--font-code)" }}
        labelShowBg
        labelBgStyle={{ fill: onPath ? "#EEF0FD" : "#ffffff", stroke: onPath ? "#CFCCF7" : "#E4E6EA" }}
        labelBgPadding={[5, 2]}
        labelBgBorderRadius={8}
      />
      <path d={arrowhead(pts)} fill={stroke} />
      {onPath && !reduce && d.group !== "containment" && d.group !== "pipeline" &&
        [0, 1].map((k) => (
          <circle key={k} r={3.5} fill={PATH_COLOR}>
            <animateMotion dur="1.8s" begin={`${k * 0.9}s`} repeatCount="indefinite" path={path} keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines="0.65 0 0.35 1" />
            <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.15;0.85;1" dur="1.8s" begin={`${k * 0.9}s`} repeatCount="indefinite" />
          </circle>
        ))}
    </>
  );
}

export const RoutedEdge = memo(RoutedEdgeImpl);
export const meshEdgeTypes = { routed: RoutedEdge };
