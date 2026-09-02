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
