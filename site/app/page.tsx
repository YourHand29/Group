'use client';

import { ChangeEvent, useEffect, useMemo, useRef, useState } from 'react';
import cytoscape from 'cytoscape';
import type { ConceptExplanation, MapNode, PaperMap, PaperSummary } from '../lib/research-schema';
import { demoMap, demoPapers } from '../lib/research-orchestrator';

type ViewMode = 'map' | 'evidence' | 'notes' | 'concepts';
const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8080';

type BackendConcept = {
  id: string;
  label: string;
  kind: MapNode['kind'];
  description: string;
  confidence: number;
  concept_type?: string | null;
  wikipedia_url?: string | null;
  wikidata_id?: string | null;
  source_urls?: string[];
  recognition_status?: ConceptExplanation['recognitionStatus'];
};
type BackendConceptExplanation = {
  concept_id: string;
  term: string;
  kind: MapNode['kind'];
  definition: string;
  use_in_paper: string;
  supporting_evidence: Array<{ evidence_id: string; claim: string; excerpt: string; source_location: string | null; confidence: number }>;
  support_status: ConceptExplanation['supportStatus'];
  reliability: ConceptExplanation['reliability'];
  simple_explanation: string;
  paper_context: string;
  evidence_ids: string[];
  confidence: number;
  concept_type?: string | null;
  wikipedia_url?: string | null;
  wikidata_id?: string | null;
  source_urls?: string[];
  recognition_status?: ConceptExplanation['recognitionStatus'];
};

type BackendAnalysisResponse = {
  run_id: string;
  status: 'completed' | 'failed';
  paper: { title: string; authors: string[]; year: number | null; source_url: string | null } | null;
  thesis: string;
  summary: string;
  relevance: number;
  concepts: BackendConcept[];
  concept_explanations?: BackendConceptExplanation[];
  relationships: Array<{ target_id: string; explanation: string; confidence: number }>;
  warnings: string[];
  trace: string[];
  query: string | null;
  query_matches: string[];
};

const viewLabels: Record<ViewMode, string> = {
  map: 'Map',
  evidence: 'Evidence',
  notes: 'Notes',
  concepts: 'Concepts',
};

const conceptKindUsage: Record<MapNode['kind'], string> = {
  concept: 'The paper uses this named entity as a relevant concept or reference point.',
  thesis: 'The paper uses this as its central claim or proposed answer.',
  method: 'The paper uses this as its approach for addressing the research problem.',
  finding: 'The paper uses this to report or interpret an observed result.',
  experiment: 'The paper uses this as part of the procedure for evaluating its proposal.',
  metric: 'The paper uses this measurement to assess the quality or effect of its approach.',
};

function fallbackExplanation(concept: BackendConcept): ConceptExplanation {
  return {
    conceptId: concept.id,
    term: concept.label,
    kind: concept.kind,
    definition: concept.description,
    useInPaper: conceptKindUsage[concept.kind],
    supportingEvidence: [],
    supportStatus: 'unsupported',
    reliability: {
      score: 0,
      label: 'low',
      rationale: 'No evidence-grounded explanation was returned by the analysis service.',
      limitations: ['Verify this concept against the paper or cited literature.'],
    },
    simpleExplanation: concept.description,
    paperContext: 'No supporting evidence was extracted for this concept.',
    evidenceIds: [],
    confidence: 0,
    conceptType: concept.concept_type ?? null,
    wikipediaUrl: concept.wikipedia_url ?? null,
    wikidataId: concept.wikidata_id ?? null,
    sourceUrls: concept.source_urls ?? [],
    recognitionStatus: concept.recognition_status ?? 'structural',
  };
}

