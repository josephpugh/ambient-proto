"""A2A exposure: the agent card, the executor that runs the loop, and the Starlette app.

Protocol shape (one task per call context):
- First message: no contextId or taskId. The server mints both and returns a Task. The task
  goes WORKING, streams updates, then stops at INPUT_REQUIRED with the turn's results.
- Later messages: the client sends the same contextId and taskId. The snippet is appended to
  the transcript held for that context and the loop runs again on the whole transcript.
- Confirm: a message carrying a data part {"action": "confirm", "flow": "<name>"} instead of
  text. The server submits that flow (through the stand-in BAM) and reports the reference.

Every streamed update is a TaskStatusUpdateEvent in state WORKING whose message carries one
data part with a "kind" (summary, flow_activated, fields, supporting, submitted, error). The
record of each flow is a data artifact named after the flow, re-emitted with the same
artifactId whenever it changes. The UI renders from those two things and nothing else.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    Part,
    Task,
    TaskState,
    TaskStatus,
)
from google.protobuf.json_format import MessageToDict, ParseDict
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from .engine import Session, run_turn, submit_flow
from .flows import FLOWS

RPC_PATH = "/a2a"


def data_part(d: dict[str, Any]) -> Part:
    return ParseDict({"data": d}, Part())


def build_agent_card(public_url: str) -> AgentCard:
    return AgentCard(
        name="Ambient assistant for branch calls",
        description=(
            "Listens to a transcript of a branch call, recognises which supported flows the client is asking for, "
            "captures each flow's inputs from what was said, validates every value with the domain's own rules, "
            "and returns a reviewable record. It never submits anything itself."
        ),
        version="0.1.0",
        provider=AgentProvider(organization="Ambient assistant prototype", url=public_url),
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", protocol_version="1.0", url=public_url.rstrip("/") + RPC_PATH)],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text/plain", "application/json"],
        default_output_modes=["application/json", "text/plain"],
        skills=[
            AgentSkill(
                id=f.name,
                name=f.title,
                description=f.description,
                tags=["flow", "branch-call", f.name],
                examples=[f"Transcript lines in which the client asks to {f.title.lower()}."],
            )
            for f in FLOWS.values()
        ] + [
            AgentSkill(
                id="summarise_snippet",
                name="Summarise what was just heard",
                description="A two-sentence note on each transcript snippet received, for the branch user.",
                tags=["summary"],
            )
        ],
    )


class AmbientExecutor(AgentExecutor):
    def __init__(self, max_sessions: int = 500) -> None:
        self._sessions: dict[str, Session] = {}
        self._max_sessions = max_sessions

    def session(self, context_id: str) -> Session:
        s = self._sessions.get(context_id)
        if s is None:
            if len(self._sessions) >= self._max_sessions:
                self._sessions.pop(next(iter(self._sessions)))
            s = self._sessions[context_id] = Session(context_id=context_id)
        return s

    @staticmethod
    def action_part(context: RequestContext) -> dict | None:
        for p in context.message.parts:
            if p.HasField("data"):
                d = MessageToDict(p.data)
                if "action" in d:
                    return d
        return None

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        if context.current_task is None:
            await event_queue.enqueue_event(
                Task(id=context.task_id, context_id=context.context_id,
                     status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED), history=[context.message])
            )
        session = self.session(context.context_id)
        await updater.start_work()

        async def emit(kind_event: dict) -> None:
            await updater.update_status(TaskState.TASK_STATE_WORKING, updater.new_agent_message([data_part(kind_event)]))

        async def emit_artifact(flow: str, record: dict) -> None:
            await updater.add_artifact([data_part(record)], artifact_id=f"flow-{flow}", name=flow, last_chunk=True)

        try:
            action = self.action_part(context)
            if action and action.get("action") == "confirm":
                result = submit_flow(session, action.get("flow", ""))
                await emit(result)
                st = session.active.get(action.get("flow", ""))
                if st:
                    await emit_artifact(st.flow.name, st.record())
                done = {"kind": "turn_done", "turn": session.turn, "iterations": 0, "changed": True,
                        "flows": {n: s.record()["status"] for n, s in session.active.items()}}
            else:
                text = context.get_user_input().strip()
                if not text:
                    await emit({"kind": "error", "text": "The message carried no transcript text."})
                done = {"kind": "turn_done"}
                if text:
                    async for ev in run_turn(session, text):
                        if ev["kind"] == "artifact":
                            await emit_artifact(ev["flow"], ev["record"])
                        elif ev["kind"] == "turn_done":
                            done = ev
                        else:
                            await emit(ev)
            # The task stays open for the whole call: more transcript may arrive on the same task.
            await updater.requires_input(
                updater.new_agent_message([Part(text="Waiting for more of the conversation."), data_part(done)])
            )
        except Exception as exc:  # noqa: BLE001
            await updater.failed(updater.new_agent_message([Part(text=f"{type(exc).__name__}: {exc}")]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        self._sessions.pop(context.context_id, None)
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


def create_app(public_url: str | None = None) -> Starlette:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "9999"))
    public_url = public_url or os.getenv("PUBLIC_URL", f"http://{host}:{port}")
    card = build_agent_card(public_url)
    handler = DefaultRequestHandler(agent_executor=AmbientExecutor(), task_store=InMemoryTaskStore(), agent_card=card)
    routes = [*create_agent_card_routes(card), *create_jsonrpc_routes(handler, rpc_url=RPC_PATH)]
    dist = Path(os.getenv("FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
    if dist.is_dir():
        routes.append(Mount("/", app=StaticFiles(directory=str(dist), html=True), name="ui"))
    return Starlette(
        routes=routes,
        middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
    )
