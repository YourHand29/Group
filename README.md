# Group — Paper Atlas

The first product slice lives in `site/` and follows the layered architecture from the reference:

- `site/app/` — interface and deployable route
- `site/lib/research-schema.ts` — typed response shape for concept maps
- `site/lib/research-orchestrator.ts` — mock orchestration boundary, ready to connect to a model API
- `site/.openai/hosting.json` — local Sites deployment configuration

Paper Atlas turns a research-paper link, abstract, or text file into a visual concept map. The current UI uses a deterministic demo model so the interaction can be validated before adding credentials or a production model provider.