function toConceptExplanation(explanation: BackendConceptExplanation): ConceptExplanation {
  return {
    conceptId: explanation.concept_id,
    term: explanation.term,
    kind: explanation.kind,
    definition: explanation.definition,
    useInPaper: explanation.use_in_paper,
    supportingEvidence: explanation.supporting_evidence.map((evidence) => ({
      evidenceId: evidence.evidence_id,
      claim: evidence.claim,
      excerpt: evidence.excerpt,
      sourceLocation: evidence.source_location,
      confidence: evidence.confidence,
    })),
    supportStatus: explanation.support_status,
    reliability: explanation.reliability,
    simpleExplanation: explanation.simple_explanation,
    paperContext: explanation.paper_context,
    evidenceIds: explanation.evidence_ids,
    confidence: explanation.confidence,
    conceptType: explanation.concept_type ?? null,
    wikipediaUrl: explanation.wikipedia_url ?? null,
    wikidataId: explanation.wikidata_id ?? null,
    sourceUrls: explanation.source_urls ?? [],
    recognitionStatus: explanation.recognition_status ?? 'recognized',
  };
}

function PaperIcon({ tone = 'default' }: { tone?: 'default' | 'mint' | 'coral' }) {
  return <span aria-hidden="true" className={`paper-icon paper-icon-${tone}`} />;
}

const graphRelationships = [
  { id: 'thesis-method', source: 'thesis', target: 'method', label: 'uses' },
  { id: 'thesis-finding', source: 'thesis', target: 'finding', label: 'leads to' },
  { id: 'thesis-experiment', source: 'thesis', target: 'experiment', label: 'tested by' },
  { id: 'thesis-metric', source: 'thesis', target: 'metric', label: 'measured by' },
];

function CytoscapeMap({ nodes, selectedNode, onSelect }: { nodes: MapNode[]; selectedNode: string; onSelect: (nodeId: string) => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const onSelectRef = useRef(onSelect);

  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  useEffect(() => {
    if (!containerRef.current || !nodes.length) return;

    const graphWidth = containerRef.current.clientWidth;
    const graphHeight = containerRef.current.clientHeight;
    const graphPositions: Record<string, { x: number; y: number }> = {
      thesis: { x: graphWidth * 0.5, y: graphHeight * 0.5 },
      method: { x: graphWidth * 0.2, y: graphHeight * 0.23 },
      finding: { x: graphWidth * 0.8, y: graphHeight * 0.23 },
      experiment: { x: graphWidth * 0.25, y: graphHeight * 0.77 },
      metric: { x: graphWidth * 0.75, y: graphHeight * 0.77 },
    };
    const nodeIds = new Set(nodes.map((node) => node.id));
    const entityPositions = new Map(
      nodes
        .filter((node) => node.kind === 'concept')
        .map((node, index) => [node.id, {
          x: graphWidth * (0.12 + (index % 4) * 0.25),
          y: graphHeight * (index % 2 === 0 ? 0.08 : 0.92),
        }]),
    );
    const entityRelationships = nodes
      .filter((node) => node.kind === 'concept')
      .map((node) => ({ id: `thesis-${node.id}`, source: 'thesis', target: node.id, label: 'mentions' }));
    const relationships = [...graphRelationships, ...entityRelationships];
    const cy = cytoscape({
      container: containerRef.current,
      elements: [
        ...nodes.map((node, index) => ({
          data: { id: node.id, label: node.label, kind: node.kind, detail: node.detail },
          position: graphPositions[node.id] ?? entityPositions.get(node.id) ?? {
            x: graphWidth * 0.5 + ((index % 3) - 1) * 100,
            y: graphHeight * 0.5 + (Math.floor(index / 3) - 1) * 90,
          },
        })),
        ...relationships
          .filter((relationship) => nodeIds.has(relationship.source) && nodeIds.has(relationship.target))
          .map((relationship) => ({ data: relationship })),
      ],
      style: [
        {
          selector: 'node',
          style: {
            'background-color': '#ffffff',
            'border-color': '#d7e5e8',
            'border-width': 1,
            'color': '#192b4e',
            'font-family': 'DM Sans',
            'font-size': 13,
            'font-weight': 600,
            height: 76,
            label: 'data(label)',
            padding: 8,
            shape: 'roundrectangle',
            'text-halign': 'center',
            'text-max-width': 130,
            'text-valign': 'center',
            'text-wrap': 'wrap',
            width: 152,
          },
        },
        {
          selector: 'node[kind = "thesis"]',
          style: {
            'background-color': '#effbf8',
            'border-color': '#8bd5c8',
            'border-width': 2,
            'font-size': 15,
            height: 96,
            width: 184,
          },
        },
        {
          selector: 'node:selected',
          style: {
            'border-color': '#43c4ad',
            'border-width': 3,
            'overlay-color': '#43c4ad',
            'overlay-opacity': 0.08,
            'overlay-padding': 6,
          },
        },
        {
          selector: 'node[kind = "concept"]',
          style: {
            'background-color': '#f4f5ff',
            'border-color': '#b8bde8',
            color: '#34366c',
          },
        },
        {
          selector: 'edge',
          style: {
            'curve-style': 'bezier',
            'font-family': 'DM Mono',
            'font-size': 9,
            'line-color': '#a9dcd4',
            label: 'data(label)',
            'target-arrow-color': '#79c8bc',
            'target-arrow-shape': 'triangle',
            'text-background-color': '#ffffff',
            'text-background-opacity': 0.9,
            'text-background-padding': 3,
            color: '#6e9c99',
            'text-rotation': 'autorotate',
            width: 2,
          },
        },
      ],
      maxZoom: 1.8,
      minZoom: 0.45,
    });

    cyRef.current = cy;
    cy.on('tap', 'node', (event) => onSelectRef.current(event.target.id()));
    const layout = cy.layout({
      name: 'preset',
      animate: false,
      fit: true,
      padding: 30,
    });
    const fitGraph = () => {
      cy.resize();
      cy.fit(cy.elements(), 30);
    };
    layout.on('layoutstop', fitGraph);
    layout.run();
    fitGraph();
    const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(fitGraph);
    resizeObserver?.observe(containerRef.current);

    return () => {
      resizeObserver?.disconnect();
      cy.destroy();
      cyRef.current = null;
    };
  }, [nodes]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().unselect();
    const selected = cy.getElementById(selectedNode);
    if (selected.length) selected.select();
  }, [selectedNode]);

  return (
    <div className="graph-scroll">
      <div ref={containerRef} className="cytoscape-graph" role="application" aria-label="Interactive research concept graph">
        <span className="graph-caption">Drag nodes · scroll to zoom · click to inspect</span>
      </div>
    </div>
  );
}

