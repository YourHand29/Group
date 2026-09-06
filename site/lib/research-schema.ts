export type NodeKind = 'thesis' | 'method' | 'finding' | 'experiment' | 'metric' | 'concept';
export type ConceptRecognitionStatus = 'structural' | 'recognized' | 'classified' | 'source_supported';

export type MapNode = {
  id: string;
  kind: NodeKind;
  label: string;
  detail: string;
};

export type ConceptSupportStatus = 'direct' | 'contextual' | 'partial' | 'unsupported';

export type EvidenceSupport = {
  evidenceId: string;
  claim: string;
  excerpt: string;
  sourceLocation: string | null;
  confidence: number;
};

export type ReliabilityAssessment = {
  score: number;
  label: 'high' | 'moderate' | 'low';
  rationale: string;
  limitations: string[];
};

export type ConceptExplanation = {
  conceptId: string;
  term: string;
  kind: NodeKind;
  definition: string;
  useInPaper: string;
  supportingEvidence: EvidenceSupport[];
  supportStatus: ConceptSupportStatus;
  reliability: ReliabilityAssessment;
  simpleExplanation: string;
  paperContext: string;
  evidenceIds: string[];
  confidence: number;
  conceptType?: string | null;
  wikipediaUrl?: string | null;
  wikidataId?: string | null;
  sourceUrls?: string[];
  recognitionStatus?: ConceptRecognitionStatus;
};

export type PaperMap = {
  title: string;
  summary: string;
  relevance: number;
  nodes: MapNode[];
  explanations: ConceptExplanation[];
  sourceUrl?: string | null;
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
