# Ambient assistant for branch calls, prototype

One project, two halves:

- `backend/` Python. The flow loop from the notebook (the order check flow, deterministic validation, a stand-in
  for the BAM tools) behind an A2A interface with an agent card that advertises the flows as skills.
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
| `fields`         | `flow`, `title`, `iteration`, `accepted[]` (with `new`, `changed`, `display`, `evidence`), `rejected[]` (with `reason`), `required[]` (with `why` and `hint`), `complete` |
| `supporting`     | `flow`, `choices{field: [{value,label}]}`, `notes[]`                                   |
| `submitted`      | `flow`, `title`, `reference`, `summary`                                                |
| `error`          | `text`                                                                                 |

The full record of each flow is a data artifact named after the flow (`artifactId` = `flow-<name>`), re-emitted
whenever it changes: `status` (`in_progress`, `ready`, `submitted`), `resolved[]`, `outstanding[]`, `rejected[]`,
`rejected_history`, `submitted`. The final status update of each turn is `INPUT_REQUIRED` and carries a
`turn_done` data part with the status of every flow.

Choice chips in the UI send a transcript line of the form `branch user: <label> = <value>`. The model is told
that such lines are the branch user typing into the application and are authoritative for that field.

## Writing a flow

A flow is a class in `backend/ambient/flows.py` that extends `Flow` and is added to the `FLOWS` catalogue at the
bottom of that file. That is the whole registration: the agent card, the model's catalogue, the loop and the UI
all read from `FLOWS`. The one flow in the file, `OrderCheck`, is the reference for everything below.

A flow has four class attributes and three methods:

    class SetTravelNotice(Flow):
        name = "set_travel_notice"          # identifier; also the artifact id (flow-set_travel_notice)
        title = "Set a travel notice"       # what people see
        description = "..."                 # how the model recognises the request (see below)
        fields = [ ... ]                    # the schema: name, type, descriptor, label and hint of each input

        def validate(self, values: Values, r: Result) -> None: ...   # the rules: what is accepted, rejected, required
        def supporting(self, r: Result) -> dict: ...                 # optional: choices and notes for the branch user
        def submit(self, accepted: Values) -> dict: ...              # the irreversible action, on Confirm only

Everything else, including `validate_inputs`, `display`, `field` and `has_field`, is inherited and rarely
needs overriding.

### The description: how the model decides to activate the flow

The model sees every flow that is not yet active as `{name, description}` and activates one when the transcript
shows the client asking for it. The description is the only thing it has to go on, so write it as three parts:

1. What the client is asking for, in one sentence, from the client's point of view.
2. `Listen for:` the phrases a client actually uses. The model matches meaning, not the exact words, but
   concrete phrases anchor it.
3. `Not for:` the neighbouring request it should not be confused with, if there is one.

    description = ("The client asks for a check to be issued or sent from one of their accounts. "
                   "Listen for: 'send me a check', 'cut a check', 'I need a check for', an amount and an account. "
                   "Not for a transfer between accounts.")

The model is told not to activate flows that are merely mentioned in passing and never to activate one that is
already active. When it activates a flow it returns a rationale quoting the transcript; the UI shows that as the
"Identified ..." line in the feed.

### Fields: the schema

Each input is a `Field`. The schema says what an input is and how to describe it to the model and to people;
it holds no rules.

| argument     | read by   | what it does                                                                                        |
|--------------|-----------|-----------------------------------------------------------------------------------------------------|
| `name`       | code      | key in the record and in the model's reply                                                          |
| `type`       | code      | `str`, `float`, `bool` or `list`. The model returns strings; `coerce` converts them (see below)      |
| `descriptor` | the model | what the value is and how to express it. The model follows this; it never judges validity           |
| `label`      | people    | shown in the feed, the flow card and the review card. Defaults to the name with underscores as spaces |
| `hint`       | people    | the question to ask the client, shown next to the field while it is outstanding                     |

    Field("amount", float, "The check amount in dollars, as a number. 'five thousand' is 5000.",
          label="Amount", hint="How much is the check for?")

