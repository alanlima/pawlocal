"""Absolute process deadline and process-group cleanup for trusted jobs."""

import os
import signal
import subprocess
import time

from quota import Denied

DEADLINE = None
GROUPS = set()


def arm(value, maximum=1200):
    global DEADLINE
    value = int(value)
    if os.name != "posix" or not 0 < value - time.time() <= maximum <= 3600:
        raise Denied("absolute admission work deadline required")
    DEADLINE = value

    def terminate(*_args):
        for group in tuple(GROUPS):
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        os._exit(124)

    signal.signal(signal.SIGALRM, terminate)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, value - time.time()))


def run(command, *, input=None, stdout=None, check=False, timeout=None, **kwargs):
    allowed = None if DEADLINE is None else DEADLINE - time.time()
    if allowed is not None and allowed <= 0:
        raise Denied("work deadline exhausted")
    if timeout is not None:
        allowed = timeout if allowed is None else min(timeout, allowed)
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE if input is not None else None,
        stdout=stdout,
        start_new_session=True,
        **kwargs,
    )
    GROUPS.add(process.pid)
    try:
        output, errors = process.communicate(input=input, timeout=allowed)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise
    finally:
        GROUPS.discard(process.pid)
    result = subprocess.CompletedProcess(command, process.returncode, output, errors)
    if check:
        result.check_returncode()
    return result
