from datetime import UTC, datetime, timedelta

from pawlocal.infrastructure.aws_credentials import AssumeRoleCredentialProvider


class FakeStsClient:
    def __init__(self):
        self.calls = 0

    def assume_role(self, **request):
        self.calls += 1
        assert request["RoleArn"] == "arn:aws:iam::123456789012:role/pawlocal-dsql"
        assert request["RoleSessionName"] == "pawlocal-dsql-runtime"
        return {
            "Credentials": {
                "AccessKeyId": f"access-{self.calls}",
                "SecretAccessKey": f"secret-{self.calls}",
                "SessionToken": f"session-{self.calls}",
                "Expiration": datetime.now(UTC) + timedelta(hours=1),
            }
        }


class FakeSourceSession:
    def __init__(self):
        self.sts = FakeStsClient()

    def client(self, service_name):
        assert service_name == "sts"
        return self.sts


def test_assume_role_provider_caches_credentials_and_refreshes_them():
    source_session = FakeSourceSession()
    provider = AssumeRoleCredentialProvider(
        "arn:aws:iam::123456789012:role/pawlocal-dsql",
        source_session=source_session,
    )

    credentials = provider.load()
    assert credentials.get_frozen_credentials().access_key == "access-1"
    assert source_session.sts.calls == 1

    # Simulate the SDK's normal expiry refresh boundary without waiting for STS.
    credentials._expiry_time = datetime.now(UTC) - timedelta(seconds=1)
    assert credentials.get_frozen_credentials().access_key == "access-2"
    assert source_session.sts.calls == 2
    assert provider.load() is credentials


def test_assume_role_provider_rejects_non_role_arn():
    from pawlocal.infrastructure.aws_credentials import (
        create_assume_role_credentials_provider,
    )

    try:
        create_assume_role_credentials_provider("not-a-role")
    except ValueError as error:
        assert "must identify an IAM role" in str(error)
    else:
        raise AssertionError("Expected invalid role ARN to fail")
