// Optional high-resolution raster export; SVG layout sources use Python stdlib only.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../../../..');
const { Resvg } = require(path.join(root, '.tmp/architecture-render/node_modules/@resvg/resvg-js'));
for (const name of ['architecture-end-to-end', 'architecture-operations-cicd']) {
  const stem = path.join(__dirname, '..', name);
  const renderer = new Resvg(fs.readFileSync(stem + '.svg', 'utf8'), {
    fitTo: { mode: 'width', value: 3200 },
    font: { loadSystemFonts: true, defaultFontFamily: 'Segoe UI' },
    background: 'white',
  });
  const png = renderer.render().asPng();
  fs.writeFileSync(stem + '.png', png);
  process.stdout.write(`${name}.png: ${png.length} bytes\n`);
}