function ConceptExplanationCard({ explanation, expanded, onToggle }: { explanation: ConceptExplanation; expanded: boolean; onToggle: () => void }) {
  const evidenceLabel = explanation.supportingEvidence.length === 1 ? '1 linked evidence item' : `${explanation.supportingEvidence.length} linked evidence items`;
  const sourceUrls = explanation.sourceUrls ?? [];
  const referenceUrls = sourceUrls.filter((url) => url !== explanation.wikipediaUrl && !url.includes('wikidata.org/wiki/')).slice(0, 3);

  return (
    <article className={`concept-card ${expanded ? 'concept-card-expanded' : ''}`}>
      <button type="button" className="concept-card-trigger" onClick={onToggle} aria-expanded={expanded}>
        <span className="concept-card-head">
          <span className="concept-card-kind">{explanation.kind} · {explanation.reliability.label} support</span>
          <span className={`concept-status concept-status-${explanation.supportStatus}`}>{explanation.supportStatus}</span>
        </span>
        <strong>{explanation.term}</strong>
        {explanation.conceptType && <span className="concept-card-type">{explanation.conceptType}</span>}
        <span className="concept-card-definition">{explanation.definition}</span>
        <span className="concept-card-toggle">{expanded ? 'Hide explanation' : evidenceLabel}<span aria-hidden="true">{expanded ? '⌃' : '⌄'}</span></span>
      </button>

      {expanded && (
        <div className="concept-card-details">
          <div className="concept-detail-block">
            <span className="concept-detail-label">In this paper</span>
            <p>{explanation.useInPaper}</p>
          </div>
          <div className="concept-detail-block">
            <span className="concept-detail-label">Plain-language read</span>
            <p>{explanation.simpleExplanation}</p>
          </div>
          <div className="concept-reliability">
            <div className="concept-reliability-row"><span>Evidence reliability</span><strong>{Math.round(explanation.reliability.score * 100)}% · {explanation.reliability.label}</strong></div>
            <div className="concept-reliability-track"><span style={{ width: `${explanation.reliability.score * 100}%` }} /></div>
            <p>{explanation.reliability.rationale}</p>
          </div>
          <div className="concept-detail-block">
            <span className="concept-detail-label">Linked evidence</span>
            {explanation.supportingEvidence.length ? (
              <ul className="concept-evidence-list">
                {explanation.supportingEvidence.map((evidence) => (
                  <li key={evidence.evidenceId}>
                    <strong>{evidence.claim}</strong>
                    <span>“{evidence.excerpt}”{evidence.sourceLocation ? ` · ${evidence.sourceLocation}` : ''}</span>
                  </li>
                ))}
              </ul>
            ) : <p>{explanation.paperContext}</p>}
          </div>
          {(explanation.wikipediaUrl || explanation.wikidataId || referenceUrls.length > 0) && (
            <div className="concept-detail-block">
              <span className="concept-detail-label">Recognition sources</span>
              <div className="concept-source-links">
                {explanation.wikipediaUrl && <a href={explanation.wikipediaUrl} target="_blank" rel="noreferrer">Wikipedia</a>}
                {explanation.wikidataId && <a href={`https://www.wikidata.org/wiki/${explanation.wikidataId}`} target="_blank" rel="noreferrer">Wikidata</a>}
                {referenceUrls.map((url, index) => <a key={url} href={url} target="_blank" rel="noreferrer">Reference {index + 1}</a>)}
              </div>
              <p>{explanation.recognitionStatus === 'source_supported' ? 'Classified and supported by linked authoritative references.' : 'Classified using a canonical Wikipedia page and Wikidata type.'}</p>
            </div>
          )}
          {explanation.reliability.limitations.length > 0 && (
            <div className="concept-limitations"><span className="concept-detail-label">Read with care</span><p>{explanation.reliability.limitations[0]}</p></div>
          )}
        </div>
      )}
    </article>
  );
}

