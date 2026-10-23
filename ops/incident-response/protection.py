"""Read-only classic-protection absence proof using a locally minted capability."""

import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from quota import Denied, strict_json
from quota_gateway import NoRedirect

ORIGIN = "https://api.github.com/repos/alanlima/pawlocal"


def classic_absent(deadline, *, path=None, opener=None):
    path = path or Path(os.environ["RUNNER_TEMP"]) / "oncall-readiness-token.json"
    if (
        path.is_symlink()
        or path.stat().st_mode & 0o077
        or path.stat().st_uid != os.getuid()
    ):
        raise Denied("private protection-reader handoff invalid")
    capability = strict_json(path.read_bytes())
    if (
        set(capability) != {"token", "repository_id", "permissions"}
        or capability["repository_id"] != 1423024931
        or capability["permissions"] != {"administration": "read"}
        or not isinstance(capability["token"], str)
        or not 20 <= len(capability["token"]) <= 1024
    ):
        raise Denied(
            "verified exact repository Administration-read capability required"
        )
    transport = opener or urllib.request.build_opener(NoRedirect)

    def read(suffix):
        if suffix not in {"", "/branches/main/protection"} or time.time() >= deadline:
            raise Denied("protection read path/deadline denied")
        request = urllib.request.Request(
            ORIGIN + suffix,
            headers={
                "Authorization": "Bearer " + capability["token"],
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with transport.open(
            request, timeout=min(15, deadline - time.time())
        ) as response:
            raw = response.read(65537)
            if response.status != 200 or len(raw) > 65536:
                raise Denied("protection read acknowledgement unknown")
            return strict_json(raw)

    # A hidden/unauthorized repository 404 is never evidence of absent policy.
    # The token's exact permissions were verified in the mint response before
    # this owner-only handoff; metadata access also proves the selected repo.
    try:
        repository = read("")
    except urllib.error.HTTPError as error:
        raise Denied("protection reader repository access is unproved") from error
    if (
        repository.get("id") != 1423024931
        or repository.get("full_name") != "alanlima/pawlocal"
    ):
        raise Denied("protection reader repository identity differs")
    try:
        read("/branches/main/protection")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return
        raise Denied("classic protection unreadable") from error
    raise Denied(
        "classic protection exists; reviewed canonical ruleset-only setup required"
    )
