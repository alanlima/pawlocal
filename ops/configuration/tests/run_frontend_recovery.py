"""Prepare public configurations for the real frontend recovery fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from test_integration import (
    SENTINEL,
    FakeAPI,
    mappings,
    module,
    store_for,
    values,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument(
        "--environment", choices=("development", "production"), default="development"
    )
    args = parser.parse_args()
    selected, api = mappings(args.environment), FakeAPI()
    github = module.GitHub("alanlima/pawlocal", SENTINEL, api)
    old = values(args.environment)
    old["VITE_COGNITO_CLIENT_ID"] = "oldfixtureclient"
    old["VITE_COGNITO_DOMAIN"] = (
        f"https://pawlocal-{args.environment}-old.auth.ap-southeast-2.amazoncognito.com"
    )
    first = module.reconcile(
        selected,
        store_for(selected, old),
        github,
        lambda _: None,
        mode="enforce",
        environment=args.environment,
        selection="all",
    )
    replacement = values(args.environment)
    replacement["VITE_COGNITO_CLIENT_ID"] = "replacementfixtureclient"
    replacement["VITE_COGNITO_DOMAIN"] = (
        f"https://pawlocal-{args.environment}-replacement.auth.ap-southeast-2.amazoncognito.com"
    )
    second = module.reconcile(
        selected,
        store_for(selected, replacement),
        github,
        lambda _: None,
        mode="enforce",
        environment=args.environment,
        selection="all",
    )
    args.output_directory.mkdir(parents=True, exist_ok=True)
    for name, result in (("old", first), ("replacement", second)):
        path = args.output_directory / f"{name}.json"
        path.write_text(
            json.dumps(module.configuration_outputs(result, "all")["frontend_config"]),
            encoding="utf-8",
        )
    print("Prepared old/replacement public configuration fixtures.")


if __name__ == "__main__":
    main()
