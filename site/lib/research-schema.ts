export type NodeKind = 'thesis' | 'method' | 'finding' | 'experiment' | 'metric';

export type MapNode = {
  id: string;
  kind: NodeKind;
  label: string;
  detail: string;
};

export type PaperMap = {
  title: string;
  summary: string;
  relevance: number;
  nodes: MapNode[];
};

export type PaperSummary = {
  id: string;
  code: string;
  title: string;
  authors: string;
  year: string;
  relevance: number;
  status: string;
};

export type PaperInput = {
  source: string;
  fileName?: string;
};