**Types and coercion.** The model always returns the value as a string, and `coerce` turns it into the field's
type before validation: a `float` has `$` and commas stripped; a `bool` is true for `true`, `yes`, `y` or `1`; a
`list` is parsed as a JSON array. Say in the descriptor how to express the value so the conversion succeeds, for
example "as a number", "as an ISO date (YYYY-MM-DD)", "as a list of account ids". A value of the wrong type after
coercion is rejected as "expected number" before the flow's rules see it.

**The descriptor** is the model's only guide to a field, so it should cover three things: what the value means,
how to format it, and how to resolve what the client actually says into it. The last part matters most: clients
say "the joint account", "the house", "five thousand", and the descriptor is where those are mapped to
`joint-4471`, the street address on file, and `5000`. The model is also told the descriptor of resolved fields,
so a later correction in the transcript ("actually make it five thousand") comes back in the same format.

### `validate`: the rules

`validate(values, r)` is where every rule lives: whether a value is acceptable, which fields depend on which,
and which fields are required under what conditions. It is called with every typed value proposed so far, all of
them at once, and records its verdicts on the `Result` with four calls:

| call                       | effect                                                                        |
|----------------------------|-------------------------------------------------------------------------------|
| `r.accept(name, value)`    | the value is good; it appears as resolved                                     |
| `r.reject(name, reason)`   | the value is turned down; the reason travels to the feed, the card and the model |
| `r.require(name)`          | the field is part of the record and still outstanding ("not provided")        |
| `r.defer(name, *until)`    | a value was given but cannot be judged until the named fields are accepted    |

A field that `validate` says nothing about is invisible: not outstanding, not asked for, not shown. The flow is
complete when nothing is rejected and nothing is required. The shape of the method is one block per field, in
dependency order, each reading what the blocks above it accepted:

    def validate(self, v: Values, r: Result) -> None:
        if "account" not in v:
            r.require("account")
        elif not bam.is_client_account(v["account"]):
            r.reject("account", "not one of the client's accounts")
        else:
            r.accept("account", v["account"])
        account = r.accepted.get("account")

        if "amount" not in v:
            r.require("amount")
        elif account is None:
            r.defer("amount", "account")
        elif v["amount"] > bam.balance(account):
            r.reject("amount", f"exceeds available balance of {bam.balance(account):,.2f}")
        else:
            r.accept("amount", v["amount"])
        ...

**Dependencies.** A rule that needs another field's value reads it from `r.accepted`, and defers when it is not
there yet: the check amount is checked against the balance of the account that was accepted, and until the
account is valid the amount is reported as "cannot be checked until account is valid" rather than rejected. The
whole set of proposed values is judged again after every change, so when a dependency changes, everything that
reads it is re-judged automatically.

**Conditional fields.** A field that only applies in some situations is simply not mentioned until the situation
holds. The large-check verification is required only once the amount is accepted and at or above $10,000:

    amount = r.accepted.get("amount")
    if "verification_confirmed" in v:
        ...judge it...
    elif amount is not None and amount >= LARGE_CHECK:
        r.require("verification_confirmed")

Any condition code can express works the same way: a limit from the system of record, a combination of accepted
values, a lookup. Nothing about it is declared in the schema.

### Validation reasons: what the string you return is used for

The reason given to `r.reject` travels a long way, so write it as a sentence that says what would be acceptable,
not just that the value is wrong:

- The feed shows it as a "Rejected ..." line under the value that was tried.
- The flow card shows it next to the field, which is outstanding again, until a better value arrives.
- The model sees it under `rejected_previously` with the attempted value, and is told to propose only a value
  that is different and that addresses the reason. "address is not on file; use one on file or confirm a new
  address" gets a better second attempt than "invalid address" does.
- A balance or limit computed at the time is worth including: "exceeds available balance of 60,000.00".

If the model proposes the exact value the flow just turned down, for the same reason, the loop ignores it rather
than reporting the same rejection twice.

