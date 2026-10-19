"""Company Brain PoC: supervisor + specialist agents on LangGraph.

Covers: multi-intent routing, specialist agents (analytics / knowledge-RAG),
human-in-the-loop approval for actions, role-based permissions, audit trail,
and persistent conversation memory (checkpointer).

Run:  uv run python company_brain.py --role manager
"""
import argparse
import csv
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Annotated, Literal, Optional, TypedDict

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.types import Command, Send, interrupt
from pydantic import BaseModel, Field
from pypdf import PdfReader

load_dotenv()

# Cheapest OpenAI chat model at time of writing; override in .env if pricing changes.
MODEL = os.getenv("OPENAI_MODEL", "gpt-5-nano")
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
llm = ChatOpenAI(model=MODEL)

# --------------------------------------------------------------------------- #
# Governance: RBAC + audit trail
# --------------------------------------------------------------------------- #
ROLE_PERMISSIONS = {
    "staff": {"knowledge"},
    "manager": {"knowledge", "analytics", "action"},
    "exec": {"knowledge", "analytics", "action"},
}
RANK = {"staff": 0, "manager": 1, "exec": 2}
AUDIT_FILE = "audit.jsonl"


def audit(event: str, **fields) -> None:
    """Append-only audit log (swap for CloudWatch / immutable store in prod)."""
    with open(AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "event": event, **fields}) + "\n")


# --------------------------------------------------------------------------- #
# Mock enterprise systems (stand-ins for ERP / CRM / n8n webhooks)
# --------------------------------------------------------------------------- #
DATA_DIR = Path(__file__).parent / "data"
DOCS_DIR = Path(__file__).parent / "docs"

AUTOMATIONS = {  # existing workflows we *connect to*, not rebuild
    "send_payment_reminder": "ERP: email payment reminder to a customer",
    "create_crm_followup": "CRM: create a follow-up task for an account",
}


