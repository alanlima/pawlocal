export function getBuildIdentity(commit?: string, buildTime?: string): string {
  const fullCommit = commit?.trim()
  const timestamp = buildTime?.trim()

  if (!fullCommit || !/^[a-f0-9]{40}$/i.test(fullCommit) || !timestamp || !/Z$/i.test(timestamp)) {
    return 'BUILD local'
  }

  const parsedTime = new Date(timestamp)
  if (Number.isNaN(parsedTime.getTime())) return 'BUILD local'

  const utcTime = parsedTime.toISOString().slice(0, 16).replace('T', ' ')
  return `BUILD ${fullCommit.slice(0, 7)} · ${utcTime} UTC`
}

export const buildIdentity = getBuildIdentity(
  import.meta.env.VITE_APP_COMMIT,
  import.meta.env.VITE_APP_BUILD_TIME,
)
