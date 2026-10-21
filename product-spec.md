# PawLocal product specification

**Status:** Approved for Stage 1 implementation on 2026-10-17; unresolved design decisions remain open for their relevant later stages.

**Scope:** MVP only; future scope requires explicit approval.

## Problem and audience

Dog owners in South East Queensland have difficulty finding current, reliable information about places that welcome dogs, including access rules, facilities and restrictions. PawLocal gives anonymous visitors a searchable directory and lets registered users improve it through contributions.

## MVP requirements

### Discovery and place details

- Visitors can browse dog parks, beaches, walks, hiking areas and pet-friendly cafes.
- Visitors can search and filter by location, category and facilities.
- Search results communicate loading, error and empty states.
- Each published place has a stable public URL and a detail view.
- Details show available information such as address/area, category, dog-access rules, facilities, description and contribution freshness. Unknown facts are identified as unknown rather than inferred.
- A place can be shared through its permanent URL.

### Community contributions

- Registered users can save and remove favourites.
- Registered users can submit a rating and review, suggest a location, and publish a tip or correction.
- Contributions are validated and protected against abuse; accepted contributions publish immediately, subject to reporting and moderation workflows.
- Users can report inaccurate or inappropriate content.
- The system prevents duplicate ratings/reviews by the same user for the same place, according to the final interaction design.
- Authentication and authorization are required for contribution and favourite operations.

### AI-assisted drafts

- AI may prepare listing drafts from permitted public sources.
- A human must verify every generated draft before it can be published.
- AI must not invent a place, facility or dog-access rule. Provenance and uncertainty must be retained for review.
- AI draft generation is not a user-facing MVP workflow until source permissions, quotas and review controls are specified and approved.

## Quality and operational requirements

- Responsive, accessible UI; keyboard and screen-reader use must be considered.
- Frontend code calls typed service interfaces; mock and HTTP adapters are interchangeable.
- Backend boundaries separate HTTP, application use cases, domain rules and persistence.
- Public browsing is available without authentication. Sensitive personal information is excluded from logs and traces.
- Validate submissions, rate-limit write operations and enforce authorization on the backend.
- Instrument the path **search → API → database → place details** with correlated traces, structured logs, latency/error metrics and user-impact indicators.
- Keep low-traffic operating costs low. Compare hosting options and estimate recurring costs before proposing production hosting.
- No billable cloud resource may be provisioned without explicit human approval.

## MVP acceptance criteria

1. A visitor can search and filter published places by area, category and facilities and see loading, empty and error states.
2. A visitor can open a place detail page and share a permanent URL that resolves to that place.
3. A registered user can add/remove a favourite and submit a rating/review, a location suggestion, or a tip/correction; anonymous write attempts are rejected.
4. A user can report a place or contribution; reports are recorded for moderation without exposing reporter details publicly.
5. Invalid or abusive write requests are rejected or rate-limited, and duplicate ratings/reviews are prevented.
6. Every public place field is backed by supplied or verified information; unknown access/facility facts are not guessed.
7. If AI drafts are enabled, they remain unpublished until human approval and retain source/provenance information.
8. Core search-to-detail behavior is covered by automated tests, containerized, and observable before production readiness is claimed.

## Out of scope without explicit approval

Any feature not listed above, including payments, bookings, messaging, advertising, native mobile apps, recommendations/personalization, or automated publication of AI content.

## Approved MVP discovery taxonomy

Use the current frontend vocabulary as the approved MVP taxonomy for Stage 3 filters and persistence:

- **Place categories:** `dog_park`, `beach`, `walk`, `hiking_area`, `cafe`.
- **Facilities:** `Fenced`, `Off-leash area`, `Drinking water`, `Shade`, `Picnic tables`, `Accessible paths`.
- **Area labels:** Use curated, human-readable South East Queensland labels. The current UI examples are `Brisbane City`, `Brisbane North`, `Gold Coast`, `Moreton Bay`, and `Sunshine Coast`; this list is not exhaustive. Filter by exact label; labels do not define precise geographic boundaries, and the API must not infer coordinates or radius membership from them.
- **Unknown facts:** Store unverified access rules and facilities as unknown/absent; do not infer them. A broader freshness and verification policy remains open.

Stage 3 must use these values consistently across API validation, persistence and frontend adapters. See `docs/decisions.md` DEC-003 and `openapi.yaml`.

## Decisions still needed before implementation

- Broader freshness and verification policy for place data.
- Identity lifecycle beyond the Stage 3 authentication integration (signup/sign-in UX, recovery, account deletion and retention, and social federation). Stage 3 does not add deletion, retention, or federation behavior without a separate decision.
- Moderation roles and report resolution process.
- Rating/review revision and removal behavior.
- Permitted source policy and AI-draft operator workflow.

## Approved Stage 3 decisions

- **Identity provider:** Use an Amazon Cognito User Pool as the OIDC issuer for Stage 3 protected API operations. The API accepts user-pool access tokens and validates them as specified in `docs/specs/backend-api-persistence.md` and `openapi.yaml`. No Cognito pool or other AWS resource is provisioned as part of Stage 3.
- **Reportable contributions:** The report dialog uses the public, paginated `GET /contributions/reportable` operation for already-published contributions. The response contains only public fields needed to identify the report target and does not include contributor or reporter identity. See `docs/decisions.md` DEC-002.

