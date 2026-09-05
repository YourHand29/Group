import type { PaperInput, PaperMap, PaperSummary } from './research-schema';

export const demoMap: PaperMap = {
  title: 'Transformers make context computable.',
  summary: 'A new architecture replaces recurrence with attention, making long-range relationships easier to learn in parallel.',
  relevance: 92,
  nodes: [
    { id: 'thesis', kind: 'thesis', label: 'Attention is all you need', detail: 'Replace recurrence with weighted context' },
    { id: 'method', kind: 'method', label: 'Self-attention', detail: 'Compare every token in one pass' },
    { id: 'finding', kind: 'finding', label: 'Parallel training', detail: 'Faster learning on long sequences' },
    { id: 'experiment', kind: 'experiment', label: 'WMT 2014', detail: 'Translation benchmark comparison' },
    { id: 'metric', kind: 'metric', label: '+2 BLEU', detail: 'Quality lift over prior systems' },
  ],
  explanations: [
    {
      conceptId: 'thesis',
      term: 'Attention is all you need',
      kind: 'thesis',
      definition: 'Replace recurrence with weighted context.',
      useInPaper: 'The paper uses this as its central claim or proposed answer.',
      supportingEvidence: [{ evidenceId: 'evidence-1', claim: 'The paper establishes a central research question.', excerpt: 'Attention replaces recurrence with a mechanism that can connect tokens directly.', sourceLocation: 'Introduction, page 1', confidence: 0.82 }],
      supportStatus: 'contextual',
      reliability: { score: 0.82, label: 'high', rationale: 'The explanation has contextual support from 1 linked evidence item with a limiting confidence of 82%.', limitations: ['This assesses evidence support, not whether the paper’s claim is universally true.'] },
      simpleExplanation: 'The paper’s main idea is that attention can replace recurrence for modeling context.',
      paperContext: 'The paper establishes a central research question.',
      evidenceIds: ['evidence-1'],
      confidence: 0.82,
    },
    {
      conceptId: 'method',
      term: 'Self-attention',
      kind: 'method',
      definition: 'Compare every token with the others in one pass.',
      useInPaper: 'The paper uses this as its approach for addressing the research problem.',
      supportingEvidence: [{ evidenceId: 'evidence-2', claim: 'The paper describes a method for addressing the question.', excerpt: 'Self-attention computes a representation by relating different positions in a sequence.', sourceLocation: 'Methods, page 3', confidence: 0.74 }],
      supportStatus: 'direct',
      reliability: { score: 0.74, label: 'moderate', rationale: 'The explanation has direct support from 1 linked evidence item with a limiting confidence of 74%.', limitations: ['Source locations are recorded for the linked evidence.'] },
      simpleExplanation: 'Self-attention lets each token weigh the information from every other token.',
      paperContext: 'The paper describes a method for addressing the question.',
      evidenceIds: ['evidence-2'],
      confidence: 0.74,
    },
    {
      conceptId: 'finding',
      term: 'Parallel training',
      kind: 'finding',
      definition: 'Long sequences can be learned without waiting for recurrent steps.',
      useInPaper: 'The paper uses this to report or interpret an observed result.',
      supportingEvidence: [{ evidenceId: 'evidence-3', claim: 'The paper reports an outcome that can be compared.', excerpt: 'The model trains more efficiently because sequence positions can be processed in parallel.', sourceLocation: 'Results, page 5', confidence: 0.68 }],
      supportStatus: 'direct',
      reliability: { score: 0.68, label: 'moderate', rationale: 'The explanation has direct support from 1 linked evidence item with a limiting confidence of 68%.', limitations: ['This assesses evidence support, not whether the paper’s claim is universally true.'] },
      simpleExplanation: 'The model can process sequence positions together, shortening training time.',
      paperContext: 'The paper reports an outcome that can be compared.',
      evidenceIds: ['evidence-3'],
      confidence: 0.68,
    },
    {
      conceptId: 'experiment',
      term: 'WMT 2014',
      kind: 'experiment',
      definition: 'A translation benchmark used to compare model quality.',
      useInPaper: 'The paper uses this as part of the procedure for evaluating its proposal.',
      supportingEvidence: [{ evidenceId: 'evidence-2', claim: 'The paper describes a method for addressing the question.', excerpt: 'The translation benchmark provides a shared evaluation setting for the competing systems.', sourceLocation: 'Experiments, page 6', confidence: 0.74 }],
      supportStatus: 'contextual',
      reliability: { score: 0.68, label: 'moderate', rationale: 'The explanation has contextual support from 1 linked evidence item with a limiting confidence of 68%.', limitations: ['Benchmark performance may not generalize to every task.'] },
      simpleExplanation: 'WMT 2014 is the paper’s main translation test bed.',
      paperContext: 'The translation benchmark provides a shared evaluation setting.',
      evidenceIds: ['evidence-2'],
      confidence: 0.68,
    },
    {
      conceptId: 'metric',
      term: '+2 BLEU',
      kind: 'metric',
      definition: 'A quality lift over prior translation systems.',
      useInPaper: 'The paper uses this measurement to assess the quality or effect of its approach.',
      supportingEvidence: [{ evidenceId: 'evidence-3', claim: 'The paper reports an outcome that can be compared.', excerpt: 'BLEU measures the quality of generated translations against reference translations.', sourceLocation: 'Results, page 7', confidence: 0.68 }],
      supportStatus: 'direct',
      reliability: { score: 0.64, label: 'moderate', rationale: 'The explanation has direct support from 1 linked evidence item with a limiting confidence of 64%.', limitations: ['A single metric does not capture every aspect of translation quality.'] },
      simpleExplanation: 'The reported BLEU gain is the result signal to inspect first.',
      paperContext: 'The paper reports an outcome that can be compared.',
      evidenceIds: ['evidence-3'],
      confidence: 0.64,
    },
  ],
};

export const demoPapers: PaperSummary[] = [
  { id: 'paper-01', code: 'PAPER 01', title: 'Attention Is All You Need', authors: 'Vaswani et al.', year: '2017', relevance: 92, status: 'Mapped' },
  { id: 'paper-02', code: 'PAPER 02', title: 'Efficient Transformers', authors: 'Tay et al.', year: '2022', relevance: 81, status: 'Mapped' },
  { id: 'paper-03', code: 'PAPER 03', title: 'Long-Range Arena', authors: 'Tay et al.', year: '2021', relevance: 67, status: 'Queued' },
];

export async function analyzePaper(input: PaperInput): Promise<{ map: PaperMap; paper: PaperSummary }> {
  await new Promise((resolve) => setTimeout(resolve, 850));
  const sourceLabel = input.fileName?.replace(/\.[^/.]+$/, '') || input.source.match(/arxiv\.org\/abs\/([^/?]+)/)?.[1] || 'your paper';
  const cleanLabel = sourceLabel.length > 36 ? `${sourceLabel.slice(0, 36)}…` : sourceLabel;

  return {
    map: {
      ...demoMap,
      title: input.fileName ? `${cleanLabel} has a clear central claim.` : demoMap.title,
      summary: input.fileName ? 'The imported document has been reduced into a thesis, supporting method, measured outcome, and open comparison points.' : demoMap.summary,
    },
    paper: {
      id: `paper-${Date.now()}`,
      code: 'PAPER 04',
      title: input.fileName ? cleanLabel : 'Attention Is All You Need',
      authors: input.fileName ? 'Imported document' : 'Vaswani et al.',
      year: '2017',
      relevance: 92,
      status: 'Mapped',
    },
  };
}
