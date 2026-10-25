# Delivery screenshot evidence

Captured from the actual production application and authenticated Grafana UI on **25 October 2026** during the #284 documentation review. Images are browser viewport JPEGs; no mock fixtures or generated UI images are presented as live evidence. Captures were inspected before inclusion for credentials and personal/customer data; visible telemetry is operational route/status/duration/release and correlation metadata.

The source audit baseline is `8895b99a549ee0db134cec69bd681618f8db46d7`, with [production release run 40181618456](https://github.com/alanlima/pawlocal/actions/runs/40181618456). The application footer displayed `BUILD local`, so these captures cannot independently bind the served frontend bundle to that commit. Dashboard time windows include multiple backend releases. Use exact workflow manifests for release provenance.

## Application

All application images use [production](https://pawlocal.alanlima.cloud/). These are anonymous read-only journeys; no production contribution or favourite was created.

![Discovery: search, area selection and real place cards](production-discovery-2026-10-25.jpg)

*Discovery displayed 51 listings at capture time.*

![Dog parks category and facility controls](production-filters-2026-10-25.jpg)

*Dog parks returned 17 listings; Filters exposes verified-only facility choices. Counts can change.*

![Place details with access information and unknown facilities](production-place-detail-2026-10-25.jpg)

*Baringa Dog Park, permanent path `/places/99fa90f5-d755-5ee7-ab93-0818d5810cef`. Facts belong to the published listing; this capture is not a new verification of council rules.*

![Share action confirmation on the place page](production-place-share-2026-10-25.jpg)

*Share this place displayed “Link copied — ready to share!”.*

![Anonymous save prompts sign-in](production-sign-in-required-2026-10-25.jpg)

*Anonymous Save displayed “Sign in to save favourites.” This proves the UI boundary, not authenticated persistence. Fresh signed-in contribution/favourite screenshots remain pending.*

## Grafana dashboards

![Production application metrics and safe logs](grafana-production-application-2026-10-25.jpg)

*[Application dashboard](https://alanlima.grafana.net/d/pawlocal-production-application): last six hours, all releases. Request volume, p95 route latency, status classes and actual structured logs are visible. A trace ID in a log is not proof that its trace was retrieved or correlated with the browser journey.*

![Production incident dashboard with visible data gaps](grafana-production-incidents-2026-10-25.jpg)

*[Incident dashboard](https://alanlima.grafana.net/d/pawlocal-production-incidents): last hour, all releases. The external journey panel shows `NO DATA / UNKNOWN`; related traces shows “No data found in response”; metrics/logs do not establish complete monitoring acceptance. Grafana URLs require authorized stack access; these checked-in images remain the public evidence.*

## Incident demonstration

The existing [drill 02 wiki](https://github.com/alanlima/pawlocal/wiki/Incident-drill-2026-10-25-02) contains 19 inspected screenshots with timestamps, both attempts and exact run/PR links. [#396](https://github.com/alanlima/pawlocal/issues/396) records automatic repair and observed recovery; [#399](https://github.com/alanlima/pawlocal/issues/399) remains `RELEASE_COMPLETED_UNVERIFIED` because enforcement was disabled. See the [delivery plan](../../submission.md) for acceptance gaps and final release binding.
