"""Flows: the framework (Field, Result, Flow), the stand-in for the BAM tools, and the order check flow.

A Field is only a schema entry: the name, the type, the descriptor the model reads, and the label and hint
people read. It holds no rules. Everything that decides whether a value is acceptable, what depends on what, and what is required when, is code in the
flow's `validate` method. In the target state the flow definition, `validate`, `supporting` and `submit`
live behind the domain's MCP server. Here they are in-process so the loop can be run end to end.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

Values = dict[str, Any]


@dataclass
class Field:
    name: str            # key in the record and in the model's reply
    type: type           # str, float, bool or list; the model returns strings and `coerce` converts them
    descriptor: str      # what the value is and how to express it, read by the model
    label: str = ""      # what people see; defaults to the name with underscores as spaces
    hint: str = ""       # the question to ask the client while the field is outstanding, shown to people

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.name.replace("_", " ").capitalize()

    def type_name(self) -> str:
        return {str: "string", float: "number", bool: "boolean", list: "list of strings"}.get(self.type, self.type.__name__)


@dataclass
class Result:
    accepted: Values = field(default_factory=dict)           # name -> value
    missing: dict[str, str] = field(default_factory=dict)    # name -> why still outstanding
    rejected: dict[str, str] = field(default_factory=dict)   # name -> why turned down

    @property
    def complete(self) -> bool:
        return not self.missing and not self.rejected

    # The vocabulary a flow's `validate` uses to record its verdicts.
    def accept(self, name: str, value: Any) -> None:
        self.accepted[name] = value

    def reject(self, name: str, reason: str) -> None:
        self.rejected[name] = reason

    def require(self, name: str, why: str = "not provided") -> None:
        """Mark a field outstanding. A value that was turned down stays reported as rejected, not missing."""
        if name not in self.rejected:
            self.missing[name] = why

    def defer(self, name: str, *until: str) -> None:
        """A value was given but cannot be judged until the named fields are accepted."""
        self.require(name, f"cannot be checked until {', '.join(until)} is valid")


class Flow:
    name: str = ""
    title: str = ""
    description: str = ""            # how the model recognises that this flow is being asked for
    fields: list[Field] = []

    def validate_inputs(self, provided: Values) -> Result:
        """Type-check what was proposed against the schema, then let the flow's own rules judge all of it."""
        r = Result()
        typed: Values = {}
        for f in self.fields:
            if f.name not in provided:
                continue
            if isinstance(provided[f.name], f.type):
                typed[f.name] = provided[f.name]
            else:
                r.reject(f.name, f"expected {f.type_name()}")
        self.validate(typed, r)
        return r

    def validate(self, values: Values, r: Result) -> None:
        """The flow's rules. Given every typed value proposed so far, record on `r` what is accepted, what is
        rejected and why, and what is still required and why. Dependencies between fields, conditional
        requirements and the domain checks all live here, not in the field schema. Overridden per flow."""
        raise NotImplementedError

    def supporting(self, result: Result) -> dict:
        """Choices per outstanding field and notes for the branch user. Overridden per flow."""
        return {"choices": {}, "notes": []}

    def submit(self, accepted: Values) -> dict:
        """The irreversible action, only ever called on the branch user's instruction."""
        raise NotImplementedError

    def field(self, name: str) -> Field:
        return next(f for f in self.fields if f.name == name)

    def has_field(self, name: str) -> bool:
        return any(f.name == name for f in self.fields)

    def display(self, name: str, value: Any) -> str:
        f = self.field(name)
        if f.type is float:
            return f"${value:,.2f}"
        if f.type is bool:
            return "Confirmed" if value else "Not confirmed"
        if f.type is list:
            return ", ".join(str(v) for v in value)
        return str(value)


# ---------------------------------------------------------------- stand-in for the BAM tools

class FakeBAM:
    accounts = {"joint-4471": 60_000.00, "ira-9902": 250_000.00}
    account_names = {"joint-4471": "Joint brokerage, ending 4471", "ira-9902": "Traditional IRA, ending 9902"}
    owners = {"joint-4471": {"Margaret Hartley", "David Hartley"}, "ira-9902": {"Margaret Hartley"}}
    addresses_on_file = ["12 Elm Street, Chapel Hill, NC 27514", "PO Box 881, Chapel Hill, NC 27515"]

    def is_client_account(self, a): return a in self.accounts
    def balance(self, a): return self.accounts[a]
    def is_owner(self, a, name): return name in self.owners[a]
    def address_on_file(self, addr): return addr in self.addresses_on_file
    def standardise(self, addr):
        # Pretend address verification: needs a street or box, a city, a state and a 5-digit ZIP.
        return bool(re.search(r"\b[A-Z]{2}\s+\d{5}\b", addr)) and "," in addr

    def order_check(self, account, amount, payee, address) -> str:
        self.accounts[account] -= amount
        return "CHK-" + uuid.uuid4().hex[:6].upper()


bam = FakeBAM()
LARGE_CHECK = 10_000.00


# ---------------------------------------------------------------- the flow: order a check

