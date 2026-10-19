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

The command requires an Aurora DSQL URL whose `application_name` is exactly `pawlocal-development` or `pawlocal-production`, matching the selected environment. It refuses PostgreSQL and mismatched targets. Production additionally requires the explicit confirmation flag. Each listing uses a stable UUID; the command inserts missing records in separate transactions, accepts an existing record only when all seeded content matches exactly, and stops on an ID or name conflict. It does not update or delete existing data, and verifies both records after insertion. This README documents the command; it does not authorize or claim a cloud seed run.
