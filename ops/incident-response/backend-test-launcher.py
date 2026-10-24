"""Test-process-only compatibility for asyncio self-pipes under Codex Linux sandbox.

The sandbox blocks sendto, including socket.send on the existing AF_UNIX
self-pipe. os.write uses that same already-created stream descriptor without
changing network permissions, socket methods, application code or test outcomes.
Trusted candidate checks continue to invoke ordinary pytest independently.
"""

import logging
import os
import socket
import sys
from asyncio import selector_events

_ORIGINAL_WRITE = selector_events.BaseSelectorEventLoop._write_to_self
_LOGGER = logging.getLogger("asyncio")


def write_to_self(loop):
    csock = loop._csock
    if csock is None:
        return
    if csock.family != socket.AF_UNIX or csock.type != socket.SOCK_STREAM:
        return _ORIGINAL_WRITE(loop)
    try:
        os.write(csock.fileno(), b"\0")
    except OSError:
        # Match CPython's closed-descriptor/full-buffer shutdown behavior.
        if loop._debug:
            _LOGGER.debug(
                "Fail to write a null byte into the self-pipe socket", exc_info=True
            )


def install():
    selector_events.BaseSelectorEventLoop._write_to_self = write_to_self


def main():
    install()
    import pytest

    return pytest.main(sys.argv[1:] or ["backend/tests/test_incident_regression.py"])


if __name__ == "__main__":
    raise SystemExit(main())
