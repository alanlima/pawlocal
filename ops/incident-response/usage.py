"""Bounded provider usage observations, independent of quota enforcement."""

import json
import os
from pathlib import Path

from quota import Denied, integer, strict_json

MAX_OBSERVATION = 16 * 1024 * 1024
TERMINAL = {"completed", "incomplete", "failed"}


def usage_numbers(response):
    if not isinstance(response, dict) or not isinstance(response.get("status"), str) or response.get("status") not in TERMINAL:
        return None
    usage = response.get("usage")
    try:
        if not isinstance(usage, dict):
            return None
        result = {name: integer(usage[name], 0) for name in ("input_tokens", "output_tokens", "total_tokens")}
        if result["total_tokens"] != result["input_tokens"] + result["output_tokens"]:
            return None
        for name, detail, key, ceiling in (
            ("cached_tokens", "input_tokens_details", "cached_tokens", "input_tokens"),
            ("reasoning_tokens", "output_tokens_details", "reasoning_tokens", "output_tokens"),
        ):
            details = usage.get(detail)
            result[name] = integer(details[key], 0) if isinstance(details, dict) and key in details else None
            if result[name] is not None and result[name] > result[ceiling]:
                return None
        result["output_limit_reached"] = int(
            response.get("incomplete_details", {}).get("reason") == "max_output_tokens"
        ) if isinstance(response.get("incomplete_details", {}), dict) else 0
        return result
    except (KeyError, Denied, TypeError):
        return None


class Observation:
    """Bytes are never persisted. SSE framing tolerates arbitrary read boundaries."""

    def __init__(self, streaming):
        self.streaming = streaming
        self.buffer = bytearray()
        self.total = 0
        self.invalid = False
        self.usage = None
        self.finished = False

    def feed(self, chunk):
        self.total += len(chunk)
        if self.total > MAX_OBSERVATION:
            self.invalid = True
            self.buffer.clear()
            return
        self.buffer.extend(chunk)
        if self.streaming:
            while b"\n" in self.buffer:
                line, _, remaining = self.buffer.partition(b"\n")
                self.buffer = bytearray(remaining)
                line = line.rstrip(b"\r")
                # Responses events use one JSON data line. Ignore content deltas.
                if line.startswith(b"data:"):
                    self.parse(line[5:].strip(), event=True)

    def parse(self, raw, event=False):
        try:
            value = strict_json(raw)
            if event:
                if not isinstance(value, dict) or value.get("type") not in {"response." + state for state in TERMINAL}:
                    return
                value = value.get("response")
            observed = usage_numbers(value)
            if observed is not None:
                if self.usage is not None:  # A duplicate terminal is ambiguous.
                    self.invalid = True
                self.usage = observed
        except (ValueError, UnicodeError, RecursionError, TypeError):
            pass

    def finish(self):
        if not self.streaming and not self.finished:
            self.parse(bytes(self.buffer))
            self.finished = True
            self.buffer.clear()
        return None if self.invalid else self.usage


class UsageRecorder:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.requests = []
        self.failures = 0
        self.exhaustions = 0
        self.write()

    def write(self):
        if self.path is None:
            return
        # The parent directory and file belong to the trusted runner, not Codex.
        # Atomic snapshots remain readable after termination mid-response.
        temporary = self.path.with_suffix(".tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w") as output:
                json.dump(self.snapshot(), output, separators=(",", ":"))
            os.replace(temporary, self.path)
        except OSError:
            # Observability cannot deny a previously authorized call or refund it.
            print("Incident usage snapshot unavailable", flush=True)

    def snapshot(self):
        return {"version": 1, "requests": self.requests, "failures": self.failures, "exhaustions": self.exhaustions}

    def reserve(self, counted_input, output_cap):
        self.requests.append({"counted_input": counted_input, "output_cap": output_cap, "actual": None})
        self.write()

    def observed(self, actual):
        if self.requests:
            self.requests[-1]["actual"] = actual
            self.write()

    def failure(self, exhausted):
        self.failures += 1
        self.exhaustions += int(exhausted)
        self.write()
