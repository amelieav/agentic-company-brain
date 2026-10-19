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

## Run

```bash
uv sync
cp .env.example .env        # add OPENAI_API_KEY
uv run python company_brain.py --role manager
```

Offline wiring check (no API key needed): `uv run python scripts/smoke_test.py`.
Regenerate the fake data: `uv run python scripts/make_data.py`.

Try as `manager`: "Which accounts are over 60 days overdue, and send Nimbus Vending a payment reminder."
Try as `staff`: "What's in the board minutes?" (should be refused).

## Roadmap

- FastAPI service with SSO-derived identity instead of a CLI `--role` flag
- Postgres checkpointer and pgvector (or managed search) with permission-aware filtering
- Approval UI (web, Slack or Teams) and an immutable audit store
- Real integrations (ERP, CRM, n8n / Make) exposed as tools
- Evaluations for groundedness and permission leakage, tracing with Langfuse or LangSmith
