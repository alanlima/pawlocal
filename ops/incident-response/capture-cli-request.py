"""Capture pinned CLI wire shape against localhost only; never uses a real key.

Developer verification tool, not an admission override or a live model smoke.
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4 * 1024 * 1024:
                self.send_error(413)
                return
            requests.append(json.loads(self.rfile.read(length)))
            response = {
                "id": "resp_fixture",
                "object": "response",
                "status": "completed",
                "model": "fixture-model",
                "output": [],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            }
            raw = (
                "event: response.completed\ndata: "
                + json.dumps({"type": "response.completed", "response": response})
                + "\n\n"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    with tempfile.TemporaryDirectory(prefix="pawlocal-cli-fixture-") as directory:
        home = Path(directory) / "home"
        home.mkdir()
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        (home / "config.toml").write_text(
            'model_provider = "fixture"\nmodel = "fixture-model"\nmodel_reasoning_effort = "medium"\nservice_tier = "default"\nweb_search = "disabled"\n'
            '[model_providers.fixture]\nname = "local-only fixture"\nwire_api = "responses"\n'
            f'base_url = "http://127.0.0.1:{server.server_port}/v1"\nenv_key = "FIXTURE_API_KEY"\nrequires_openai_auth = false\n'
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if not any(word in key.upper() for word in ("OPENAI", "CODEX", "API_KEY"))
        }
        environment.update(
            {
                "CODEX_HOME": str(home),
                "HOME": directory,
                "USERPROFILE": directory,
                "FIXTURE_API_KEY": "local-fixture-not-a-real-key",
            }
        )
        command = [
            shutil.which("npm.cmd" if os.name == "nt" else "npm"),
            "exec",
            "--yes",
            "--package=@openai/codex@0.163.0",
            "--",
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "Reply fixture only; do not execute tools.",
        ]
        try:
            result = subprocess.run(
                command, cwd=directory, env=environment, timeout=45, check=False
            )
            if result.returncode or not requests:
                raise RuntimeError(
                    "Pinned CLI did not complete the local-only request fixture"
                )
            value = requests[0]
            # Preserve wire structure, never copy machine paths, global agent
            # instructions, session identifiers or generated prompts into Git.
            for item in value.get("input", []):
                item["id"] = "msg_fixture"
                if isinstance(item.get("content"), list):
                    for part in item["content"]:
                        if "text" in part:
                            part["text"] = "fixture text"
            if "client_metadata" in value:
                value["client_metadata"] = {
                    key: "fixture" for key in value["client_metadata"]
                }
            if "prompt_cache_key" in value:
                value["prompt_cache_key"] = "fixture"

            def sanitize_schema(node):
                if isinstance(node, dict):
                    for key, child in node.items():
                        if key == "description":
                            node[key] = "fixture description"
                        else:
                            sanitize_schema(child)
                elif isinstance(node, list):
                    for child in node:
                        sanitize_schema(child)

            sanitize_schema(value.get("tools", []))
            raw = json.dumps(value, sort_keys=True, indent=2)
            Path(args.output).write_text(raw + "\n")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