Validation is the domain's job, not the model's. The model is told it never decides whether a value is valid. Keep
rules in `validate`, backed by whatever stands in for the system of record (`FakeBAM` here), and keep them cheap:
they run on every change to the flow.

### `supporting`: choices and notes for the branch user

After every change the loop calls `supporting(result)` and, when the answer differs from last time, sends it to
the UI. It returns two things:

    {"choices": {"<field>": [{"value": "...", "label": "..."}, ...]}, "notes": ["...", ...]}

**Choices** become chips under an outstanding field in the flow card. Offer them whenever the domain knows the
set of acceptable answers: the client's accounts, the owners of the chosen account, the addresses on file. Only
fields in `result.missing` show chips, so key the dictionary by outstanding fields. Clicking a chip sends a
transcript line of the form `branch user: <label> = <value>`. The model is told such lines are the branch user
typing into the application and are authoritative for that field, so it returns the value and the normal coerce
and validate path runs. Use the `value` the field's descriptor expects and a `label` people recognise.

**Notes** are shown with a bulb icon on the flow card. Use them for facts the domain can compute once it has
enough inputs (the balance after the check) and for procedure the branch user needs to know (a verification step
applies). Notes and chips disappear once the flow is submitted.

Because `supporting` receives the whole `Result`, a note or choice can depend on what has been accepted so far:
the payee choices are the owners of the account that was accepted.

### Confirmations: things only the branch user can say

Some inputs are not in the transcript; they are the branch user attesting that something was done. The pattern,
used by the large-check verification, is a `bool` field with:

- a descriptor that ends "Only the branch user can say this", so the model never infers it from the client;
- a `validate` block that requires it only in the situation that calls for it, and accepts only `True`;
- in `supporting`, a single chip with value `"true"` and a label such as "Verification completed", plus a note
  explaining why the step applies.

The model sees the field as outstanding, finds nothing in the transcript, and leaves it alone. The chip is the
only way to fill it. The record is not complete, and the review card does not appear, until the chip is used.

### `display` and `submit`

`display(name, value)` formats a value for people. The default renders a float as dollars, a bool as
"Confirmed" or "Not confirmed", and a list as a comma-separated string. Override it for anything else.

`submit(accepted)` is called once, with the accepted values, when the branch user presses Confirm on the review
card. It performs the action and returns `{"reference": ..., "summary": ...}`. The reference is shown as the
receipt and the summary beneath it, so write the summary as the one line you would want in the client's notes.
Nothing in the loop ever calls `submit`; the model cannot trigger it.

### Checking a new flow

Start the backend, send a transcript that asks for the flow, and watch the feed. The quickest loop is
`backend/examples/client.py`, which streams a turn, a follow-up and a confirm from the terminal, or paste into
the sidebar. Things to try: a transcript that gives every field but one, to see the hint and any chips; a value the rule should reject, to read the reason as the branch user will; a correction of a value that
was already accepted; and the confirmation chip, if the flow has one. In the target state the flow definition,
`validate`, `supporting` and `submit` live behind the domain's MCP server, so keep the flow free of anything that
only exists in this prototype.

## Hosting a flow in the domain's MCP server

In the prototype a flow's definition, validation, supporting metadata and submission are Python in this process.
In the target state they belong to the business domain that owns the flow and are hosted in that domain's MCP
server. This application then holds no flow logic at all: it holds the transcript, runs the model loop, and
calls the domain. This section describes what the domain server has to provide and what changes here.

### The split

The domain owns everything that is domain knowledge: what the flow is, what its inputs are and how to describe
them, whether a value is acceptable, what the branch user can be offered, and how to execute. The application
owns everything that is conversation: the transcript, the model, what has been proposed so far and where in the
transcript it came from, and the UI. The domain never sees the transcript. It sees field values, and the
identity of the client on the call so it can look things up.

