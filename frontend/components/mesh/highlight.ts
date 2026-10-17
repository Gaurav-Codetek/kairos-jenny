"use client";

import { createContext, useContext } from "react";

/**
 * Hover and selection highlighting, read by each card and edge directly.
 *
 * Highlighting must never rebuild React Flow's nodes or edges: new node
 * objects lose their measured size, React Flow re-measures every card and
 * hides the edges meanwhile — a visible stutter on every hover. Cards and
 * edges subscribe to this instead and restyle themselves.
 */
export interface MeshHighlight {
  selected: string | null;
  /** The hovered or selected bundle whose path is lit. */
  focusId: string | null;
  pathNodes: Set<string>;
  pathEdges: Set<string>;
}

const EMPTY: MeshHighlight = { selected: null, focusId: null, pathNodes: new Set(), pathEdges: new Set() };

export const MeshHighlightContext = createContext<MeshHighlight>(EMPTY);

export const useMeshHighlight = () => useContext(MeshHighlightContext);
