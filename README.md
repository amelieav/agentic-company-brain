# agentic-company-brain

A proof of concept for an internal "company brain": one natural-language interface that routes questions and tasks
to specialist agents, retrieves from internal documents, queries business data, and asks for human approval before
anything with side effects runs. Built with LangGraph, LangChain and OpenAI. The demo company is a fictional
bakery, Moonpool Bakehouse, which makes Blue Sherbet cookies.

## Architecture

```
user -> planner (multi-intent split) -> parallel fan-out
                                         |- knowledge agent  (RAG over markdown + PDFs, filtered by role)
                                         |- analytics agent  (tools over sales / invoices / costs CSVs)
                                         |- action node      (human approval via interrupt, then run automation)
                                         '- denied           (role lacks the capability)
        -> synthesise -> answer
```

- **Role-based access:** `staff`, `manager`, `exec`. Capabilities are checked per task, and every document chunk
  carries a `min_role` that is enforced at retrieval time, not in the prompt.
- **Human in the loop:** actions pause with a LangGraph `interrupt`; nothing runs until approved.
- **Audit trail:** plans, retrievals, denials, approvals and executions go to `audit.jsonl`.
- **Memory:** conversation state is kept per user by a checkpointer (in memory for now).

## Run the web app (local)

```bash
uv sync
uv run uvicorn api:app --reload      # then open http://localhost:8000
```

1. Pick a demo account on the simulated Microsoft Entra sign-in. The backend issues a signed JWT with an
   app role (`Brain.Staff`, `Brain.Manager` or `Brain.Exec`). The API takes identity and role only from that
   validated token, never from the request body.
2. Paste your own OpenAI key. It is validated, then held in server memory for the session only (never written
   to disk, logs or the audit trail) and dropped on sign-out.
3. Chat. The side panel shows the token claims, what the role may use, and a live audit trail.

The same `web/` folder works as a static site (for example GitHub Pages). With no backend it runs in demo mode:
sign-in works, and where a key would be used it plays `web/demo.mp4` (record and add that file yourself).

## Run the CLI

```bash
cp .env.example .env        # add OPENAI_API_KEY
uv run python company_brain.py --role manager
```

## Checks

- `uv run pytest` runs the API and auth tests (no key or network needed).
- `uv run python scripts/smoke_test.py` checks the graph wiring, role denials and approval flow with a stubbed model.
- `uv run python scripts/make_data.py` regenerates the fake data.

Try as `manager`: "Which accounts are over 60 days overdue, and send Nimbus Vending a payment reminder."
Try as `staff`: "What's in the board minutes?" (should be refused).

## Roadmap

- FastAPI service with SSO-derived identity instead of a CLI `--role` flag
- Postgres checkpointer and pgvector (or managed search) with permission-aware filtering
- Approval UI (web, Slack or Teams) and an immutable audit store
- Real integrations (ERP, CRM, n8n / Make) exposed as tools
- Evaluations for groundedness and permission leakage, tracing with Langfuse or LangSmith