| in the prototype                       | in the target state                                                        |
|----------------------------------------|----------------------------------------------------------------------------|
| `Flow.name`, `title`, `description`    | an MCP **resource** per flow, read at startup to build the catalogue        |
| `Flow.fields`, `validate`, `supporting`, `display`, `coerce` | one MCP **tool** per flow that validates a set of proposed values |
| `Flow.submit`                          | one MCP **tool** per flow that executes, called only on Confirm             |
| `FlowState.values`, `evidence`, `rejected_history`, `Session` | unchanged, in the application                        |
| the model loop and the UI events       | unchanged, in the application                                               |

### Resource: the flow description

One resource per flow, for example `flow://order_check`, whose content is the catalogue entry the
model reads when deciding whether to activate a flow:

    {
      "name": "order_check",
      "title": "Order a check",
      "description": "The client asks for a check to be issued or sent from one of their accounts. Listen for: ..."
    }

The application lists the server's resources at startup, reads each flow resource, and builds `FLOWS` from them.
The same text is used in the agent card, so the A2A skills the sidebar's backend advertises are exactly the flows
the domain publishes. If the server supports resource subscriptions the application subscribes, so a changed
description takes effect without a restart. Field definitions are deliberately not in the resource: they come
from the first call to the validation tool, where conditional fields and the supporting metadata live anyway.

### Tool: validate a set of proposed values

One tool per flow, for example `validate_order_check`. It is stateless: every call carries the whole
set of values proposed so far, and the answer describes the whole record. The application already works this
way (`FlowState.values` is everything proposed so far and `revalidate` judges all of it), so the loop does not
change shape; `revalidate` becomes a tool call.

Input:

    {
      "client_id": "client-10021",
      "values": { "account": "joint-4471", "amount": 5000, "delivery_address": "48 Rosemary Lane, Carrboro, NC 27510" }
    }

Values are passed as the model expressed them, which is as strings, lists of strings or booleans. The domain
owns the types, so it does the conversion; a value that cannot be converted is simply a rejection with a reason.
That moves `coerce` out of the application.

The first call, when the flow is activated, has an empty `values` object. That is the domain's opportunity to
return every required field with its full metadata, and any choices and notes that apply before anything is
known. Each later call returns the same shape, updated:

    {
      "complete": false,
      "accepted": [
        { "field": "account", "label": "Account", "type": "string",
          "descriptor": "The client's account the check is drawn on. The client will say 'the joint account' or ...",
          "value": "joint-4471", "display": "joint-4471" },
        { "field": "amount", "label": "Amount", "type": "number",
          "descriptor": "The check amount in dollars, as a number. 'five thousand' is 5000.",
          "value": 5000, "display": "$5,000.00" }
      ],
      "rejected": [
        { "field": "delivery_address", "label": "Delivery address", "type": "string",
          "descriptor": "Where to mail the check, as a full postal address. If the client says 'the house' or ...",
          "value": "48 Rosemary Lane, Carrboro, NC 27510",
          "reason": "address is not on file; use one on file or confirm a new address" }
      ],
      "outstanding": [
        { "field": "payee", "label": "Payee", "type": "string",
          "descriptor": "Who the check is made out to. Usually the client. Use the full name as spoken.",
          "hint": "Who is the check made out to?",
          "why": "not provided" }
      ],
      "choices": {
        "payee": [
          { "value": "David Hartley", "label": "David Hartley" },
          { "value": "Margaret Hartley", "label": "Margaret Hartley" }
        ],
        "delivery_address": [
          { "value": "12 Elm Street, Chapel Hill, NC 27514", "label": "12 Elm Street, Chapel Hill, NC 27514" },
          { "value": "PO Box 881, Chapel Hill, NC 27515", "label": "PO Box 881, Chapel Hill, NC 27515" }
        ]
      },
      "notes": ["Available balance on joint-4471 after this check: $55,000.00."]
    }

What each part is for, and where it goes:

- `accepted` carries the display form, because formatting is domain knowledge. The application attaches the
  transcript evidence it kept for each field and renders the review card from the result. It also carries the
  `type` and `descriptor`, because the model is shown resolved fields with their descriptors so that a later
  correction in the transcript comes back in the same format.
