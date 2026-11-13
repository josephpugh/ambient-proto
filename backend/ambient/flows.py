"""Flows: the framework (Field, Result, Flow), the stand-in for the BAM tools, and the two flows.

This is the notebook's sections 1 to 5, unchanged in behaviour, with two small additions that
the UI needs: a human label per field, and a `supporting` method per flow that returns the
choices and notes the domain can offer once dependencies are known. In the target state the
flow definition, `validate_inputs`, `supporting` and `submit` live behind the domain's MCP
server. Here they are in-process so the loop can be run end to end.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

Values = dict[str, Any]


@dataclass
class Field:
    name: str
    type: type
    descriptor: str                                          # read by the model
    label: str = ""                                          # read by people
    depends_on: tuple[str, ...] = ()                         # must be accepted before this can be checked
    required_when: Callable[[Values], bool] = lambda accepted: True
    validate: Callable[[Any, Values], str | None] = lambda value, accepted: None   # reason, or None
    hint: str = ""                                           # what to ask the client when outstanding

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


class Flow:
    name: str = ""
    title: str = ""
    description: str = ""            # how the model recognises that this flow is being asked for
    fields: list[Field] = []

    def validate_inputs(self, provided: Values) -> Result:
        r = Result()
        # Pass 1: judge what was provided, dependencies first (fields are listed in dependency order).
        for f in self.fields:
            if f.name not in provided:
                continue
            unmet = [d for d in f.depends_on if d not in r.accepted]
            if unmet:
                r.missing[f.name] = f"cannot be checked until {', '.join(unmet)} is valid"
                continue
            value = provided[f.name]
            if not isinstance(value, f.type):
                r.rejected[f.name] = f"expected {f.type_name()}"
                continue
            reason = f.validate(value, r.accepted)
            if reason:
                r.rejected[f.name] = reason
            else:
                r.accepted[f.name] = value
        # Pass 2: what is required right now, given what has been accepted?
        for f in self.fields:
            if not f.required_when(r.accepted):
                continue
            if f.name in r.accepted or f.name in r.rejected or f.name in r.missing:
                continue
            r.missing[f.name] = "not provided"
        return r

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
            return "All accounts" if value == ["all"] else ", ".join(str(v) for v in value)
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

    def update_address(self, address, effective, accounts) -> str:
        if address not in self.addresses_on_file:
            self.addresses_on_file.append(address)
        return "ADR-" + uuid.uuid4().hex[:6].upper()


bam = FakeBAM()
LARGE_CHECK = 10_000.00


# ---------------------------------------------------------------- flow one: order a check

class OrderCheck(Flow):
    name = "order_check"
    title = "Order a check"
    description = ("The client asks for a check to be issued or sent from one of their accounts. "
                   "Listen for: 'send me a check', 'cut a check', 'I need a check for', an amount and an account.")
    fields = [
        Field("account", str,
              "The client's account the check is drawn on. The client will say 'the joint account' or 'ending 4471', "
              "not the number. Known accounts: joint-4471, ira-9902.",
              label="Account", hint="Which account is the check drawn on?",
              validate=lambda v, acc: None if bam.is_client_account(v) else "not one of the client's accounts"),
        Field("amount", float,
              "The check amount in dollars, as a number. 'five thousand' is 5000.",
              label="Amount", hint="How much is the check for?",
              depends_on=("account",),
              validate=lambda v, acc: ("must be greater than zero" if v <= 0 else
                                       f"exceeds available balance of {bam.balance(acc['account']):,.2f}" if v > bam.balance(acc["account"])
                                       else None)),
        Field("payee", str,
              "Who the check is made out to. Usually the client. Use the full name as spoken.",
              label="Payee", hint="Who is the check made out to?",
              depends_on=("account",),
              validate=lambda v, acc: ("payee name is empty" if not v.strip() else
                                       None if bam.is_owner(acc["account"], v) else "payee is not an owner of the account")),
        Field("delivery_address", str,
              "Where to mail the check, as a full postal address. If the client says 'the house' or 'home', "
              "that means the street address on file: 12 Elm Street, Chapel Hill, NC 27514. 'the PO box' means PO Box 881, Chapel Hill, NC 27515.",
              label="Delivery address", hint="Where should the check be sent?",
              validate=lambda v, acc: (None if bam.address_on_file(v) else
                                       "address is not on file; use one on file or confirm a new address" if bam.standardise(v)
                                       else "not a complete postal address")),
        Field("verification_confirmed", bool,
              "Branch user confirms the large-check verification procedure was completed. Only the branch user can say this.",
              label="Large-check verification", hint="Complete the verification procedure, then confirm it here.",
              depends_on=("amount",),
              required_when=lambda acc: "amount" in acc and acc["amount"] >= LARGE_CHECK,
              validate=lambda v, acc: None if v is True else "verification must be confirmed"),
    ]

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


# ---------------------------------------------------------------- flow two: update a mailing address

def _valid_future_date(v: str) -> str | None:
    try:
        d = date.fromisoformat(v)
    except ValueError:
        return "not an ISO date"
    return None if d >= date.today() else "effective date is in the past"


class UpdateMailingAddress(Flow):
    name = "update_mailing_address"
    title = "Update mailing address"
    description = ("The client says they have moved or want mail sent somewhere new, permanently. "
                   "Listen for: 'we moved', 'new address', 'update my address', 'change where you send'. "
                   "Not for a one-off delivery of a single item.")
    fields = [
        Field("new_address", str,
              "The new mailing address as a full postal address: street, city, state, ZIP.",
              label="New address", hint="What is the full new address, including ZIP?",
              validate=lambda v, acc: None if bam.standardise(v) else "not a complete postal address (need street, city, state, 5-digit ZIP)"),
        Field("effective_date", str,
              "When the change takes effect, as an ISO date (YYYY-MM-DD). 'from the first' means the first of next month.",
              label="Effective date", hint="When should the new address take effect?",
              validate=lambda v, acc: _valid_future_date(v)),
        Field("accounts_to_update", list,
              "Which accounts the new address applies to, as a list of account ids, or ['all'] for every account. "
              "Known accounts: joint-4471, ira-9902.",
              label="Accounts to update", hint="Does this apply to all accounts or only some?",
              validate=lambda v, acc: (None if v == ["all"] or (v and all(bam.is_client_account(a) for a in v))
                                       else "one or more accounts are not the client's")),
        Field("client_confirmed_new_address", bool,
              "Branch user confirms the new address back to the client and the client agreed. Only the branch user can say this.",
              label="Client confirmed address", hint="Read the new address back to the client and confirm they agree.",
              depends_on=("new_address",),
              required_when=lambda acc: "new_address" in acc and not bam.address_on_file(acc["new_address"]),
              validate=lambda v, acc: None if v is True else "client must confirm the new address"),
    ]

    def supporting(self, r: Result) -> dict:
        choices: dict[str, list[dict]] = {}
        notes: list[str] = []
        if "accounts_to_update" in r.missing:
            choices["accounts_to_update"] = [{"value": "all", "label": "All accounts"}] + \
                [{"value": a, "label": n} for a, n in bam.account_names.items()]
        if "client_confirmed_new_address" in r.missing:
            choices["client_confirmed_new_address"] = [{"value": "true", "label": "Client confirmed"}]
            notes.append("The new address is not on file. Read it back to the client before it is recorded.")
        return {"choices": choices, "notes": notes}

    def submit(self, a: Values) -> dict:
        ref = bam.update_address(a["new_address"], a["effective_date"], a["accounts_to_update"])
        return {"reference": ref, "summary": f"Mailing address set to {a['new_address']} from {a['effective_date']} on {self.display('accounts_to_update', a['accounts_to_update']).lower()}."}


# ---------------------------------------------------------------- the catalogue

FLOWS: dict[str, Flow] = {f.name: f for f in (OrderCheck(), UpdateMailingAddress())}


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
