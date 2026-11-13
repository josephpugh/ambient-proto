"""Stream a turn, a follow-up on the same task, and a confirm, printing each A2A update.

    python examples/client.py [http://127.0.0.1:9999]
"""

import json
import sys
import uuid

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9999").rstrip("/")
HEADERS = {"A2A-Version": "1.0", "Content-Type": "application/json", "Accept": "text/event-stream"}

TRANSCRIPT = """advisor: Thanks for calling, Margaret. What can I do for you today?
client: The roof people start Monday and I need a check for five thousand from the joint account.
advisor: Sure. That's the one ending 4471?
client: Yes, that one.
advisor: And who should it be made out to?
client: Just make it out to me.
advisor: That's Margaret Hartley, correct?
client: Yes.
advisor: Where would you like it sent?
client: Send it to the house, same as last time."""


def stream(parts, context_id=None, task_id=None):
    msg = {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": parts}
    if context_id:
        msg["contextId"] = context_id
    if task_id:
        msg["taskId"] = task_id
    body = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "SendStreamingMessage", "params": {"message": msg}}
    with httpx.stream("POST", BASE + "/a2a", headers=HEADERS, json=body, timeout=120) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line.startswith("data:"):
                msg = json.loads(line[5:])
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                yield msg["result"]


def show(result):
    if "task" in result:
        t = result["task"]
        print(f"  task {t['id'][:8]} in context {t['contextId'][:8]}: {t['status']['state']}")
        return t["contextId"], t["id"]
    if "statusUpdate" in result:
        su = result["statusUpdate"]
        for p in su["status"].get("message", {}).get("parts", []):
            if "data" in p:
                d = p["data"]
                print(f"  {su['status']['state']:<26} {d.get('kind')}: " + json.dumps({k: v for k, v in d.items() if k != 'kind'})[:160])
            elif "text" in p:
                print(f"  {su['status']['state']:<26} text: {p['text']}")
    if "artifactUpdate" in result:
        a = result["artifactUpdate"]["artifact"]
        rec = a["parts"][0]["data"]
        print(f"  artifact {a['artifactId']}: {rec['status']}, {len(rec['resolved'])} resolved, {len(rec['outstanding'])} outstanding")
    return None


def main():
    card = httpx.get(BASE + "/.well-known/agent-card.json").json()
    print("agent:", card["name"], "| skills:", [s["id"] for s in card["skills"]])

    print("\n-- turn 1: the transcript")
    ctx = task = None
    for r in stream([{"text": TRANSCRIPT}]):
        ids = show(r)
        if ids:
            ctx, task = ids

    print("\n-- turn 2: a follow-up line on the same task")
    for r in stream([{"text": "advisor: OK, I'll get that started and confirm the details with you before it goes."}], ctx, task):
        show(r)

    print("\n-- confirm the check order")
    for r in stream([{"data": {"action": "confirm", "flow": "order_check"}}], ctx, task):
        show(r)


if __name__ == "__main__":
    main()
