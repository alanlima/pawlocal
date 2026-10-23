"""Exercise the pinned CLI's writable home boundary using a different real UID."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(
    os.name == "posix", "Real UID/sticky directory semantics require Ubuntu"
)
class CodexHomeTests(unittest.TestCase):
    def test_operational_writes_cannot_change_trusted_config_or_parent_home(self):
        import pwd

        identity = pwd.getpwnam("nobody")
        if os.getuid() == identity.pw_uid:
            self.skipTest("Fixture needs a distinct model UID")
        prefix = [] if os.getuid() == 0 else ["sudo", "-n", "-u", "nobody"]
        if prefix and (
            not shutil.which("sudo")
            or subprocess.run(
                ["sudo", "-n", "-u", "nobody", "true"], capture_output=True, check=False
            ).returncode
        ):
            self.skipTest("Hosted Ubuntu passwordless sudo or root required")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o755)
            home = root / ".codex"
            home.mkdir(mode=0o1777)
            home.chmod(0o1777)  # Do not let umask remove the sticky/write bits.
            config = home / "config.toml"
            config.write_text('web_search = "disabled"\n')
            config.chmod(0o644)
            script = r"""
import json, pathlib, sys
root = pathlib.Path(sys.argv[1]); home = root / '.codex'; config = home / 'config.toml'
(home / 'installation_id').write_text('fixture')
(home / '.tmp-operational').write_text('fixture')
blocked = []
for name, operation in (
    ('write', lambda: config.write_text('changed')),
    ('unlink', lambda: config.unlink()),
    ('rename', lambda: config.rename(home / 'config-moved')),
    ('replace', lambda: (home / '.tmp-operational').replace(config)),
    ('parent-write', lambda: (root / 'config.toml').write_text('changed')),
    ('home-rename', lambda: home.rename(root / '.codex-replaced')),
):
    try: operation()
    except PermissionError: blocked.append(name)
print(json.dumps(blocked))
"""

            def drop_uid():
                os.setgroups([])
                os.setgid(identity.pw_gid)
                os.setuid(identity.pw_uid)

            result = subprocess.run(
                prefix + ["/usr/bin/python3", "-c", script, str(root)],
                preexec_fn=drop_uid if os.getuid() == 0 else None,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(
                json.loads(result.stdout),
                ["write", "unlink", "rename", "replace", "parent-write", "home-rename"],
            )
            self.assertEqual(config.read_text(), 'web_search = "disabled"\n')
            self.assertEqual(home.stat().st_uid, os.getuid())
            self.assertEqual(config.stat().st_uid, os.getuid())


if __name__ == "__main__":
    unittest.main()
