# Paper Atlas

Paper Atlas is a visual research workspace for quickly deciding whether a research paper is relevant enough to read deeply. A user submits a paper link, abstract, or text file. The system extracts the paper's central thesis, methods, findings, experiments, and evidence, then presents those relationships as a concept map. When multiple papers are present, the system highlights similar, supporting, extending, or conflicting ideas.

## Problem statement

Researchers and students screening a new literature area need a faster way to understand a paper's central claim, supporting evidence, and relationship to existing work because reading full papers sequentially makes early-stage literature triage slow and difficult to compare.

## Proposed solution

Paper Atlas uses a Python agentic workflow to turn unstructured research documents into evidence-backed, comparable structures:

1. Ingest a paper from text or an HTTP(S) URL.
2. Extract bounded text chunks for focused processing.
3. Identify the thesis, methods, findings, experiments, metrics, and supporting evidence.
4. Validate the structured result and retry a bounded number of times if it is invalid.
5. Produce a concise summary and relevance signal.
6. Compare the paper with existing papers and create relationship edges.
7. Return typed JSON to the web interface for deterministic graph rendering.

The agentic element is the controlled workflow: it maintains shared state, uses document tools, validates intermediate output, retries failures, and adapts its comparison step based on the papers already in the workspace. The graph renderer itself is deterministic frontend code, not another autonomous agent.

## Current repository structure

```text
Group/
├─ README.md
├─ site/                         # React/Vinext frontend
│  ├─ app/page.tsx               # Paper Atlas workspace UI
│  ├─ app/globals.css            # Visual system and responsive layout
│  ├─ app/layout.tsx             # Metadata and root layout
│  └─ lib/                       # Existing frontend demo data
└─ backend/                      # Python workflow backbone
   ├─ pyproject.toml             # Python dependencies and scripts
   ├─ .env.example               # Runtime configuration template
   ├─ src/paper_atlas/
   │  ├─ api.py                  # FastAPI /health and /analyze endpoints
   │  ├─ config.py               # Environment-backed settings
   │  ├─ graph.py                # LangGraph workflow and response adapter
   │  ├─ model.py                # Model provider boundary, demo, and Bedrock adapter
   │  ├─ nodes.py                # Workflow node functions and routing
   │  ├─ schemas.py              # Pydantic request, state payload, and output models
   │  ├─ state.py                # Shared LangGraph state definition
   │  └─ tools/documents.py      # URL/text/PDF ingestion and chunking
   └─ tests/                     # Workflow, ingestion, OCR, and agent tests
```

## AWS authentication for the team

### Team decision: Option 2 — named AWS credentials profile

For this shared four-person repository, use Option 2. Each teammate keeps their own AWS credentials in a local `paper-atlas` profile, while the code uses only the profile name. This avoids secrets in Git, avoids credentials in source code, and avoids having to paste environment variables into every terminal.

The repository does not contain AWS credentials and should not contain them. Each developer uses their own AWS CLI profile. The recommended setup is AWS IAM Identity Center (SSO), because the AWS CLI stores the profile configuration and temporary session cache on the developer's machine rather than in Git.

One developer setup:

```powershell
cd backend
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\scripts\aws-login.ps1 -ProfileName paper-atlas
.\scripts\aws-check.ps1
```

During the first login, AWS CLI asks for the organization's SSO start URL, SSO region, AWS account, and role. Put only non-secret runtime choices in `backend/.env`:

```text
PAPER_ATLAS_AWS_PROFILE=paper-atlas
PAPER_ATLAS_AWS_REGION=ap-southeast-1
PAPER_ATLAS_BEDROCK_MODEL_ID=
```

Change the region and profile to match the team's AWS setup. Do not put `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, session tokens, private keys, or passwords in `.env`, source code, or Git. `backend/.env` is ignored locally, while `backend/.env.example` is the safe template that can be committed.

