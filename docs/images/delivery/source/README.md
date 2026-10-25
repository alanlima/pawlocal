# Architecture artwork sources

The two architecture images are custom, hand-positioned vector layouts. No Mermaid or automatic graph layout is used. PNGs are the README display assets; SVGs provide a scalable copy with accessible titles and descriptions.

From the repository root, regenerate the vectors with Python's standard library:

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

- AWS service artwork: [official AWS Architecture Icons](https://aws.amazon.com/architecture/icons/), [31 July 2026 asset package](https://d1.awsstatic.com/onedam/marketing-channels/website/public/shared/architecture-icon-release/Icon-package_07312026.5846e92413caa21490223536cc97f1269e44fa92.zip), retrieved 25 October 2026. Original SVG files are retained in `icons/`; inline copies preserve their shapes, colors and aspect ratios. IDs are prefixed where needed to keep repeated instances distinct. Aurora DSQL uses the official Amazon Aurora family icon with an explicit DSQL label.
- GitHub, Terraform, Grafana, React and Docker glyphs: [Simple Icons](https://github.com/simple-icons/simple-icons), retrieved 25 October 2026 from its `develop/icons/` directory. Original path geometry is retained with the brand fill applied. Simple Icons distributes its artwork under [CC0](https://github.com/simple-icons/simple-icons/blob/develop/LICENSE.md); brand marks remain subject to their owners' trademark policies.
- Generic package, check and model symbols are drawn directly in the layout source. They are not AWS service icons.

AWS supplies these service assets for architecture diagrams. Product names and marks belong to their respective owners; these diagrams do not imply endorsement. Boundaries represent logical environment, service and process ownership. They do not assert separate AWS accounts, VPC/subnet isolation, high availability or proof that every depicted journey has passed live acceptance.
