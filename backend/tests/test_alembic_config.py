from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]


def test_release_manifest_resolves_migration_head_from_repository_root(
    monkeypatch,
) -> None:
    monkeypatch.chdir(ROOT)

    scripts = ScriptDirectory.from_config(Config("backend/alembic.ini"))

    assert Path(scripts.dir).resolve() == ROOT / "backend" / "migrations"
    assert len(scripts.get_heads()) == 1