The AWS session is cached by AWS CLI, so the backend can reuse it across restarts. SSO sessions expire by design; a user may occasionally need to run `.\scripts\aws-login.ps1 -ProfileName paper-atlas` again. No application can safely guarantee permanent login without using a long-lived secret or a managed IAM role. For deployed environments, use an IAM role attached to the compute service instead of sharing a developer profile.

The `paper-atlas-aws-check` command calls AWS STS only to confirm the active identity and never prints credentials. AWS connectivity is prepared for the future Bedrock model adapter; the current model remains `demo` until that adapter is implemented.

### If the hackathon gives you access key credentials

If the organizers provide an **AWS access key ID**, **AWS secret access key**, and **AWS session token**, they are temporary credentials. All three values are required together, and they expire at the time specified by the organizers. They are different from an SSO login.

On Windows, AWS CLI stores them in:

```text
C:\Users\<your-user>\.aws\credentials
```

The safest setup is to create a named profile with the AWS CLI. Do this in your own terminal and never paste the values into Git:

```powershell
aws configure --profile paper-atlas
```

Enter the access key ID and secret access key when prompted. Then add the session token to the same profile:

```text
[paper-atlas]
aws_access_key_id = YOUR_ACCESS_KEY_ID
aws_secret_access_key = YOUR_SECRET_ACCESS_KEY
aws_session_token = YOUR_SESSION_TOKEN
```

Do not add quotation marks. The credentials file is outside the repository and should remain private. In `backend/.env`, select the profile:

```text
PAPER_ATLAS_AWS_PROFILE=paper-atlas
PAPER_ATLAS_AWS_REGION=the-region-provided-by-the-organizers
```

Verify the profile without exposing the secret values:

```powershell
aws sts get-caller-identity --profile paper-atlas
cd backend
.\scripts\aws-check.ps1
```

If the organizers provide long-lived access keys instead, omit `aws_session_token`. If they provide temporary credentials, do not omit it. When temporary credentials expire, replace the three values or run the organizers' refresh procedure. Never commit `C:\Users\<your-user>\.aws\credentials`, `backend/.env`, or any credential values.

## Architecture

```text
site/ frontend
   │ POST /analyze
   ▼
FastAPI API
   ▼
LangGraph stateful workflow
   ├─ validate_input
   ├─ ingest_document
   ├─ extract_structure
   ├─ validate_output ── retry (bounded)
   ├─ summarise_paper
   └─ compare_papers
   ▼
Validated AnalysisResponse JSON
```

The backbone deliberately starts with an explicit graph rather than a free-form supervisor. LangGraph gives us typed state, node boundaries, conditional routing, bounded loops, and a future path to streaming and persistence. The model is isolated behind `ResearchModel`, so the deterministic demo implementation can later be replaced with a real provider without rewriting the workflow.

## Local setup

The frontend currently runs independently:

```powershell
cd site
npm install
npm run dev
```

The Python backend uses Python 3.11 or newer. With standard Python tooling:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m spacy download en_core_web_sm
Copy-Item .env.example .env
paper-atlas-api
```

The backend listens on `http://localhost:8080`.

Check it:

```powershell
Invoke-WebRequest http://localhost:8080/health
```

Run the workflow tests:

```powershell
pytest
```

Example request:

```powershell
$body = @{ source_type = "text"; source = "This paper proposes a method and evaluates it on a benchmark." } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8080/analyze -ContentType "application/json" -Body $body
```

