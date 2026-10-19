"""FastAPI service. Identity and role come ONLY from the validated bearer token, never from the request body.

Run:  uv run uvicorn api:app --reload
Serves the lightweight frontend from ./web at "/".
"""
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from openai import AuthenticationError, OpenAI, OpenAIError
from pydantic import BaseModel, Field

import auth
from company_brain import MODEL, ROLE_PERMISSIONS, Brain

MAX_MESSAGES_PER_SESSION = 60
app = FastAPI(title="Company Brain", docs_url="/api/docs", openapi_url="/api/openapi.json")


class Session:
    """Server-side state for one signed-in user. The API key lives only here, in memory."""

    def __init__(self, claims: dict):
        self.claims = claims
        self.brain: Brain | None = None
        self.messages = 0
        self.pending_approval = False
        self.lock = threading.Lock()


SESSIONS: dict[str, Session] = {}  # keyed by token jti


def current_session(authorization: str = Header(default="")) -> Session:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        claims = auth.verify_token(authorization[7:])
    except auth.AuthError as e:
        raise HTTPException(401, f"invalid token: {e}")
    return SESSIONS.setdefault(claims["jti"], Session(claims))


def require_brain(s: Session = Depends(current_session)) -> Session:
    if s.brain is None:
        raise HTTPException(409, "connect an OpenAI key first")
    return s


# -- auth (mock Entra) -------------------------------------------------------- #
class LoginBody(BaseModel):
    user_id: str


@app.get("/api/health")
def health():
    return {"ok": True, "model": MODEL}


@app.get("/api/users")
def users():
    return [{"id": k, **{f: v[f] for f in ("name", "upn", "title")}} for k, v in auth.DEMO_USERS.items()]


@app.post("/auth/login")
def login(body: LoginBody):
    try:
        token = auth.issue_token(body.user_id)
    except auth.AuthError as e:
        raise HTTPException(404, str(e))
    return {"access_token": token, "token_type": "Bearer"}


# -- session ------------------------------------------------------------------ #
@app.get("/api/me")
def me(s: Session = Depends(current_session)):
    c = s.claims
    return {"name": c["name"], "upn": c["preferred_username"], "role": c["role"], "app_roles": c["roles"],
            "capabilities": sorted(ROLE_PERMISSIONS[c["role"]]), "connected": s.brain is not None}


class KeyBody(BaseModel):
    api_key: str = Field(min_length=20, max_length=300)


@app.post("/api/key")
def connect_key(body: KeyBody, s: Session = Depends(current_session)):
    key = body.api_key.strip()
    try:
        OpenAI(api_key=key).models.list()  # free call; rejects invalid keys
    except AuthenticationError:
        raise HTTPException(400, "OpenAI rejected that key")
    except OpenAIError:
        raise HTTPException(502, "could not reach OpenAI to validate the key")
    s.brain = Brain(key, s.claims["sub"], s.claims["role"])
    s.messages, s.pending_approval = 0, False
    return {"connected": True}


# -- chat --------------------------------------------------------------------- #
class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ApproveBody(BaseModel):
    approved: bool


def run(s: Session, fn, *args) -> dict:
    with s.lock:  # one in-flight request per session
        try:
            out = fn(*args)
        except OpenAIError as e:
            raise HTTPException(502, f"OpenAI error: {type(e).__name__}")
        s.pending_approval = out["type"] == "approval"
        return out


@app.post("/api/chat")
def chat(body: ChatBody, s: Session = Depends(require_brain)):
    if s.pending_approval:
        raise HTTPException(409, "an approval is pending; approve or reject it first")
    if s.messages >= MAX_MESSAGES_PER_SESSION:
        raise HTTPException(429, "message limit reached for this session")
    s.messages += 1
    return run(s, s.brain.ask, body.message)


@app.post("/api/approve")
def approve(body: ApproveBody, s: Session = Depends(require_brain)):
    if not s.pending_approval:
        raise HTTPException(409, "nothing is awaiting approval")
    return run(s, s.brain.resume, body.approved)


@app.get("/api/audit")
def audit_trail(s: Session = Depends(require_brain)):
    return s.brain.events[-100:]


@app.post("/api/logout")
def logout(s: Session = Depends(current_session)):
    SESSIONS.pop(s.claims["jti"], None)  # drops the Brain and with it the API key
    return {"ok": True}


app.mount("/", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="web")
