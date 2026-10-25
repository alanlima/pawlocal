"""Job-local trusted gateway; run as runner, Codex as a distinct non-sudo UID.

The Action proxy receives only a random local bearer, never the upstream key.
No inference retry, remote tool, stored response, or non-Responses endpoint.
"""

import argparse
import hmac
import json
import os
import re
import signal
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from usage import Observation, UsageRecorder
from control import LiveControl
from quota import Denied, Profile, RequestBudget, strict_json
from enforcement import enabled, skipped, operational_deadline

ORIGIN = "https://api.openai.com/v1/responses"
MAX_BODY = 4 * 1024 * 1024
MAX_RESPONSE = 16 * 1024 * 1024
COUNT_FIELDS = {
    "model",
    "input",
    "instructions",
    "tools",
    "text",
    "reasoning",
    "parallel_tool_calls",
    "tool_choice",
    "truncation",
}
BODY_FIELDS = COUNT_FIELDS | {
    "stream",
    "store",
    "max_output_tokens",
    "service_tier",
    "include",
    "metadata",
    "client_metadata",
    "prompt_cache_key",
    "safety_identifier",
}
INPUT_TYPES = {
    "message",
    "function_call",
    "function_call_output",
    "custom_tool_call",
    "custom_tool_call_output",
    "reasoning",
    "compaction",
}


def explicit_text(value):
    if isinstance(value, str):
        return
    if not isinstance(value, list):
        raise Denied("explicit text required")
    for part in value:
        if (
            not isinstance(part, dict)
            or set(part) - {"type", "text", "annotations", "logprobs"}
            or part.get("type") not in {"input_text", "output_text"}
            or not isinstance(part.get("text"), str)
        ):
            raise Denied("only explicit text content supported")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_request(body, profile):
    if (
        not isinstance(body, dict)
        or set(body) - BODY_FIELDS
        or body.get("model") != profile.model
    ):
        raise Denied("unapproved request schema/model")
    if (
        body.get("store") is not False
        or body.get("service_tier", profile.service_tier) != profile.service_tier
    ):
        raise Denied("stored state or unapproved tier")
    reasoning = body.get("reasoning")
    if (
        not isinstance(reasoning, dict)
        or reasoning.get("effort") != profile.effort
        or set(reasoning) - {"effort", "summary"}
    ):
        raise Denied("unapproved reasoning")
    if body.get("truncation", "disabled") != "disabled":
        raise Denied("automatic truncation changes token-count input")
    if type(body.get("stream", False)) is not bool:
        raise Denied("invalid streaming flag")
    if "input" not in body or not isinstance(body["input"], (str, list)):
        raise Denied("explicit full input required")
    if isinstance(body["input"], list):
        for item in body["input"]:
            if (
                not isinstance(item, dict)
                or item.get("type", "message") not in INPUT_TYPES
            ):
                raise Denied("unsupported remote or stored input")
            if item.get("type", "message") == "message":
                if set(item) - {"type", "role", "content", "status", "phase", "id"}:
                    raise Denied("unsupported message fields")
                explicit_text(item.get("content"))
            elif item["type"] in {"function_call_output", "custom_tool_call_output"}:
                if set(item) - {"type", "call_id", "output", "status", "id"}:
                    raise Denied("unsupported output fields")
                explicit_text(item.get("output"))
            elif item["type"] in {"function_call", "custom_tool_call"}:
                if set(item) - {
                    "type",
                    "call_id",
                    "name",
                    "arguments",
                    "input",
                    "status",
                    "id",
                }:
                    raise Denied("unsupported local call fields")
                if not isinstance(item.get("arguments", item.get("input")), str):
                    raise Denied("explicit local call text required")
            elif item["type"] == "reasoning":
                if set(item) - {
                    "type",
                    "id",
                    "summary",
                    "content",
                    "encrypted_content",
                    "status",
                }:
                    raise Denied("unsupported reasoning fields")
                for field in ("summary", "content"):
                    if field in item and (
                        not isinstance(item[field], list)
                        or any(
                            not isinstance(part, dict)
                            or set(part) != {"type", "text"}
                            or part["type"] not in {"summary_text", "reasoning_text"}
                            or not isinstance(part["text"], str)
                            for part in item[field]
                        )
                    ):
                        raise Denied("explicit reasoning text required")
                if "encrypted_content" in item and not isinstance(
                    item["encrypted_content"], str
                ):
                    raise Denied("invalid encrypted reasoning")
            elif set(item) - {"type", "id", "encrypted_content"} or not isinstance(
                item.get("encrypted_content"), str
            ):
                raise Denied("unsupported compaction fields")
    tools = body.get("tools", [])
    if (
        not isinstance(tools, list)
        or len(tools) > 64
        or any(
            not isinstance(tool, dict)
            or tool.get("type") not in {"function", "custom", "namespace"}
            for tool in tools
        )
    ):
        raise Denied("remote/billable tools forbidden")
    # Namespace tools must recursively contain only local function/custom tools.
    for tool in tools:
        if tool["type"] == "namespace":
            nested = tool.get("tools")
            if (
                not isinstance(nested, list)
                or len(nested) > 64
                or any(
                    not isinstance(value, dict)
                    or value.get("type") not in {"function", "custom"}
                    for value in nested
                )
            ):
                raise Denied("remote namespace tools forbidden")