function ConceptsView({ explanations, expandedConceptId, onToggle }: { explanations: ConceptExplanation[]; expandedConceptId: string | null; onToggle: (conceptId: string) => void }) {
  return (
    <div className="concepts-view">
      <div className="concepts-view-intro">
        <div><span className="concepts-view-label">EXPLAIN CONCEPT</span><h3>What does the paper mean?</h3></div>
        <span>{explanations.length} identified concepts</span>
      </div>
      <p className="concepts-view-copy">Select a concept to see its role in the paper, how strongly the evidence supports it, and where to verify it.</p>
      <div className="concepts-grid" role="list" aria-label="Identified concepts">
        {explanations.map((explanation) => (
          <ConceptExplanationCard key={explanation.conceptId} explanation={explanation} expanded={expandedConceptId === explanation.conceptId} onToggle={() => onToggle(explanation.conceptId)} />
        ))}
      </div>
    </div>
  );
}

function PaperCard({ paper, active, onClick }: { paper: PaperSummary; active: boolean; onClick: () => void }) {
  return (
    <button type="button" className={`paper-card ${active ? 'paper-card-active' : ''}`} onClick={onClick}>
      <span className="paper-card-topline">
        <PaperIcon tone={active ? 'mint' : 'default'} />
        <span>{paper.code}</span>
        <span className="paper-card-status">{paper.status}</span>
      </span>
      <strong>{paper.title}</strong>
      <span className="paper-card-meta">{paper.authors} · {paper.year}</span>
      <span className="paper-card-match"><span style={{ width: `${paper.relevance}%` }} /> {paper.relevance}% relevant</span>
    </button>
  );
}