def read_csv(name: str) -> list[dict]:
    with open(DATA_DIR / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# --------------------------------------------------------------------------- #
# Knowledge base: markdown (front-matter `min_role:`) + PDFs -> role-tagged chunks
# --------------------------------------------------------------------------- #
PDF_MIN_ROLE = {"board-minutes-q3.pdf": "exec", "qa-audit-report-sep.pdf": "manager",
                "allergen-matrix.pdf": "staff"}  # unlisted PDFs default to exec (deny by default)


def load_docs() -> list[Document]:
    raw: list[Document] = []
    for path in sorted(DOCS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta = dict(re.findall(r"^(\w+):\s*(.+)$", text.split("---")[1], re.M))
        raw.append(Document(page_content=text.split("---", 2)[2].strip(),
                            metadata={"source": meta.get("source", path.name),
                                      "min_role": meta.get("min_role", "exec")}))
    for path in sorted(DOCS_DIR.glob("*.pdf")):
        body = "\n".join(pg.extract_text() or "" for pg in PdfReader(path).pages)
        raw.append(Document(page_content=body, metadata={"source": f"pdf/{path.name}",
                                                         "min_role": PDF_MIN_ROLE.get(path.name, "exec")}))
    return RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=80).split_documents(raw)


_store: Optional[InMemoryVectorStore] = None


def get_store() -> InMemoryVectorStore:
    global _store
    if _store is None:
        _store = InMemoryVectorStore(OpenAIEmbeddings(model=EMBED_MODEL))
        _store.add_documents(load_docs())
    return _store


# --------------------------------------------------------------------------- #
# Specialist agents (built per-request so tools can enforce the caller's role)
# --------------------------------------------------------------------------- #
def build_analytics_agent():
    @tool
    def get_sales_summary(region: str = "", month: str = "") -> dict:
        """Boxes, revenue and variance vs target. Optional filters: region (north, south, midlands, scotland), month (YYYY-MM)."""
        rows = [r for r in read_csv("sales.csv")
                if (not region or r["region"] == region.lower()) and (not month or r["month"] == month)]
        rev, tgt = sum(float(r["revenue"]) for r in rows), sum(float(r["target_revenue"]) for r in rows)
        return {"rows": len(rows), "boxes": sum(int(r["boxes"]) for r in rows), "revenue": round(rev, 2),
                "target": round(tgt, 2), "vs_target_pct": round((rev / tgt - 1) * 100, 1) if tgt else None}

    @tool
    def get_overdue_invoices(min_days: int = 1) -> list:
        """Open invoices at least `min_days` overdue (customer, amount, days_overdue)."""
        return [r for r in read_csv("invoices.csv") if r["status"] == "open" and int(r["days_overdue"]) >= min_days]

    @tool
    def get_costs(category: str = "", month: str = "") -> dict:
        """Total costs. Optional filters: category (spirulina extract, sherbet crystals, butter & dairy, packaging, labour, energy), month (YYYY-MM)."""
        rows = [r for r in read_csv("costs.csv")
                if (not category or r["category"] == category.lower()) and (not month or r["month"] == month)]
        return {"rows": len(rows), "total": round(sum(float(r["amount"]) for r in rows), 2)}

    return create_agent(llm, [get_sales_summary, get_overdue_invoices, get_costs],
                        system_prompt="You are the analytics agent. Use tools; never guess figures. Be concise.")


NO_RESULTS = "NO_ACCESSIBLE_RESULTS"


def build_knowledge_agent(role: str):
    @tool
    def search_company_docs(query: str) -> str:
        """Semantic search over internal policies, SOPs and reports."""
        # Over-fetch, then filter by role, so restricted chunks don't crowd out allowed ones.
        hits = get_store().similarity_search(query, k=12)
        allowed = [d for d in hits if RANK[role] >= RANK[d.metadata["min_role"]]][:4]
        audit("rag_retrieval", role=role, query=query, sources=[d.metadata["source"] for d in allowed])
        return "\n".join(f"[{d.metadata['source']}] {d.page_content}" for d in allowed) or NO_RESULTS

    return create_agent(
        llm, [search_company_docs],
        system_prompt=("You are the knowledge agent for Moonpool Bakehouse. Answer ONLY from text returned by "
                       f"search_company_docs and cite the [source]. If the tool returns {NO_RESULTS} or nothing "
                       "relevant, reply exactly: \"I don't have accessible documents on that.\" "
                       "Never use general knowledge."))


# --------------------------------------------------------------------------- #
# Graph state + planner schema
# --------------------------------------------------------------------------- #
def collect(old: list, new) -> list:
    """Reducer: append results from parallel branches; the string 'RESET' clears per turn."""
    return [] if new == "RESET" else old + new


class ActionCall(BaseModel):
    automation: Literal["send_payment_reminder", "create_crm_followup"]
    target: str = Field(description="Customer/account name the automation applies to")


class Task(BaseModel):
    agent: Literal["analytics", "knowledge", "action"]
    request: str = Field(description="Self-contained sub-request for that agent")
    action: Optional[ActionCall] = Field(None, description="Only when agent == 'action'")


class Plan(BaseModel):
    tasks: list[Task] = Field(description="One entry per distinct intent in the user's message")


class State(TypedDict):
    messages: Annotated[list, add_messages]   # persistent memory via checkpointer
    user_id: str
    role: str
    tasks: list[dict]
    actions: list[dict]
    results: Annotated[list, collect]


PLANNER_PROMPT = f"""You route requests for an internal business assistant at Moonpool Bakehouse (maker of Blue Sherbet cookies).
Split the user's latest message into independent tasks (multi-intent).
- analytics: sales, costs, overdue invoices (ERP data)
- knowledge: policies, SOPs, reports, how-to questions
- action: the user asks to DO something. Available automations: {json.dumps(AUTOMATIONS)}
Keep each request close to the user's own wording; do not add topics they didn't ask about.
Use earlier conversation to resolve references like "them" or "that customer"."""


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
def planner(state: State) -> dict:
    plan = llm.with_structured_output(Plan).invoke([SystemMessage(PLANNER_PROMPT), *state["messages"][-8:]])
    audit("plan", user=state["user_id"], role=state["role"], tasks=[t.model_dump() for t in plan.tasks])
    return {
        "results": "RESET",
        "actions": [t.action.model_dump() for t in plan.tasks if t.agent == "action" and t.action],
        "tasks": [t.model_dump() for t in plan.tasks],
    }


def dispatch(state: State) -> list[Send]:
    """Fan out to the specialist nodes that have work (parallel execution)."""
    by_agent: dict[str, list[str]] = {}
    for t in state["tasks"]:
        by_agent.setdefault(t["agent"], []).append(t["request"])
    sends = []
    for agent, reqs in by_agent.items():
        if agent not in ROLE_PERMISSIONS[state["role"]]:
            audit("denied", user=state["user_id"], role=state["role"], agent=agent)
            sends.append(Send("denied", {"agent": agent}))
        elif agent != "action":  # action node is routed separately (it needs full state)
            sends.append(Send(agent, {"requests": reqs, "role": state["role"]}))
    if not sends and not (state["actions"] and "action" in ROLE_PERMISSIONS[state["role"]]):
        sends.append(Send("synthesise_only", {}))
    return sends


def run_agent(agent, requests: list[str]) -> str:
    out = agent.invoke({"messages": [HumanMessage(" ; ".join(requests))]})
    return out["messages"][-1].content


def analytics_node(p: dict) -> dict:
    return {"results": [{"agent": "analytics", "answer": run_agent(build_analytics_agent(), p["requests"])}]}


def knowledge_node(p: dict) -> dict:
    return {"results": [{"agent": "knowledge", "answer": run_agent(build_knowledge_agent(p["role"]), p["requests"])}]}


def denied_node(p: dict) -> dict:
    return {"results": [{"agent": p["agent"], "answer": f"Permission denied: your role cannot use the '{p['agent']}' capability."}]}


def action_node(state: State) -> dict:
    """Human-in-the-loop: nothing with side effects runs without explicit approval.

    No LLM calls here: on resume LangGraph re-runs this node from the top, so the
    approved payload must be deterministic and identical to what the human saw.
    """
    done = []
    for a in state["actions"]:
        approved = interrupt({"type": "approval_request", "automation": a["automation"],
                              "target": a["target"], "description": AUTOMATIONS[a["automation"]]})
        audit("approval", user=state["user_id"], action=a, approved=bool(approved))
        if approved:
            # real implementation: POST to n8n / Make webhook or ERP API with idempotency key
            run_id = uuid.uuid4().hex[:8]
            audit("action_executed", user=state["user_id"], action=a, run_id=run_id)
            done.append({"agent": "action", "answer": f"Executed {a['automation']} for {a['target']} (run {run_id})."})
        else:
            done.append({"agent": "action", "answer": f"Rejected: {a['automation']} for {a['target']} was not run."})
    return {"results": done}


def synthesise(state: State) -> dict:
    if not state["results"]:
        return {"messages": [AIMessage("I couldn't identify a task in that request.")]}
    findings = "\n".join(f"- ({r['agent']}) {r['answer']}" for r in state["results"])
    last_user = [m for m in state["messages"] if isinstance(m, HumanMessage)][-1].content
    reply = llm.invoke([
        SystemMessage("Combine the specialist findings into one clear answer for a busy executive. "
                      "Use ONLY the findings; do not add outside knowledge or claim sources that aren't listed. "
                      "If a finding says documents are unavailable, say so plainly."),
        HumanMessage(f"Question: {last_user}\n\nFindings:\n{findings}"),
    ])
    audit("response", user=state["user_id"])
    return {"messages": [reply]}


# --------------------------------------------------------------------------- #
# Graph assembly
# --------------------------------------------------------------------------- #
def build_graph():
    g = StateGraph(State)
    g.add_node("planner", planner)
    g.add_node("analytics", analytics_node)
    g.add_node("knowledge", knowledge_node)
    g.add_node("denied", denied_node)
    g.add_node("synthesise", synthesise)
    g.add_node("synthesise_only", lambda s: {})
    g.add_node("action", action_node)
    g.add_edge(START, "planner")
    g.add_conditional_edges("planner", dispatch, ["analytics", "knowledge", "denied", "synthesise_only"])
    # The action node reads state["actions"], so route it from the planner too.
    g.add_conditional_edges(
        "planner",
        lambda s: ["action"] if s["actions"] and "action" in ROLE_PERMISSIONS[s["role"]] else [],
        ["action"])
    for n in ("analytics", "knowledge", "denied", "action", "synthesise_only"):
        g.add_edge(n, "synthesise")
    g.add_edge("synthesise", END)
    return g.compile(checkpointer=InMemorySaver())


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def chat(graph, user_id: str, role: str) -> None:
    config = {"configurable": {"thread_id": f"{user_id}-session"}}
    print(f"Company Brain PoC | model={MODEL} | role={role}  (Ctrl-C to quit)")
    while True:
        text = input("\nyou> ").strip()
        if not text:
            continue
        payload = {"messages": [HumanMessage(text)], "user_id": user_id, "role": role}
        result = graph.invoke(payload, config)
        while "__interrupt__" in result:
            req = result["__interrupt__"][0].value
            ans = input(f"\n[APPROVAL] {req['description']} -> {req['target']}. Approve? (y/n) ").lower() == "y"
            result = graph.invoke(Command(resume=ans), config)
        print("\nbrain>", result["messages"][-1].content)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", choices=list(ROLE_PERMISSIONS), default="manager")
    ap.add_argument("--user", default="amelie")
    args = ap.parse_args()
    chat(build_graph(), args.user, args.role)
