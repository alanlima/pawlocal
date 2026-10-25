# Architecture artwork sources

The two architecture images are custom, hand-positioned vector layouts. No Mermaid or automatic graph layout is used. PNGs are the README display assets; SVGs provide a scalable copy with accessible titles and descriptions. The Python builders and optional renderer are one-off artwork helpers; finished images display directly and have no application or workflow dependency.

From the repository root, regenerate the vectors with Python's standard library. Regeneration requires HTTPS access to `cdn.jsdelivr.net` for the eight AWS service icons; viewing the checked-in SVG/PNG images requires no network. The shared `icon_assets.py` loader uses commit-pinned URLs, verifies each asset against its SHA-256 manifest and caches bytes only in process memory. Download, HTTP or integrity failures stop generation; there is no local AWS fallback or persistent icon cache:

```powershell
python docs/images/delivery/source/end-to-end.py
python docs/images/delivery/source/operations.py
```

Optional 3200-pixel PNG export uses the pinned resvg renderer installed in a disposable workspace directory; it adds no application dependency:

```powershell
npm install --prefix .tmp/architecture-render --no-audit --no-fund @resvg/resvg-js@2.6.2
node docs/images/delivery/source/render.cjs
```

The layout uses Segoe UI with an Arial fallback. Font availability can affect raster output across operating systems. Inspect both exported images after changes, including arrow routes, labels, environment boundaries and README rendering. The diagrams describe capabilities; current runtime evidence and acceptance limitations remain in the README captions and delivery plan.

## Icon sources

- AWS service artwork originates in [official AWS Architecture Icons](https://aws.amazon.com/architecture/icons/). The builders fetch it through the third-party [phergoualch/aws-icons CDN mirror](https://github.com/phergoualch/aws-icons/tree/ec5b8422f1a48621bff6eebd1d4a270cf51dc70d), served by jsDelivr at exact commit `ec5b8422f1a48621bff6eebd1d4a270cf51dc70d`. This mirror is not an AWS-operated CDN. On 25 October 2026 all eight CDN assets returned HTTP 200 and matched the drawing geometry/colors of the [31 July 2026 official package](https://d1.awsstatic.com/onedam/marketing-channels/website/public/shared/architecture-icon-release/Icon-package_07312026.5846e92413caa21490223536cc97f1269e44fa92.zip). The exact URL paths and byte digests are in `icon_assets.py`; individual AWS input SVG files are not stored in this repository. Finished SVGs inline the verified shapes with preserved colors/aspect ratios and prefixed IDs. Aurora DSQL uses the official Amazon Aurora family icon with an explicit DSQL label.
- GitHub, Terraform, Grafana, React and Docker glyphs: [Simple Icons](https://github.com/simple-icons/simple-icons), retrieved 25 October 2026 from its `develop/icons/` directory. These five non-AWS glyphs remain local in `icons/`; original path geometry is retained with the brand fill applied. Simple Icons distributes its artwork under [CC0](https://github.com/simple-icons/simple-icons/blob/develop/LICENSE.md); brand marks remain subject to their owners' trademark policies.
- Generic package, check and model symbols are drawn directly in the layout source. They are not AWS service icons.

AWS supplies these service assets for architecture diagrams. Product names and marks belong to their respective owners; these diagrams do not imply endorsement. Boundaries represent logical environment, service and process ownership. They do not assert separate AWS accounts, VPC/subnet isolation, high availability or proof that every depicted journey has passed live acceptance.
