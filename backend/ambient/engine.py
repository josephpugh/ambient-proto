"""The loop: what the model is shown, how it answers, and how its proposals are applied and validated.

This is the notebook's sections 6 to 10 turned into an async generator that yields UI events
instead of printing. One call to `run_turn` runs the whole bounded loop for one batch of
transcript. The summary of the new snippet runs in a worker thread alongside the first model
call and is always the first event out.

Events yielded (plain dicts, each with a "kind"):
  summary          {text, turn}
  flow_activated   {flow, title, rationale}
  fields           {flow, title, iteration, accepted[] (each with new / changed), rejected[], required[] (each with why and hint), complete}
  supporting       {flow, choices{field: [{value,label}]}, notes[]}
  turn_done        {turn, iterations, changed}
  artifact         {flow, record}      the full record of a flow, re-emitted whenever it changes
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any, AsyncIterator

from .flows import FLOWS, Flow, Result, Values, coerce

MODEL = os.getenv("MODEL", "gpt-6-luna")
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", MODEL)
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "5"))


# ---------------------------------------------------------------- state

@dataclass
class FlowState:
    flow: Flow
    rationale: str
    values: Values = field(default_factory=dict)             # everything proposed so far, by field
    result: Result = field(default_factory=Result)
    rejected_history: dict[str, list[dict]] = field(default_factory=dict)   # field -> [{value, reason}]
    evidence: dict[str, str] = field(default_factory=dict)   # field -> transcript line it came from
    submitted: dict | None = None
    last_supporting: dict | None = None

    def revalidate(self) -> Result:
        self.result = self.flow.validate_inputs(self.values)
        return self.result

    def record(self) -> dict:
        """The data artifact the UI renders: resolved fields with sources, outstanding with reasons."""
        r = self.result
        f = self.flow
        status = "submitted" if self.submitted else "ready" if r.complete else "in_progress"
        return {
            "flow": f.name,
            "title": f.title,
            "status": status,
            "rationale": self.rationale,
            "resolved": [
                {"field": k, "label": f.field(k).label, "value": v, "display": f.display(k, v),
                 "evidence": self.evidence.get(k, "")}
                for k, v in r.accepted.items()
            ],
            "outstanding": [
                {"field": k, "label": f.field(k).label, "why": why, "hint": f.field(k).hint,
                 "last_rejection": (self.rejected_history[k][-1] if k in self.rejected_history else None)}
                for k, why in r.missing.items()
            ],
            "rejected": [
                {"field": k, "label": f.field(k).label, "reason": why} for k, why in r.rejected.items()
            ],
            "rejected_history": self.rejected_history,
            "submitted": self.submitted,
        }


@dataclass
class Session:
    context_id: str
    transcript: str = ""
    turn: int = 0
    active: dict[str, FlowState] = field(default_factory=dict)


# ---------------------------------------------------------------- what the model is shown

def catalogue_json(active: dict[str, FlowState]) -> dict:
    return {
        "available_flows": [
            {"name": f.name, "description": f.description}
            for f in FLOWS.values() if f.name not in active
        ],
        "active_flows": [
            {
                "name": st.flow.name,
                "resolved": [
                    {"field": name, "type": st.flow.field(name).type_name(),
                     "descriptor": st.flow.field(name).descriptor, "value": value}
                    for name, value in st.result.accepted.items()
                ],
                "outstanding": [
                    {"field": name, "type": st.flow.field(name).type_name(),
                     "descriptor": st.flow.field(name).descriptor, "why": why}
                    for name, why in st.result.missing.items()
                ],
                "rejected_previously": [
                    {"field": name, "type": st.flow.field(name).type_name(),
                     "descriptor": st.flow.field(name).descriptor, "attempts": attempts}
                    for name, attempts in st.rejected_history.items()
                ],
            }
            for st in active.values() if not st.submitted
        ],
    }


RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "activate": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"flow": {"type": "string"}, "rationale": {"type": "string"}},
                "required": ["flow", "rationale"],
            },
        },
        "values": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "flow": {"type": "string"},
                    "field": {"type": "string"},
                    "value": {"type": "string", "description": "The value as a string. Lists as JSON arrays. Booleans as true/false."},
                    "evidence": {"type": "string", "description": "The transcript line this came from."},
                },
                "required": ["flow", "field", "value", "evidence"],
            },
        },
    },
    "required": ["activate", "values"],
}

INSTRUCTIONS = '''You read a transcript of a call between a branch user (advisor) and a client and help a
form-filling application. You never decide whether a value is valid; the application does that.

Two jobs:
1. If the transcript shows the client asking for something that matches an AVAILABLE flow's description,
   list it under "activate" with a one-line rationale quoting the transcript. Do not activate flows that are
   merely mentioned in passing. Never activate a flow that is already active.
2. For each ACTIVE flow, look at its outstanding fields and its previously rejected fields. If the transcript
   gives a value, return it under "values" with the transcript line as evidence. Follow each field's descriptor
   for how to express the value. For a previously rejected field, only propose a value that is different from
   the rejected attempts and that addresses the rejection reason. If the transcript does not give a value,
   leave the field out. Never guess.
3. Resolved fields can change. If a later line of the transcript clearly replaces a resolved value, for
   example the client corrects themselves ("actually make it five thousand") or the branch user overrides it,
   return the new value under "values" with that line as evidence, expressed per the field's descriptor. The
   latest statement in the transcript wins. Do not return a resolved field whose value has not changed.

Lines that begin "branch user:" are the branch user typing directly into the application during the call,
for example picking an option or confirming a procedure. Treat them as authoritative for the field they name.

Return only the JSON object.'''

SUMMARY_INSTRUCTIONS = '''You write a short note, one or two sentences, for a financial advisor about a snippet of their call with a
client that just happened. Past tense. Refer to the advisor as "you" and the client by first name. Summarise what
was said in the lines given, whoever said them. If only one party speaks, summarise that; never remark that the
other party did not speak or that something is missing. Do not assume or mention anything said earlier in the
call. No preamble, no bullet points, no quotation marks. Plain prose.'''


def build_prompt(transcript: str, active: dict[str, FlowState]) -> str:
    today = date.today().isoformat()
    return (
        f"TODAY: {today}\n\nFLOWS AND CURRENT STATE (JSON):\n" + json.dumps(catalogue_json(active), indent=2) +
        "\n\nTRANSCRIPT:\n" + transcript.strip()
    )


# ---------------------------------------------------------------- calling the model

_client = None


def client():
    """One OpenAI client for the process. OPENAI_API_KEY is required, OPENAI_BASE_URL optional."""
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI()   # reads OPENAI_API_KEY and OPENAI_BASE_URL; a missing key fails here, per call
    return _client


def call_model(prompt: str) -> dict:
    resp = client().responses.create(
        model=MODEL,
        instructions=INSTRUCTIONS,
        input=prompt,
        service_tier="fast",
        reasoning={"effort": "medium"},
        store=False,
        text={"format": {"type": "json_schema", "name": "flow_update", "schema": RESPONSE_SCHEMA, "strict": True}},
    )
    return json.loads(resp.output_text)


def summarise(snippet: str) -> str:
    """The note covers only the snippet just received, never what came before it."""
    resp = client().responses.create(
        model=SUMMARY_MODEL,
        instructions=SUMMARY_INSTRUCTIONS,
        input=snippet.strip(),
        reasoning={"effort": "none"},
        service_tier="fast",
        store=False,
    )
    return resp.output_text.strip()




# ---------------------------------------------------------------- the loop, as events

def _fields_event(st: FlowState, iteration: int, before_accepted: Values, verdict_rejections: list[dict]) -> dict:
    r = st.result
    f = st.flow
    return {
        "kind": "fields",
        "flow": f.name,
        "title": f.title,
        "iteration": iteration,
        "accepted": [
            {"field": k, "label": f.field(k).label, "value": v, "display": f.display(k, v),
             "evidence": st.evidence.get(k, ""), "new": k not in before_accepted,
             "changed": k in before_accepted and before_accepted[k] != v}
            for k, v in r.accepted.items()
        ],
        "rejected": verdict_rejections,
        "required": [
            {"field": k, "label": f.field(k).label, "why": why, "hint": f.field(k).hint}
            for k, why in r.missing.items()
        ],
        "complete": r.complete,
    }


def _repeat_rejection(st: FlowState, field_name: str, value: Any, reason: str) -> bool:
    """True when the flow just turned down exactly what it turned down last time, for the same reason.

    The model is told not to re-propose a rejected attempt, but when the transcript offers nothing else it
    sometimes does. Judging the value again is right (a dependency may have changed); recording and
    reporting the identical verdict again is not, and it is not a change that warrants another iteration.
    """
    history = st.rejected_history.get(field_name)
    return bool(history) and history[-1]["value"] == value and history[-1]["reason"] == reason


async def run_turn(session: Session, new_text: str) -> AsyncIterator[dict]:
    """Append the snippet, summarise it in parallel, run the bounded loop, yield events as they happen."""
    session.transcript = (session.transcript.rstrip() + "\n" + new_text.strip()).strip()
    session.turn += 1
    turn = session.turn
    active = session.active

    # Summary runs in a worker thread alongside the first model call. It is emitted before any loop output.
    summary_task = asyncio.create_task(asyncio.to_thread(summarise, new_text))
    summary_emitted = False

    async def summary_event() -> dict:
        try:
            text = await summary_task
        except Exception as exc:  # noqa: BLE001
            text = f"Summary unavailable ({type(exc).__name__})."
        return {"kind": "summary", "text": text, "turn": turn}

    iterations = 0
    turn_changed = False
    error: str | None = None
    for iteration in range(1, MAX_ITERATIONS + 1):
        iterations = iteration
        prompt = build_prompt(session.transcript, active)
        try:
            reply = await asyncio.to_thread(call_model, prompt)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            break

        if not summary_emitted:
            yield await summary_event()
            summary_emitted = True


        changed = False

        # (3) Activate suggested flows. Validating with no values yields the full list of required fields.
        for a in reply.get("activate", []):
            name = a["flow"]
            if name in FLOWS and name not in active:
                st = FlowState(flow=FLOWS[name], rationale=a["rationale"])
                st.revalidate()
                active[name] = st
                changed = True
                yield {"kind": "flow_activated", "flow": name, "title": st.flow.title, "rationale": a["rationale"]}
                yield _fields_event(st, iteration, {}, [])
                sup = st.flow.supporting(st.result)
                if sup != st.last_supporting and (sup["choices"] or sup["notes"]):
                    st.last_supporting = sup
                    yield {"kind": "supporting", "flow": name, **sup}
                yield {"kind": "artifact", "flow": name, "record": st.record()}

        # (5) Apply proposed values to their flow, then revalidate that flow.
        touched: set[str] = set()
        rejections: dict[str, list[dict]] = {}
        for v in reply.get("values", []):
            st = active.get(v["flow"])
            if not st or st.submitted or not st.flow.has_field(v["field"]):
                continue
            f = st.flow.field(v["field"])
            value, err = coerce(f, v["value"])
            if err:
                if _repeat_rejection(st, f.name, v["value"], err):
                    continue
                st.rejected_history.setdefault(f.name, []).append({"value": v["value"], "reason": err})
                rejections.setdefault(st.flow.name, []).append({"field": f.name, "label": f.label, "value": v["value"], "reason": err})
                changed = True
                continue
            if st.values.get(f.name) != value:
                st.values[f.name] = value
                st.evidence[f.name] = v.get("evidence", "")
                touched.add(st.flow.name)

        for name in touched:
            st = active[name]
            before = (dict(st.result.accepted), dict(st.result.missing), dict(st.result.rejected))
            st.revalidate()
            for fname, reason in st.result.rejected.items():
                bad = st.values[fname]
                if not _repeat_rejection(st, fname, bad, reason):
                    st.rejected_history.setdefault(fname, []).append({"value": bad, "reason": reason})
                    rejections.setdefault(name, []).append({"field": fname, "label": st.flow.field(fname).label,
                                                            "value": bad, "reason": reason})
                del st.values[fname]
                st.evidence.pop(fname, None)
            st.revalidate()
            after = (dict(st.result.accepted), dict(st.result.missing), dict(st.result.rejected))
            if before != after or rejections.get(name):
                changed = True
                yield _fields_event(st, iteration, before[0], rejections.get(name, []))
                sup = st.flow.supporting(st.result)
                if sup != st.last_supporting:
                    st.last_supporting = sup
                    yield {"kind": "supporting", "flow": name, **sup}
                yield {"kind": "artifact", "flow": name, "record": st.record()}

        # Coercion failures on flows that were not otherwise touched still need reporting.
        for name, rej in rejections.items():
            if name not in touched:
                st = active[name]
                yield _fields_event(st, iteration, dict(st.result.accepted), rej)

        turn_changed |= changed
        # (6) Stop when nothing changed.
        if not changed:
            break

    if not summary_emitted:
        yield await summary_event()
    if error:
        yield {"kind": "error", "text": error}

    yield {"kind": "turn_done", "turn": turn, "iterations": iterations, "changed": turn_changed,
           "flows": {n: st.record()["status"] for n, st in active.items()}}


def submit_flow(session: Session, flow_name: str) -> dict:
    """The branch user's instruction to execute. Only valid when the flow's record is complete."""
    st = session.active.get(flow_name)
    if not st:
        return {"kind": "error", "text": f"No active flow named {flow_name}."}
    if st.submitted:
        return {"kind": "submitted", "flow": flow_name, "title": st.flow.title, **st.submitted, "already": True}
    if not st.result.complete:
        return {"kind": "error", "flow": flow_name, "text": "The flow still has outstanding fields."}
    st.submitted = st.flow.submit(st.result.accepted)
    return {"kind": "submitted", "flow": flow_name, "title": st.flow.title, **st.submitted}
