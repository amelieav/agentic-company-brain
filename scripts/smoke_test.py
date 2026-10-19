"""Offline smoke test: stubs the LLM so graph wiring, RBAC and the approval flow can be checked without a key."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["AUDIT_FILE"] = str(Path(tempfile.gettempdir()) / "company_brain_smoke_audit.jsonl")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import company_brain as cb
from langchain_core.messages import AIMessage


class FakeLLM:
    def invoke(self, messages):
        return AIMessage("SYNTH: " + messages[-1].content.replace("\n", " | ")[-200:])


class FakeAgent:
    def invoke(self, payload):
        return {"messages": [AIMessage("fake analytics answer")]}


def make_brain(role: str) -> cb.Brain:
    b = cb.Brain("sk-test", "smoke", role)
    b.llm = FakeLLM()
    b._analytics_agent = FakeAgent
    b._planner = lambda state: {
        "results": "RESET",
        "actions": [{"automation": "send_payment_reminder", "target": "Nimbus Vending"}],
        "tasks": [{"agent": "analytics", "request": "x"}, {"agent": "action", "request": "y"}],
    }
    b.graph = b._build_graph()
    return b


if __name__ == "__main__":
    assert {d.metadata["min_role"] for d in cb.load_docs()} == {"staff", "manager", "exec"}, "role tags missing"
    for role in ("staff", "manager"):
        b = make_brain(role)
        out = b.ask("hi")
        if out["type"] == "approval":
            print(role, "APPROVAL:", out["request"])
            out = b.resume(True)
        print(role, "->", out["text"])
