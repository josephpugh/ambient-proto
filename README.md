# Ambient assistant for branch calls, prototype

One project, two halves:

- `backend/` Python. The flow loop from the notebook (two flows, deterministic validation, a stand-in for the
  BAM tools) behind an A2A interface with an agent card that advertises the flows as skills.
- `frontend/` React (Vite). The sidebar from the design: 380px wide by default, full height, docked right,
  resizable by dragging its left edge. It speaks A2A directly to the backend.

## Run it

Backend (Python 3.11 or later). The start script creates a virtual environment the first time and uses it after that:

    cd backend
    ./start.sh                           # Windows: .\start.ps1
    # first run: creates .venv, installs requirements.txt, copies .env.example to .env
    # put OPENAI_API_KEY in backend/.env (and OPENAI_BASE_URL if you go through a gateway)
    # then serves on http://127.0.0.1:9999

Or by hand, if you prefer to manage the environment yourself:

    cd backend
    python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    python -m ambient

`python -m ambient` runs wherever it is launched. It reads `backend/.env` at startup without overriding variables
already set in the shell, prints whether it is in a virtual environment, and notes if `OPENAI_API_KEY` is missing.
Nothing stops it starting: a missing or bad key makes the model call fail on the first turn, and that failure is
streamed to the UI as an error event.

Frontend, either in development with hot reload:

    cd frontend
    npm install
    npm run dev                          # http://localhost:5173, proxies /a2a and the agent card to :9999

or built once and served by the backend:

    cd frontend && npm install && npm run build
    python -m ambient                    # now also serves the UI at http://127.0.0.1:9999/

Paste a transcript into the box at the bottom, one line per speaker (`advisor:` and `client:`), exactly as in
the notebook. Send with the button or Enter; Shift+Enter inserts a newline. The box grows with the text up to about six lines, then scrolls.

## What happens on a turn

1. The UI sends the snippet as an A2A `SendStreamingMessage`. The first message carries no ids, and the server
   mints a `contextId` and a `taskId` and returns the Task. Every later message carries both, and the backend
   appends the snippet to the transcript it holds for that context and runs the whole loop again.
2. The backend kicks off a summary request to the model in a worker thread and, in parallel, the first call
   of the loop. The summary is always the first update out, before anything the loop produced.
3. The loop runs the notebook's steps: the model proposes which flows to activate and which outstanding
   fields it can fill; the flow's `validate_inputs` judges every value; the loop repeats until nothing changes
   or five iterations have run. Each change is streamed as it happens.
4. The task stops at `INPUT_REQUIRED`. The UI treats the end of the stream as the end of the turn and only
   then unlocks the input box.
5. When a flow's record is complete the UI shows the review card with every resolved input, its evidence
   line from the transcript, and a Confirm button. Confirm sends a data part `{"action":"confirm","flow":...}`
   on the same task. The backend submits through the stand-in BAM and returns a reference.

## The A2A shapes the UI reads

All updates are `TaskStatusUpdateEvent`s in state `WORKING` whose message carries one data part with a `kind`:

| kind             | fields                                                                                 |
|------------------|----------------------------------------------------------------------------------------|
| `summary`        | `text`, `turn`                                                                         |
| `flow_activated` | `flow`, `title`, `rationale`                                                           |
| `fields`         | `flow`, `title`, `iteration`, `accepted[]` (with `new`, `changed`, `display`, `evidence`), `rejected[]` (with `reason`), `required[]` (with `hint`), `complete` |
| `supporting`     | `flow`, `choices{field: [{value,label}]}`, `notes[]`                                   |
| `submitted`      | `flow`, `title`, `reference`, `summary`                                                |
| `error`          | `text`                                                                                 |

The full record of each flow is a data artifact named after the flow (`artifactId` = `flow-<name>`), re-emitted
whenever it changes: `status` (`in_progress`, `ready`, `submitted`), `resolved[]`, `outstanding[]`, `rejected[]`,
`rejected_history`, `submitted`. The final status update of each turn is `INPUT_REQUIRED` and carries a
`turn_done` data part with the status of every flow.

Choice chips in the UI send a transcript line of the form `branch user: <label> = <value>`. The model is told
that such lines are the branch user typing into the application and are authoritative for that field.

## Layout of the code

    backend/ambient/flows.py       Field, Result, Flow, FakeBAM, OrderCheck, UpdateMailingAddress, coerce
    backend/ambient/engine.py      FlowState, Session, prompt and schema, model calls, run_turn, submit_flow
    backend/ambient/a2a_server.py  agent card, AmbientExecutor, create_app (JSON-RPC at /a2a, card at /.well-known/agent-card.json)
    backend/start.sh, start.ps1    start inside .venv, creating it and installing requirements the first time
    backend/examples/client.py     a terminal client that streams a turn, a follow-up and a confirm
    frontend/src/a2a.js            SendStreamingMessage over SSE, and interpret() to pull events out of each result
    frontend/src/state.js          the reducer: how each event changes the feed and the flow records
    frontend/src/components/       Sidebar (frame, resize, run loop), Header, ClientBar, Feed (heard, activity, review), FlowCard, Composer