For a local PDF, TXT, or Markdown file, use the multipart endpoint. The web UI uses this endpoint automatically when a file is selected:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8080/analyze-file -Form @{ file = Get-Item ".\paper.pdf"; existing_papers = "[]" }
```

### Paper text extraction and OCR

When a user submits an HTTP(S) paper page, the backend first checks the page for a publisher or repository PDF link (`citation_pdf_url`, PDF links, embeds, alternate PDF links, download-data attributes, and PDF URLs in page JSON). If a readable PDF is found, its URL becomes the effective paper source. Only when no usable PDF is available does the backend fall back to the article-content portion of the HTML page. The fetcher retries transient server responses and browser/challenge pages a bounded number of times. It does not execute arbitrary JavaScript; if a site only creates its PDF link after browser rendering, submit the direct PDF URL when possible.

PDF extraction removes repeated page headers and footers, publication boilerplate, page numbers, and sections after the main paper body such as references, acknowledgements, supplementary material, and appendices. The title, abstract, keywords, and main sections are retained because they are part of the paper text needed for screening. The same body filter is applied to text and Markdown uploads.

Text-based PDFs are read with `pypdf`. For scanned or image-only PDFs, install the optional OCR dependencies:

```powershell
cd backend
python -m pip install -e ".[ocr]"
```

OCR also requires the Tesseract OCR executable and Poppler's PDF rendering tools. Install both for Windows and make sure `tesseract.exe` and `pdftoppm.exe` are available on `PATH`. You can configure OCR with `PAPER_ATLAS_OCR_LANG` (default `eng`) and `PAPER_ATLAS_OCR_DPI` (default `220`). If OCR is not installed, text PDFs still work; an image-only PDF returns an actionable ingestion error instead of sending webpage chrome or an empty document to the model.

### Choosing the model provider

The default `demo` mode is deterministic and works offline. When the team has
AWS access, set both of these values in `backend/.env`:

```text
PAPER_ATLAS_MODEL_MODE=bedrock
PAPER_ATLAS_BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
```

The Bedrock adapter uses the configured local AWS profile and region, requests
strict JSON, and validates every returned evidence excerpt against the
ingested paper body before the workflow can complete. It supports Anthropic
Claude and Amazon Nova request formats, with a text-completion fallback for
legacy providers. If Bedrock mode is selected without a model ID, the app
falls back to the local demo model so incomplete optional configuration does
not break website analysis.

## Current limitations and next steps

- The default model is deterministic and requires no API key. An optional AWS Bedrock adapter is available by setting `PAPER_ATLAS_MODEL_MODE=bedrock` and `PAPER_ATLAS_BEDROCK_MODEL_ID`. The frontend calls the Python `/analyze` endpoint, so URL/text submissions execute the backend graph.
- Paper concepts are augmented with spaCy named-entity recognition, then filtered to entities with an English Wikipedia article. The first setup downloads `en_core_web_sm`; set `PAPER_ATLAS_SPACY_MODEL` to another installed spaCy pipeline when a domain-specific model is preferred.
- Concept recognition also extracts noun phrases and named-law/theory patterns, links them to canonical Wikipedia pages, checks Wikidata `instance of`/`subclass of` types, and exposes Wikipedia, Wikidata, DOI, university, government, and publisher references in the Concepts view. A source-backed label means the concept is documented and referenced; it is not a claim that the paper's interpretation is universally true.
- File uploads now use a multipart `/analyze-file` endpoint for PDF, TXT, and Markdown files. This path works without internet access.
- URL ingestion prefers a discoverable PDF and reports the effective format/source in the response trace; scanned/image-only PDFs use the optional OCR fallback described above.
- Similarity uses weighted token overlap and explicit-language relationship cues; embeddings can be added later.
- Completed responses are persisted locally in SQLite (by default in the operating system temporary directory) and can be retrieved with `GET /runs/{run_id}`.
- `POST /analyze/stream` emits server-sent progress events. Responses expose lightweight quality telemetry for schema validity, citation/location coverage, retries, input size, chunk count, and latency.
- Citation navigation in the UI and human review are future steps.

## Next implementation order

1. Add resumable checkpoints and citation navigation in the UI.
2. Add a two-paper comparison fixture and improve relationships.
3. Add embeddings only after the concept and relationship schema is stable.
4. Measure schema pass rate, citation coverage, relevance agreement, latency, retries, and token cost.
