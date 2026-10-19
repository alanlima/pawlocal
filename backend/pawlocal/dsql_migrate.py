"""Apply the initial clean-install Aurora DSQL schema before API startup."""

from sqlalchemy import Engine

from pawlocal.dsql_migrations import apply_dsql_baseline
from pawlocal.infrastructure.database import engine


def run_dsql_migrations(database_engine: Engine) -> bool:
    """Apply the DSQL baseline; return False when it is already recorded."""
    if database_engine.dialect.name != "auroradsql":
        raise RuntimeError(
            "The DSQL baseline command requires an Aurora DSQL database URL."
        )
    return apply_dsql_baseline(database_engine)


def main() -> None:
    try:
        applied = run_dsql_migrations(engine)
    finally:
        engine.dispose()
    print(
        "Aurora DSQL baseline applied."
        if applied
        else "Aurora DSQL baseline is already applied."
    )


if __name__ == "__main__":
    main()
