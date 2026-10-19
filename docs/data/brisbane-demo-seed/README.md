# Brisbane demo seed

This one-off dataset contains two published dog park listings for demonstrating PawLocal's cloud environments. Listing content is limited to the cited Brisbane City Council pages. Facilities are empty and average ratings are unset because the cited sources do not establish those values. The listings are not user reviews or popularity claims.

Sources checked 2026-10-19:

- [Orleigh Park — Brisbane City Council](https://www.brisbane.qld.gov.au/parks-and-recreation/parks-and-greenspaces/book-a-park-site/orleigh-park): address 68 Hill End Terrace, West End Qld 4101; page identifies an off-leash dog park.
- [Whites Hill Reserve — Brisbane City Council](https://www.brisbane.qld.gov.au/parks-and-recreation/bushland-and-wetlands/find-reserves-and-forests/whites-hill-reserve): address 258 Boundary Road, Camp Hill Qld 4152; page identifies a dog park, permits dogs on leash in the reserve, and allows off-leash access only in the dog park.

Run from `backend/` only after migrations have been applied and the deployment environment has the intended `PAWLOCAL_DATABASE_URL` and AWS SDK credentials:

```powershell
python -m pawlocal.seed_places --environment development
python -m pawlocal.seed_places --environment production --confirm-production
```

The source of truth is [`backend/data/seed_places.json`](../../../backend/data/seed_places.json), which is copied into the backend container image at `/app/data/seed_places.json`. The command can use this default or accept a different catalog with `--catalog`. It requires an Aurora DSQL URL whose host exactly matches the environment-scoped `PAWLOCAL_EXPECTED_DSQL_ENDPOINT` allowlist and whose `application_name` is exactly `pawlocal-development` or `pawlocal-production`, matching the selected environment. Configure the expected endpoint from the matching Terraform `environment_targets` output separately from `PAWLOCAL_DATABASE_URL`; this prevents a production URL with a development application name from passing the guard. It refuses PostgreSQL, an unset allowlist, and mismatched targets. Production additionally requires the explicit confirmation flag.

Each listing uses a stable UUID. Re-running the command inserts missing IDs or updates the catalog-owned fields (`name`, `category`, `area`, `address`, `description`, `dog_access_rules`, `facilities`, and `is_published`). Ratings and source timestamps are preserved. Rows removed from the catalog are never deleted or unpublished. A name collision with a different ID fails before writing. The command verifies every catalog row after the updates. On Aurora DSQL, the connection must resolve `current_schema()` to `pawlocal`, the schema read by the API. Updating a non-empty facilities list also writes `pawlocal.place_facilities`; the seeding identity therefore needs access to both application tables. This README documents the command; it does not authorize or claim a cloud seed run.
