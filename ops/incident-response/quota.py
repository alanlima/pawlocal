"""Trusted, conservative admission arithmetic. No profile is configured by default.

Amounts use integer microdollars. Reserve both executions' entire envelope and
never refund automatically, including when jobs fail before recording usage.
"""

import datetime as dt
import hashlib
import json
import re
import time
from dataclasses import dataclass


class Denied(ValueError):
    """Admission was not authorized; callers must not start a model process."""


def integer(value, minimum=1, maximum=10**12):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Denied("invalid bounded integer")
    return value


def strict_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise Denied("duplicate JSON key")
            result[key] = value
        return result

    try:
        return json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(Denied("nonfinite JSON")),
        )
    except (TypeError, json.JSONDecodeError) as error:
        raise Denied("invalid JSON") from error


@dataclass(frozen=True)
class Profile:
    model: str
    effort: str
    service_tier: str
    input_rate: int
    output_rate: int
    monthly_microdollars: int
    monthly_runs: int
    promotion_seconds: int
    recovery_seconds: int
    rule_uids: dict
    requests_per_role: int
    input_per_request: int
    output_per_request: int
    input_per_role: int
    output_per_role: int
    approval: str
    approved_month: str
    rates_source: str
    rates_reviewed_at: str
    expires_at: str

    @classmethod
    def load(cls, raw, now=None):
        value = strict_json(raw)
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise Denied("complete approved runtime profile required")
        for name in ("model", "approval"):
            if not isinstance(value[name], str) or not re.fullmatch(
                r"[A-Za-z0-9_.:/-]{1,160}", value[name]
            ):
                raise Denied("explicit model and approval reference required")
        if (
            value["effort"] not in {"minimal", "low", "medium", "high", "xhigh"}
            or value["service_tier"] != "default"
        ):
            raise Denied("approved effort and Standard tier required")
        for name in set(value) - {
            "model",
            "effort",
            "service_tier",
            "approval",
            "approved_month",
            "rates_source",
            "rates_reviewed_at",
            "expires_at",
            "rule_uids",
        }:
            integer(value[name])
        if (
            value["monthly_runs"] > 1000
            or value["promotion_seconds"] > 3600
            or not 600 <= value["recovery_seconds"] <= 900
            or value["promotion_seconds"] < 2 * value["recovery_seconds"] + 300
            or value["requests_per_role"] > 32
            or value["input_per_request"] > 250000
            or value["output_per_request"] > 32000
        ):
            raise Denied("request limits exceed reviewed gateway bounds")
        if (
            not isinstance(value["rule_uids"], dict)
            or set(value["rule_uids"]) != {"development", "production"}
            or any(
                not isinstance(uid, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", uid)
                for uid in value["rule_uids"].values()
            )
        ):
            raise Denied("explicit per-environment recovery rule UIDs required")
        for prefix in ("input", "output"):
            if (
                value[f"{prefix}_per_role"]
                > value[f"{prefix}_per_request"] * value["requests_per_role"]
            ):
                raise Denied("inconsistent cumulative limit")
        profile = cls(**value)
        profile.valid_at(time.time() if now is None else now)
        return profile

    def valid_at(self, now):
        if not isinstance(self.rates_source, str) or not re.fullmatch(
            r"https://(?:developers|platform)\.openai\.com/[A-Za-z0-9_./#?=&-]{1,240}",
            self.rates_source,
        ):
            raise Denied("official reviewed pricing source required")
        try:
            if not all(
                isinstance(value, str)
                and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value)
                for value in (self.rates_reviewed_at, self.expires_at)
            ):
                raise Denied("explicit UTC profile validity required")
            reviewed = dt.datetime.fromisoformat(self.rates_reviewed_at).timestamp()
            expires = dt.datetime.fromisoformat(self.expires_at).timestamp()
            current_month = dt.datetime.fromtimestamp(now, dt.UTC).strftime("%Y-%m")
        except (ValueError, OverflowError) as error:
            raise Denied("invalid profile validity") from error
        if (
            self.approved_month != current_month
            or not reviewed <= now < expires
            or expires - reviewed > 31 * 86400
        ):
            raise Denied("stale, future or unapproved-month profile")

    @property
    def digest(self):
        return hashlib.sha256(
            json.dumps(self.__dict__, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @property
    def reservation(self):
        # Rates are approved worst-case microdollars per million tokens,
        # including any model/context surcharge; cached-input discount ignored.
        numerator = 2 * (
            self.input_per_role * self.input_rate
            + self.output_per_role * self.output_rate
        )
        return (numerator + 999999) // 1000000


def reserve(profile, ledger, month, run_id, attempt):
    """Caller holds the global workflow concurrency lease for the whole run.

    Ledger is fetched from the protected, fixed issue immediately before write.
    Persist and read back this reservation BEFORE exposing any API gateway.
    Never release a reservation based on an untrusted usage artifact.
    """
    if (
        not isinstance(month, str)
        or not isinstance(run_id, str)
        or type(attempt) is not int
        or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month)
        or not re.fullmatch(r"[1-9]\d{0,19}", run_id)
        or attempt != 1
    ):
        raise Denied("invalid month/run or repeated attempt")
    if not isinstance(ledger, list) or len(ledger) > 10000:
        raise Denied("invalid ledger")
    spent = 0
    admissions = 0
    seen = set()
    for entry in ledger:
        if not isinstance(entry, dict) or set(entry) != {
            "month",
            "run_id",
            "profile",
            "microdollars",
        }:
            raise Denied("invalid ledger entry")
        if (
            not isinstance(entry["run_id"], str)
            or not isinstance(entry["profile"], str)
            or not re.fullmatch(r"[1-9]\d{0,19}", entry["run_id"])
            or not re.fullmatch(r"[0-9a-f]{64}", entry["profile"])
        ):
            raise Denied("invalid ledger identity")
        if not isinstance(entry["month"], str) or not re.fullmatch(
            r"\d{4}-(0[1-9]|1[0-2])", entry["month"]
        ):
            raise Denied("invalid ledger month")
        integer(entry["microdollars"])
        if entry["run_id"] in seen:
            raise Denied("duplicate ledger run")
        seen.add(entry["run_id"])
        if entry["month"] == month:
            spent += entry["microdollars"]
            admissions += 1
    if (
        run_id in seen
        or admissions >= profile.monthly_runs
        or spent + profile.reservation > profile.monthly_microdollars
    ):
        raise Denied("duplicate or exhausted monthly admission")
    return {
        "month": month,
        "run_id": run_id,
        "profile": profile.digest,
        "microdollars": profile.reservation,
    }


class RequestBudget:
    """Per-job trusted process state, never writable by the Codex account."""

    def __init__(self, profile):
        self.profile = profile
        self.requests = self.inputs = self.outputs = 0

    def admit(self, input_tokens):
        p = self.profile
        integer(input_tokens, 0)
        if (
            input_tokens > p.input_per_request
            or self.requests >= p.requests_per_role
            or self.inputs + input_tokens > p.input_per_role
        ):
            raise Denied("request or cumulative input quota exhausted")
        output_cap = min(p.output_per_request, p.output_per_role - self.outputs)
        if output_cap <= 0:
            raise Denied("cumulative output quota exhausted")
        # Charge BEFORE forwarding. Unknown/failed/stream-interrupted requests
        # keep their whole output allocation, preventing retry overspend.
        self.requests += 1
        self.inputs += input_tokens
        self.outputs += output_cap
        return output_cap