- `rejected` reasons go to the feed, to the flow card, and back to the model as previously rejected attempts, so
  they should say what would be acceptable. The application removes a rejected value from its proposed set, as
  it does now, so the next call will not carry it. The application keeps the attempt, with the `type` and
  `descriptor` from this entry, in its own rejection history so the model keeps seeing it even once the field is
  neither accepted nor outstanding.
- `outstanding` is the complete list of what is still required, with the `descriptor` the model needs to express
  a value and the `hint` the branch user needs to ask for it. A field whose requirement depends on accepted
  values (the verification step once an amount is large) simply appears in this list when the condition holds
  and is absent otherwise. A field that cannot be judged yet because a dependency is not accepted is listed here
  with that as its `why`. The application does not need to know about dependencies or conditions at all.
- `choices` and `notes` are the supporting metadata, keyed by field for choices. The application turns choices
  into chips, which send a `branch user: <label> = <value>` line through the model as they do today, and shows
  notes on the flow card. Choices for a field that is not outstanding are ignored.
- `complete` is true when nothing is outstanding or rejected. The application shows the review card on it.

The tool must have no side effects and should be cheap: the loop calls it after every change, up to several
times per turn. It is also the only place the domain learns anything, so anything the domain wants to say to the
branch user, a limit, a balance, a procedure that applies, goes in `notes`.

### Tool: submit

One tool per flow, for example `submit_order_check`, taking `client_id` and the accepted values, and
returning the receipt:

    { "reference": "CHK-5F2C1A", "summary": "Check for $5,000.00 to Margaret Hartley from joint-4471, mailed to 12 Elm Street, Chapel Hill, NC 27514." }

The application calls it only when the branch user presses Confirm on a complete record, and only once per
record; a second confirm returns the stored receipt. The domain should validate again on the way in, since it
cannot assume the application did, and should make the call idempotent on a key the application supplies (the
A2A task id is a natural one) so a retried confirm does not execute twice.

### What changes in the application

- `FLOWS` is built from the server's flow resources instead of the classes in `flows.py`.
- `FlowState.revalidate` calls the validation tool with `client_id` and `values` and stores the response. The
  record artifact, the `fields` event and the `supporting` event are all derived from that response; the
  dependency, condition and formatting code in `flows.py` has no counterpart here.
- `coerce` goes away. The application passes the model's values through and treats a conversion failure as a
  rejection like any other.
- `submit_flow` calls the submit tool.
- The model prompt is unchanged: it is already built from exactly the fields the tool returns. Every entry in
  `accepted`, `rejected` and `outstanding` carries its `type` and `descriptor`, so the application never needs
  a field definition it did not get from the latest response.
- Tool errors, including an unreachable server, surface as the turn's `error` event, as a model failure does
  now.

One MCP server per domain can host several flows this way, and the application can connect to several servers;
the catalogue is the union of their flow resources. A generic pair of tools taking a `flow` argument works too,
but one pair per flow lets each tool publish a typed input schema and keeps the per-flow authorisation at the
tool boundary, which is where a domain will want it.

## Layout of the code

    backend/ambient/flows.py       Field, Result, Flow, FakeBAM, OrderCheck, coerce
    backend/ambient/engine.py      FlowState, Session, prompt and schema, model calls, run_turn, submit_flow
    backend/ambient/a2a_server.py  agent card, AmbientExecutor, create_app (JSON-RPC at /a2a, card at /.well-known/agent-card.json)
    backend/start.sh, start.ps1    start inside .venv, creating it and installing requirements the first time
    backend/examples/client.py     a terminal client that streams a turn, a follow-up and a confirm
    frontend/src/a2a.js            SendStreamingMessage over SSE, and interpret() to pull events out of each result
    frontend/src/state.js          the reducer: how each event changes the feed and the flow records
    frontend/src/components/       Sidebar (frame, resize, run loop), Header, ClientBar, Feed (heard, activity, review), FlowCard, Composer
