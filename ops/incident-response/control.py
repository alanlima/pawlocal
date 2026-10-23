"""Live owner stop through existing ledger/incident resources; read-only."""

import time

from quota import Denied, integer

LEDGER = "<!-- pawlocal-oncall-quota:v1 -->"
INCIDENT = "<!-- pawlocal-incident:v1:"


def check_ledger(reader, quota_issue, deadline, clock=time.time):
    integer(quota_issue)
    if clock() >= deadline:
        raise Denied("live work deadline exhausted")
    ledger = reader("/issues/" + str(quota_issue))
    if (
        ledger.get("state") != "open"
        or ledger.get("user", {}).get("login") != "alanlima"
        or not ledger.get("body", "").startswith(LEDGER)
        or clock() >= deadline
    ):
        raise Denied("live global quota/stop authority revoked")


class LiveControl:
    def __init__(self, reader, metadata, deadline, clock=time.time):
        self.reader, self.metadata, self.deadline, self.clock = (
            reader,
            metadata,
            deadline,
            clock,
        )
        integer(metadata.get("quota_issue"))
        integer(metadata.get("issue"))

    def check(self):
        if self.clock() >= self.deadline:
            raise Denied("live work deadline exhausted")
        check_ledger(
            self.reader, self.metadata["quota_issue"], self.deadline, self.clock
        )
        issue = self.reader("/issues/" + str(self.metadata["issue"]))
        marker = INCIDENT + self.metadata["alert"]["incident_key"] + " -->"
        if (
            issue.get("state") != "open"
            or issue.get("user", {}).get("login") != "github-actions[bot]"
            or marker not in issue.get("body", "")
        ):
            raise Denied("live incident lease closed or changed")
        if self.clock() >= self.deadline:
            raise Denied("live work deadline exhausted")
