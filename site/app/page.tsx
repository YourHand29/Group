'use client';

import { ChangeEvent, useMemo, useState } from 'react';
import type { MapNode, PaperMap, PaperSummary } from '../lib/research-schema';
import { demoMap, demoPapers } from '../lib/research-orchestrator';

type ViewMode = 'map' | 'evidence' | 'notes';
const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8080';

type BackendAnalysisResponse = {
  run_id: string;
  status: 'completed' | 'failed';
  paper: { title: string; authors: string[]; year: number | null; source_url: string | null } | null;
  thesis: string;
  summary: string;
  relevance: number;
  concepts: Array<{ id: string; label: string; kind: MapNode['kind']; description: string; confidence: number }>;
  relationships: Array<{ target_id: string; explanation: string; confidence: number }>;
  warnings: string[];
  trace: string[];
  query: string | null;
  query_matches: string[];
};

const nodePositions: Record<string, string> = {
  thesis: 'node-thesis',
  method: 'node-method',
  finding: 'node-finding',
  experiment: 'node-experiment',
  metric: 'node-metric',
};

function PaperIcon({ tone = 'default' }: { tone?: 'default' | 'mint' | 'coral' }) {
  return <span aria-hidden="true" className={`paper-icon paper-icon-${tone}`} />;
}

function MapNodeCard({ node, selected, onSelect }: { node: MapNode; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      className={`map-node ${nodePositions[node.id]} ${selected ? 'map-node-selected' : ''}`}
      onClick={onSelect}
      aria-pressed={selected}
    >
      <span className="map-node-kicker">{node.kind}</span>
      <strong>{node.label}</strong>
      <span className="map-node-detail">{node.detail}</span>
    </button>
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
  const [fileText, setFileText] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [map, setMap] = useState<PaperMap>(demoMap);
  const [papers, setPapers] = useState<PaperSummary[]>(demoPapers);
  const [selectedNode, setSelectedNode] = useState('thesis');
  const [activePaper, setActivePaper] = useState('paper-01');
  const [viewMode, setViewMode] = useState<ViewMode>('map');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [status, setStatus] = useState('Ready to map a new paper');
  const [relationshipSummary, setRelationshipSummary] = useState('Paper 01 and Paper 02 converge on efficient context mixing.');
  const [relationshipCount, setRelationshipCount] = useState(2);

  const selectedNodeData = useMemo(
    () => map.nodes.find((node) => node.id === selectedNode) ?? map.nodes[0],
    [map.nodes, selectedNode],
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
      setSelectedNode('thesis');
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

  const handleFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setSelectedFile(file);
    setFileText(file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf') ? '' : await file.text());
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
              <div className="map-toolbar"><div className="view-tabs" role="tablist" aria-label="Map views">{(['map', 'evidence', 'notes'] as ViewMode[]).map((view) => <button key={view} type="button" role="tab" aria-selected={viewMode === view} className={viewMode === view ? 'view-tab-active' : ''} onClick={() => setViewMode(view)}>{view === 'map' ? 'Map' : view === 'evidence' ? 'Evidence' : 'Notes'}</button>)}</div><span className="map-toolbar-label"><span className="legend-dot legend-dot-teal" /> Core idea <span className="legend-dot legend-dot-coral" /> Signal</span></div>
              {viewMode === 'map' ? <div className="graph-scroll"><div className="graph-canvas"><div className="graph-grid" /><div className="graph-line graph-line-thesis-method" /><div className="graph-line graph-line-thesis-finding" /><div className="graph-line graph-line-thesis-experiment" /><div className="graph-line graph-line-thesis-metric" /><div className="association-link"><span>↔ related across 2 papers</span></div>{map.nodes.map((node) => <MapNodeCard key={node.id} node={node} selected={selectedNode === node.id} onSelect={() => setSelectedNode(node.id)} />)}<span className="graph-caption">Click a node to inspect the paper’s logic</span></div></div> : <div className="alternate-view"><span className="alternate-icon">{viewMode === 'evidence' ? '◒' : '✦'}</span><h3>{viewMode === 'evidence' ? 'Evidence is clustered around one claim' : 'Notes layer coming into focus'}</h3><p>{viewMode === 'evidence' ? 'The strongest support is the 41% reduction in training cost across three benchmark datasets.' : 'Save your reactions beside any concept as you compare papers.'}</p><button type="button" className="secondary-button" onClick={() => setViewMode('map')}>Back to map</button></div>}
              <div className="map-card-foot"><span><b>5</b> concepts</span><span><b>4</b> relationships</span><span><b>3</b> evidence signals</span><span className="map-updated">Updated just now <i /></span></div>
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