export default function Home() {
  const [paperInput, setPaperInput] = useState('https://arxiv.org/abs/1706.03762');
  const [fileName, setFileName] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [map, setMap] = useState<PaperMap>(demoMap);
  const [papers, setPapers] = useState<PaperSummary[]>(demoPapers);
  const [selectedNode, setSelectedNode] = useState('thesis');
  const [activePaper, setActivePaper] = useState('paper-01');
  const [viewMode, setViewMode] = useState<ViewMode>('map');
  const [expandedConceptId, setExpandedConceptId] = useState<string | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [status, setStatus] = useState('Ready to map a new paper');
  const [relationshipSummary, setRelationshipSummary] = useState('Paper 01 and Paper 02 converge on efficient context mixing.');
  const [relationshipCount, setRelationshipCount] = useState(2);

  const selectedNodeData = useMemo(
    () => map.nodes.find((node) => node.id === selectedNode) ?? map.nodes[0],
    [map.nodes, selectedNode],
  );

  const evidenceCount = useMemo(
    () => new Set(map.explanations.flatMap((explanation) => explanation.evidenceIds)).size,
    [map.explanations],
  );

  const handleAnalyze = async () => {
    if (!paperInput.trim() && !fileName) {
      setStatus('Add a paper link, abstract, or text file first');
      return;
    }

    if (fileName && !selectedFile) {
      setStatus('This file could not be read as text');
      return;
    }

    setIsAnalyzing(true);
    setStatus('Reading the paper and finding its signal…');
    try {
      const existingPapers = papers.map((paper) => ({ id: paper.id, title: paper.title, concepts: [paper.title, paper.authors] }));
      const response = selectedFile
        ? await (() => {
            const formData = new FormData();
            formData.append('file', selectedFile);
            formData.append('existing_papers', JSON.stringify(existingPapers));
            formData.append('instruction', paperInput.trim());
            return fetch(`${BACKEND_URL}/analyze-file`, { method: 'POST', body: formData });
          })()
        : await fetch(`${BACKEND_URL}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              source_type: /^https?:\/\//i.test(paperInput.trim()) ? 'url' : 'text',
              source: paperInput.trim(),
              existing_papers: existingPapers,
            }),
          });
      const result = (await response.json()) as BackendAnalysisResponse | { detail?: string | string[] };
      if (!response.ok || !('concepts' in result) || result.status !== 'completed' || !result.paper) {
        const detail = 'detail' in result ? result.detail : undefined;
        throw new Error(Array.isArray(detail) ? detail.join(', ') : detail || 'The analysis service rejected this paper');
      }

      const nextMap: PaperMap = {
        title: result.thesis,
        summary: result.summary,
        relevance: result.relevance,
        nodes: result.concepts.map((concept) => ({ id: concept.id, kind: concept.kind, label: concept.label, detail: concept.description })),
        explanations: result.concept_explanations?.length
          ? result.concept_explanations.map(toConceptExplanation)
          : result.concepts.map(fallbackExplanation),
      };
      const nextPaper: PaperSummary = {
        id: result.run_id,
        code: `PAPER ${String(papers.length + 1).padStart(2, '0')}`,
        title: result.paper.title,
        authors: result.paper.authors.join(', ') || 'Imported document',
        year: result.paper.year ? String(result.paper.year) : '—',
        relevance: result.relevance,
        status: 'Mapped',
      };
      setMap(nextMap);
      setPapers((current) => [nextPaper, ...current.filter((paper) => paper.id !== nextPaper.id)]);
      setActivePaper(nextPaper.id);
      setSelectedNode(result.concepts[0]?.id ?? 'thesis');
      setExpandedConceptId(null);
      setRelationshipCount(result.relationships.length);
      setRelationshipSummary(result.relationships[0]?.explanation || 'No strong overlap found yet. Add another paper to discover a connection.');
      const queryStatus = result.query
        ? result.query_matches.length
          ? ` · Found ${result.query_matches.length} text match${result.query_matches.length === 1 ? '' : 'es'} for “${result.query}”`
          : ` · No exact text match for “${result.query}”; map still generated`
        : '';
      setStatus(`Map ready · ${result.concepts.length} concepts connected${queryStatus}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Could not reach the analysis service');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setSelectedFile(file);
    setStatus(`${file.name} is ready to analyze`);
  };

  return (
    <main className="atlas-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <span className="brand-mark"><i /><i /><i /></span>
          <span>paper<span className="brand-slash">/</span>atlas</span>
        </div>

        <div className="sidebar-section">
          <span className="sidebar-label">Workspace</span>
          <nav className="side-nav" aria-label="Workspace navigation">
            <button className="side-nav-item side-nav-item-active" type="button"><span>◈</span> Overview</button>
            <button className="side-nav-item" type="button"><span>⌘</span> Collections <em>3</em></button>
            <button className="side-nav-item" type="button"><span>↗</span> Connections</button>
          </nav>
        </div>

        <div className="sidebar-section sidebar-library">
          <div className="sidebar-label-row"><span className="sidebar-label">Recent maps</span><button type="button" aria-label="Add recent map">+</button></div>
          <button type="button" className="recent-map recent-map-active"><span className="recent-dot" />Transformer architectures <small>now</small></button>
          <button type="button" className="recent-map"><span className="recent-dot recent-dot-lilac" />Climate adaptation <small>yesterday</small></button>
          <button type="button" className="recent-map"><span className="recent-dot recent-dot-amber" />Synthetic biology <small>Aug 28</small></button>
        </div>

        <div className="sidebar-footer">
          <div className="model-status"><span className="status-pulse" /><span><strong>AI schema online</strong><small>Local-first runtime</small></span></div>
          <div className="user-chip"><span className="avatar">JS</span><span>Jordan Smith</span><span className="user-chevron">⌄</span></div>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="breadcrumb"><span>Workspace</span><b>/</b><strong>Transformer architectures</strong></div>
          <div className="topbar-actions"><span className="sync-label"><span className="sync-dot" /> Autosaved</span><button type="button" className="icon-button" aria-label="Search">⌕</button><button type="button" className="help-button">?</button></div>
        </header>

        <div className="workspace-content">
          <div className="page-intro">
            <div>
              <span className="eyebrow"><span className="eyebrow-line" /> PAPER ATLAS <span className="eyebrow-number">/ 01</span></span>
              <h1>See the shape<br /><em>of an idea.</em></h1>
              <p className="intro-copy">Turn dense research into a visual signal map.<br className="desktop-break" /> Find the paper that is worth your next deep read.</p>
            </div>
            <div className="intro-actions"><button type="button" className="text-button">Tour the workspace <span>↗</span></button><button type="button" className="primary-button" onClick={() => document.getElementById('paper-input')?.focus()}><span>+</span> Add paper</button></div>
          </div>

          <section className="ingest-card" aria-label="Add a research paper">
            <div className="ingest-head"><div><span className="card-eyebrow">REQUEST <span>01</span></span><h2>What are you reading?</h2></div><span className={`processing-state ${isAnalyzing ? 'processing-state-active' : ''}`}><span /> {isAnalyzing ? 'Analyzing source' : status}</span></div>
            <div className="input-wrap"><span className="input-leading">↳</span><textarea id="paper-input" value={paperInput} onChange={(event) => setPaperInput(event.target.value)} placeholder={selectedFile ? 'Optional instruction for this uploaded paper…' : 'Paste a paper link, abstract, or text…'} rows={2} /><button type="button" className={`analyze-button ${isAnalyzing ? 'analyze-button-loading' : ''}`} onClick={handleAnalyze} disabled={isAnalyzing}>{isAnalyzing ? 'Mapping…' : 'Analyze paper'} <span>→</span></button></div>
            <div className="ingest-foot"><label className="file-trigger"><input type="file" accept=".txt,.md,.pdf" onChange={handleFile} /> <span>＋</span> {fileName || 'Drop a .txt, .md, or .pdf'}</label><span className="ingest-hint">AI extracts the thesis, methods, evidence, and open questions</span></div>
          </section>

          <div className="signal-grid">
            <section className="map-card" aria-label="Research concept map">
              <div className="map-card-head"><div><span className="card-eyebrow">RESPONSE <span>02</span></span><h2>Concept map</h2></div><div className="map-head-actions"><span className="confidence-pill"><i /> {map.relevance}% relevance</span><button type="button" className="small-icon-button" aria-label="More map options">···</button></div></div>
              <div className="map-toolbar"><div className="view-tabs" role="tablist" aria-label="Map views">{(['map', 'evidence', 'notes', 'concepts'] as ViewMode[]).map((view) => <button key={view} type="button" role="tab" aria-selected={viewMode === view} className={viewMode === view ? 'view-tab-active' : ''} onClick={() => setViewMode(view)}>{viewLabels[view]}</button>)}</div><span className="map-toolbar-label"><span className="legend-dot legend-dot-teal" /> Core idea <span className="legend-dot legend-dot-coral" /> Signal</span></div>
              {viewMode === 'map' ? <CytoscapeMap nodes={map.nodes} selectedNode={selectedNode} onSelect={setSelectedNode} /> : viewMode === 'concepts' ? <ConceptsView explanations={map.explanations} expandedConceptId={expandedConceptId} onToggle={(conceptId) => { setSelectedNode(conceptId); setExpandedConceptId((current) => current === conceptId ? null : conceptId); }} /> : <div className="alternate-view"><span className="alternate-icon">{viewMode === 'evidence' ? '◒' : '✦'}</span><h3>{viewMode === 'evidence' ? 'Evidence is clustered around one claim' : 'Notes layer coming into focus'}</h3><p>{viewMode === 'evidence' ? 'The strongest support is the 41% reduction in training cost across three benchmark datasets.' : 'Save your reactions beside any concept as you compare papers.'}</p><button type="button" className="secondary-button" onClick={() => setViewMode('map')}>Back to map</button></div>}
              <div className="map-card-foot"><span><b>{map.nodes.length}</b> concepts</span><span><b>{relationshipCount}</b> relationships</span><span><b>{evidenceCount}</b> evidence signals</span><span className="map-updated">Updated just now <i /></span></div>
            </section>

            <aside className="insight-column">
              <section className="insight-card insight-card-primary"><div className="insight-head"><span className="card-eyebrow">SIGNAL <span>03</span></span><span className="signal-badge">Strong signal</span></div><h2>{map.title}</h2><p>{map.summary}</p><div className="insight-divider" /><div className="selected-node"><span className="selected-node-label">Selected concept</span><strong>{selectedNodeData.label}</strong><span>{selectedNodeData.detail}</span></div><div className="confidence-row"><span>Relevance to your workspace</span><strong>{map.relevance}%</strong></div><div className="progress-track"><span style={{ width: `${map.relevance}%` }} /></div><button type="button" className="outline-button">Open source <span>↗</span></button></section>
              <section className="insight-card connection-card"><div className="connection-orbit"><span className="orbit-core">{relationshipCount}</span><span className="orbit-dot orbit-dot-one" /><span className="orbit-dot orbit-dot-two" /></div><div><span className="card-eyebrow">CONNECTION</span><h3>{relationshipCount ? 'Shared research patterns' : 'No strong overlap yet'}</h3><p>{relationshipSummary}</p><button type="button" className="text-button text-button-small" onClick={() => setActivePaper('paper-02')}>Explore overlap <span>→</span></button></div></section>
            </aside>
          </div>

          <section className="paper-section"><div className="section-heading"><div><span className="card-eyebrow">LIBRARY <span>04</span></span><h2>Papers in this workspace</h2></div><button type="button" className="text-button">View all <span>→</span></button></div><div className="paper-grid">{papers.slice(0, 3).map((paper) => <PaperCard key={paper.id} paper={paper} active={activePaper === paper.id} onClick={() => setActivePaper(paper.id)} />)}<button type="button" className="add-paper-card" onClick={() => document.getElementById('paper-input')?.focus()}><span>+</span><strong>Add another paper</strong><small>Compare ideas across a collection</small></button></div></section>
        </div>
      </section>
    </main>
  );
}
