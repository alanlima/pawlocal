// Inspect the rendered footer against the artifact built by this release job.
export async function verifyServedBuildIdentity(page, commit, buildTime) {
  if (
    !/^[a-f0-9]{40}$/i.test(commit ?? '') ||
    !buildTime ||
    Number.isNaN(Date.parse(buildTime)) ||
    !/Z$/.test(buildTime)
  ) {
    throw new Error('Missing expected frontend build identity')
  }
  const timestamp = new Date(buildTime).toISOString().slice(0, 16).replace('T', ' ')
  const expected = `BUILD ${commit.slice(0, 7)} \u00b7 ${timestamp} UTC`
  await page
    .getByRole('contentinfo')
    .getByText(expected, { exact: true })
    .waitFor({ state: 'visible', timeout: 15000 })
}
