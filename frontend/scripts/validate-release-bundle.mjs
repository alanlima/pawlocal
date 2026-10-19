import { readFile, readdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const demoDataFiles = ['src/data/demo-places.ts', 'src/data/demo-contributions.ts']
const assetDirectory = resolve('dist/assets')
const assets = await readdir(assetDirectory)
const bundles = await Promise.all(
  assets.map(async (asset) => readFile(resolve(assetDirectory, asset), 'utf8')),
)
const demoRecordIds = new Set()

for (const file of demoDataFiles) {
  const source = await readFile(resolve(file), 'utf8')
  for (const match of source.matchAll(/id:\s*'([^']+)'/g)) demoRecordIds.add(match[1])
}

const leakedIds = [...demoRecordIds].filter((id) => bundles.some((bundle) => bundle.includes(id)))
if (leakedIds.length > 0) {
  throw new Error('Production frontend assets contain mock/demo records')
}

console.log('Verified production frontend assets contain no mock/demo record IDs.')