class OrderCheck(Flow):
    name = "order_check"
    title = "Order a check"
    description = ("The client asks for a check to be issued or sent from one of their accounts. "
                   "Listen for: 'send me a check', 'cut a check', 'I need a check for', an amount and an account.")
    fields = [
        Field("account", str,
              "The client's account the check is drawn on. The client will say 'the joint account' or 'ending 4471', "
              "not the number. Known accounts: joint-4471, ira-9902.",
              label="Account", hint="Which account is the check drawn on?"),
        Field("amount", float,
              "The check amount in dollars, as a number. 'five thousand' is 5000.",
              label="Amount", hint="How much is the check for?"),
        Field("payee", str,
              "Who the check is made out to. Usually the client. Use the full name as spoken.",
              label="Payee", hint="Who is the check made out to?"),
        Field("delivery_address", str,
              "Where to mail the check, as a full postal address. If the client says 'the house' or 'home', "
              "that means the street address on file: 12 Elm Street, Chapel Hill, NC 27514. 'the PO box' means PO Box 881, Chapel Hill, NC 27515.",
              label="Delivery address", hint="Where should the check be sent?"),
        Field("verification_confirmed", bool,
              "Branch user confirms the large-check verification procedure was completed. Only the branch user can say this.",
              label="Large-check verification", hint="Complete the verification procedure, then confirm it here."),
    ]

    def validate(self, v: Values, r: Result) -> None:
        # The account comes first: the amount and the payee are both judged against it.
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
        elif v["amount"] <= 0:
            r.reject("amount", "must be greater than zero")
        elif v["amount"] > bam.balance(account):
            r.reject("amount", f"exceeds available balance of {bam.balance(account):,.2f}")
        else:
            r.accept("amount", v["amount"])

        if "payee" not in v:
            r.require("payee")
        elif account is None:
            r.defer("payee", "account")
        elif not v["payee"].strip():
            r.reject("payee", "payee name is empty")
        elif not bam.is_owner(account, v["payee"]):
            r.reject("payee", "payee is not an owner of the account")
        else:
            r.accept("payee", v["payee"])

        if "delivery_address" not in v:
            r.require("delivery_address")
        elif bam.address_on_file(v["delivery_address"]):
            r.accept("delivery_address", v["delivery_address"])
        elif bam.standardise(v["delivery_address"]):
            r.reject("delivery_address", "address is not on file; use one on file or confirm a new address")
        else:
            r.reject("delivery_address", "not a complete postal address")

        # The large-check verification is only part of the record once the amount is accepted and at or above
        # the threshold. Until then it is invisible: not outstanding, not asked for, not shown.
        amount = r.accepted.get("amount")
        if "verification_confirmed" in v:
            if amount is None:
                r.defer("verification_confirmed", "amount")
            elif v["verification_confirmed"] is not True:
                r.reject("verification_confirmed", "verification must be confirmed")
            else:
                r.accept("verification_confirmed", v["verification_confirmed"])
        elif amount is not None and amount >= LARGE_CHECK:
            r.require("verification_confirmed")

    def supporting(self, r: Result) -> dict:
        choices: dict[str, list[dict]] = {}
        notes: list[str] = []
        if "account" in r.missing:
            choices["account"] = [{"value": a, "label": n} for a, n in bam.account_names.items()]
        if "account" in r.accepted and "payee" in r.missing:
            choices["payee"] = [{"value": o, "label": o} for o in sorted(bam.owners[r.accepted["account"]])]
        if "delivery_address" in r.missing:
            choices["delivery_address"] = [{"value": a, "label": a} for a in bam.addresses_on_file]
        if "verification_confirmed" in r.missing:
            choices["verification_confirmed"] = [{"value": "true", "label": "Verification completed"}]
        if "amount" in r.accepted and r.accepted["amount"] >= LARGE_CHECK:
            notes.append(f"This check is at or above ${LARGE_CHECK:,.0f}. The large-check verification procedure applies before it can be ordered.")
        if "account" in r.accepted and "amount" in r.accepted:
            notes.append(f"Available balance on {r.accepted['account']} after this check: ${bam.balance(r.accepted['account']) - r.accepted['amount']:,.2f}.")
        return {"choices": choices, "notes": notes}

    def submit(self, a: Values) -> dict:
        ref = bam.order_check(a["account"], a["amount"], a["payee"], a["delivery_address"])
        return {"reference": ref, "summary": f"Check for ${a['amount']:,.2f} to {a['payee']} from {a['account']}, mailed to {a['delivery_address']}."}


# ---------------------------------------------------------------- the catalogue

FLOWS: dict[str, Flow] = {f.name: f for f in (OrderCheck(),)}


def coerce(f: Field, raw: Any) -> tuple[Any, str | None]:
    """The model returns strings. The field says what type it must be."""
    try:
        if f.type is float:
            return float(str(raw).replace(",", "").replace("$", "")), None
        if f.type is bool:
            return str(raw).strip().lower() in ("true", "yes", "y", "1"), None
        if f.type is list:
            v = json.loads(raw) if isinstance(raw, str) else raw
            return (list(v), None) if isinstance(v, list) else (None, "expected a JSON list")
        return str(raw).strip(), None
    except Exception:
        return None, f"could not convert '{raw}' to {f.type_name()}"
