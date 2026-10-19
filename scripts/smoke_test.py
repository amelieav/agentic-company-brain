"""Offline smoke test: stubs the LLM so graph wiring, RBAC and the approval flow can be checked without a key."""
import os
import sys
from pathlib import Path

os.environ.setdefault("OPENAI_API_KEY", "sk-test")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import company_brain as cb
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command


class FakeLLM:
    def invoke(self, messages):
        return AIMessage("SYNTH: " + messages[-1].content.replace("\n", " | ")[-200:])


class FakeAgent:
    def invoke(self, payload):
        return {"messages": [AIMessage("fake analytics answer")]}


cb.llm = FakeLLM()
cb.build_analytics_agent = FakeAgent
cb.planner = lambda state: {
    "results": "RESET",
    "actions": [{"automation": "send_payment_reminder", "target": "Nimbus Vending"}],
    "tasks": [{"agent": "analytics", "request": "x"}, {"agent": "action", "request": "y"}],
}

docs = cb.load_docs()
assert {d.metadata["min_role"] for d in docs} == {"staff", "manager", "exec"}, "role tags missing"

for role in ("staff", "manager"):
    g = cb.build_graph()
    cfg = {"configurable": {"thread_id": role}}
    r = g.invoke({"messages": [HumanMessage("hi")], "user_id": "u", "role": role}, cfg)
    if "__interrupt__" in r:
        print(role, "INTERRUPT:", r["__interrupt__"][0].value)
        r = g.invoke(Command(resume=True), cfg)
    print(role, "->", r["messages"][-1].content)
