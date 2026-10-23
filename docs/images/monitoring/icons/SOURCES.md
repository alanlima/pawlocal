# Diagram integration icon sources

Downloaded 23 October 2026. These files are unmodified source assets embedded as base64 images in the self-contained diagram SVGs. Product marks remain the property of their respective owners; this draft does not relicense them.

- **AWS Architecture Icons**: official [architecture icon page](https://aws.amazon.com/architecture/icons/) and [July 2026 icon ZIP](https://d1.awsstatic.com/onedam/marketing-channels/website/public/shared/architecture-icon-release/Icon-package_07312026.5846e92413caa21490223536cc97f1269e44fa92.zip). Only selected service SVGs from `64/` directories were extracted; macOS metadata was excluded. The applicable AWS usage guidance is linked from the official page.
- **Grafana**: [official Grafana repository icon](https://raw.githubusercontent.com/grafana/grafana/main/public/img/grafana_icon.svg), with [Grafana trademark policy](https://grafana.com/trademark-policy/).
- **GitHub**: [official GitHub Mark](https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png), with [GitHub logo usage guidance](https://github.com/logos).


Regenerate the editable SVGs with `python docs/images/monitoring/generate-stage5-diagrams.py`. Rasterize with an SVG-capable image tool (the draft PNGs were rendered with Sharp). The SVGs retain selectable labels, vector connectors, and embedded integration assets, and need no external image URLs to display.