class Gateway:
    def __init__(
        self,
        profile,
        key,
        local_token,
        deadline,
        upstream=None,
        clock=time.time,
        control=None,
        diagnostic=None,
        usage=None,
    ):
        if (
            not key
            or len(local_token) < 32
            or enabled()
            and not clock() < deadline <= clock() + 1200
        ):
            raise Denied("invalid gateway authorization/deadline")
        self.usage = usage or UsageRecorder()
        self.profile = profile
        self.key = key
        self.local_token = local_token
        self.deadline = deadline if enabled() else operational_deadline()
        self.clock = clock
        self.budget = RequestBudget(profile)
        self.received = 0
        self.counted_input_tokens = None
        self.request_body_bytes = None
        self.upstream = upstream or self.request
        self.control = control
        self.stage = "request_headers"
        self.diagnostic = diagnostic or (
            lambda event: print(json.dumps(event), file=sys.stderr, flush=True)
        )

    def accounting(self):
        # Numeric accounting only: never request text, headers or credentials.
        p = self.profile
        return {
            "counted_input_tokens": self.counted_input_tokens,
            "requests_received": self.received,
            "requests_reserved": self.budget.requests,
            "input_tokens_reserved": self.budget.inputs,
            "output_tokens_reserved": self.budget.outputs,
            "request_body_bytes": self.request_body_bytes,
            "limits": {
                "requests_per_role": p.requests_per_role,
                "input_per_request": p.input_per_request,
                "input_per_role": p.input_per_role,
                "output_per_request": p.output_per_request,
                "output_per_role": p.output_per_role,
                "effective_output_per_request": min(
                    p.output_per_request, p.output_per_role // p.requests_per_role
                ),
                "request_body_bytes": MAX_BODY,
            },
        }

    def ensure_live(self):
        if self.control is not None:
            self.control()

    def remaining(self):
        if not enabled():
            skipped("deadline")
            return 90
        self.profile.valid_at(self.clock())
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise Denied("workflow deadline exhausted")
        return min(remaining, 90)

    def request(self, suffix, payload):
        request = urllib.request.Request(
            ORIGIN + suffix,
            data=json.dumps(payload, separators=(",", ":")).encode(),
            headers={
                "Authorization": "Bearer " + self.key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return urllib.request.build_opener(NoRedirect).open(
            request, timeout=self.remaining()
        )

    def admit(self, authorization, raw):
        self.counted_input_tokens = None
        self.request_body_bytes = len(raw)
        if not isinstance(authorization, str) or not hmac.compare_digest(
            authorization, "Bearer " + self.local_token
        ):
            raise Denied("local authentication failed")
        self.stage = "live_control"
        self.remaining()
        self.ensure_live()
        self.stage = "request_quota"
        self.received += 1
        if enabled() and self.received > self.profile.requests_per_role:
            raise Denied("request count quota exhausted")
        if len(raw) > MAX_BODY:
            raise Denied("request body bound exceeded")
        self.stage = "request_validation"
        body = strict_json(raw)
        if isinstance(body, dict):
            # CLI correlation identifiers are unnecessary for this adapter and
            # never forwarded upstream. Tier is fixed even when CLI omits it.
            for field in (
                "client_metadata",
                "metadata",
                "prompt_cache_key",
                "safety_identifier",
            ):
                body.pop(field, None)
            body.setdefault("service_tier", self.profile.service_tier)
        else:
            raise Denied("Responses API request object required")
        if enabled():
            validate_request(body, self.profile)
        # Counting and generation are different provider endpoint schemas.
        # Project transport fields in both modes; this is not policy admission.
        count_body = {key: value for key, value in body.items() if key in COUNT_FIELDS}
        # Token counting includes tool schemas, instructions and entire history.
        # Failure, unknown schema, redirect, or missing count denies inference.
        self.stage = "input_token_count"
        with self.upstream("/input_tokens", count_body) as response:
            if response.status != 200:
                raise Denied("token counting failed")
            count_raw = response.read(65537)
            if len(count_raw) > 65536:
                raise Denied("token count response too large")
            count = strict_json(count_raw)
            if (
                not isinstance(count, dict)
                or type(count.get("input_tokens")) is not int
            ):
                raise Denied("token count missing")
        self.stage = "quota_reservation"
        self.counted_input_tokens = count["input_tokens"]
        cap = self.budget.admit(self.counted_input_tokens)
        self.usage.reserve(self.counted_input_tokens, cap)
        body["max_output_tokens"] = cap
        self.remaining()
        # Conservative charged allocation, not a claim of provider-billed
        # usage. Never log prompts, tool arguments, responses or credentials.
        numerator = (
            self.budget.inputs * self.profile.input_rate
            + self.budget.outputs * self.profile.output_rate
        )
        self.diagnostic(
            {
                "event": "oncall_quota_reserved",
                "profile": self.profile.digest,
                "model": self.profile.model,
                "requests": self.budget.requests,
                "upper_cost_microdollars": (numerator + 999999) // 1000000,
                **self.accounting(),
            }
        )
        return body


def serve(gateway, port):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *_args):
            # No bodies, query strings, bearer tokens or prompts in access logs.
            pass

        def do_POST(self):
            started = False
            gateway.stage = "request_headers"
            gateway.counted_input_tokens = None
            gateway.request_body_bytes = None
            try:
                if (
                    self.path != "/v1/responses"
                    or self.headers.get("Transfer-Encoding")
                    or self.headers.get("Content-Encoding")
                ):
                    raise Denied("fixed endpoint required")
                if (
                    len(self.headers.get_all("Authorization", [])) != 1
                    or len(self.headers.get_all("Content-Length", [])) != 1
                ):
                    raise Denied("ambiguous request headers")
                length = int(self.headers.get("Content-Length", "-1"))
                gateway.request_body_bytes = length
                if not 0 < length <= MAX_BODY:
                    raise Denied("request body bound exceeded")
                self.connection.settimeout(min(gateway.remaining(), 10))
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise Denied("incomplete body")
                body = gateway.admit(self.headers.get("Authorization"), raw)
                gateway.stage = "live_control"
                gateway.ensure_live()
                gateway.stage = "inference"
                with gateway.upstream("", body) as response:
                    if response.status != 200:
                        raise Denied("upstream inference failed")
                    content_type = response.headers.get("Content-Type", "")
                    if not (
                        content_type.startswith(
                            ("text/event-stream", "application/json")
                        )
                    ):
                        raise Denied("unexpected upstream content type")
                    observation = Observation(
                        content_type.startswith("text/event-stream")
                    )
                    started = True
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.end_headers()
                    total = 0
                    while True:
                        gateway.remaining()
                        chunk = response.read(16384)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_RESPONSE:
                            raise Denied("upstream response bound")
                        observation.feed(chunk)
                        # Persist terminal usage before a potentially broken client write.
                        if observation.streaming and observation.usage is not None:
                            gateway.usage.observed(observation.finish())
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    gateway.usage.observed(observation.finish())
            except (
                Denied,
                ValueError,
                OSError,
                urllib.error.URLError,
                TimeoutError,
            ) as error:
                # One classification, no gateway retry and no reservation refund.
                status = 403
                event = {
                    "event": "oncall_gateway_failure",
                    "stage": gateway.stage,
                    "origin": "local",
                    "code": "local_quota_exhausted"
                    if gateway.stage in {"request_quota", "quota_reservation"}
                    else "local_admission_denied",
                    "reason": str(error)
                    if isinstance(error, Denied)
                    else "invalid_request",
                    "response_started": started,
                    **gateway.accounting(),
                }
                if isinstance(error, urllib.error.HTTPError):
                    status = error.code if 400 <= error.code <= 599 else 502
                    origin = (
                        "openai"
                        if gateway.stage in {"input_token_count", "inference"}
                        else "github"
                    )
                    event.update(
                        origin=origin,
                        code="upstream_http_error",
                        reason="upstream_http_error",
                        upstream_status=error.code,
                    )
                    # Read only bounded structured error identifiers, never messages or payloads.
                    try:
                        raw_error = error.read(65537)
                        details = (
                            strict_json(raw_error) if len(raw_error) <= 65536 else None
                        )
                        details = (
                            details.get("error") if isinstance(details, dict) else None
                        )
                        if isinstance(details, dict):
                            for name in ("code", "type"):
                                value = details.get(name)
                                if isinstance(value, str) and re.fullmatch(
                                    r"[A-Za-z0-9_-]{1,128}", value
                                ):
                                    event["upstream_" + name] = value
                    except (ValueError, OSError, urllib.error.URLError, TimeoutError):
                        pass
                    finally:
                        error.close()
                    request_id = (
                        error.headers.get("x-request-id", "") if error.headers else ""
                    )
                    if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id):
                        event["request_id"] = request_id
                elif isinstance(error, (OSError, urllib.error.URLError, TimeoutError)):
                    status = 502
                    event.update(
                        origin="transport",
                        code="transport_uncertain",
                        reason="transport_failure",
                    )
                gateway.usage.failure(event["code"] == "local_quota_exhausted")
                gateway.diagnostic(event)
                self.close_connection = True
                if not started and not self.wfile.closed:
                    try:
                        raw = json.dumps({"error": event}).encode()
                        self.send_response(status)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(raw)))
                        self.end_headers()
                        self.wfile.write(raw)
                    except OSError:
                        pass

        def do_GET(self):
            self.send_error(405)

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1
    # Absolute wall clock, including idle periods; no request can restart it.
    while gateway.clock() < gateway.deadline:
        server.handle_request()
    server.server_close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--deadline", type=int, required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if (
        os.name != "posix"
        or os.stat(args.profile).st_uid != os.getuid()
        or os.stat(args.profile).st_mode & 0o022
    ):
        raise Denied("trusted owner-only profile required")
    remaining = args.deadline - time.time()
    if enabled() and not 0 < remaining <= 1200:
        raise Denied("invalid absolute deadline")
    # Kernel-delivered main-thread alarm covers header parsing, socket reads,
    # blocked upstream/client writes and idle time, not merely loop boundaries.
    signal.signal(signal.SIGALRM, lambda *_: os._exit(124))
    if enabled():
        signal.setitimer(signal.ITIMER_REAL, remaining)
    profile = Profile.load(Path(args.profile).read_text())
    # stdin avoids real API key in argv, candidate files or exported job env.
    credentials = strict_json(sys.stdin.readline(MAX_BODY))

    def read_control(path):
        if not re.fullmatch(r"/issues/[1-9][0-9]*", path):
            raise Denied("unsupported live-control read")
        request = urllib.request.Request(
            "https://api.github.com/repos/alanlima/pawlocal" + path,
            headers={
                "Authorization": "Bearer " + credentials["github_token"],
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.build_opener(NoRedirect).open(
            request, timeout=min(10, args.deadline - time.time())
        ) as response:
            raw = response.read(65537)
            if response.status != 200 or len(raw) > 65536:
                raise Denied("live-control read uncertain")
            return strict_json(raw)

    control = LiveControl(read_control, credentials["metadata"], args.deadline).check
    diagnostic_path = Path(args.profile).with_name("gateway-diagnostics.jsonl")
    # Trusted runner owns this fixed path; the model UID cannot replace it.
    descriptor = os.open(diagnostic_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    diagnostic_file = os.fdopen(descriptor, "w", buffering=1)

    def diagnostic(event):
        raw = json.dumps(event)
        print(raw, file=sys.stderr, flush=True)
        diagnostic_file.write(raw + "\n")
        diagnostic_file.flush()

    gateway = Gateway(
        profile,
        credentials["api_key"],
        credentials["local_token"],
        args.deadline,
        control=control,
        diagnostic=diagnostic,
        usage=UsageRecorder(Path(args.profile).with_name("gateway-usage.json")),
    )
    serve(gateway, args.port)


if __name__ == "__main__":
    main()
