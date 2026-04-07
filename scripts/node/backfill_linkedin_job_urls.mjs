import { DatabaseSync } from 'node:sqlite'

const dbPath = process.argv[2] || 'input/crawled_job/linkedin_jobs_jd.sqlite'
const db = new DatabaseSync(dbPath)

function extractJobId(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  if (/^\d+$/.test(text)) return text
  try {
    const url = new URL(text)
    const currentJobId = url.searchParams.get('currentJobId')
    if (currentJobId && /^\d+$/.test(currentJobId)) return currentJobId
    const match =
      url.pathname.match(/\/jobs\/view\/(?:[^/?#]*-)?(\d+)(?:\/)?/i) ||
      url.pathname.match(/\/jobPosting\/(\d+)/i)
    return match ? match[1] : ''
  } catch {
    return ''
  }
}

function canonicalJobId(...values) {
  for (const value of values) {
    const jobId = extractJobId(value)
    if (jobId) return jobId
    const text = String(value || '').trim()
    if (/^\d+$/.test(text)) return text
  }
  return ''
}

function canonicalJobUrl(...values) {
  const jobId = canonicalJobId(...values)
  if (jobId) return `https://www.linkedin.com/jobs/view/${jobId}/`
  for (const value of values) {
    const text = String(value || '').trim()
    if (text) return text
  }
  return ''
}

const rows = db.prepare(`
  SELECT id, linkedin_job_id, job_url, job_url_final
  FROM job_posts
  ORDER BY id
`).all()

const update = db.prepare(`
  UPDATE job_posts
  SET linkedin_job_id = ?, job_url_final = ?, updated_at = CURRENT_TIMESTAMP
  WHERE id = ?
`)

let changed = 0
let unchanged = 0
let unresolved = 0

db.exec('BEGIN')
try {
  for (const row of rows) {
    const linkedinJobId = canonicalJobId(row.job_url_final, row.job_url, row.linkedin_job_id)
    const jobUrlFinal = canonicalJobUrl(row.job_url_final, row.job_url, row.linkedin_job_id)
    if (!linkedinJobId) {
      unresolved += 1
      continue
    }
    const oldId = String(row.linkedin_job_id || '').trim()
    const oldFinal = String(row.job_url_final || '').trim()
    if (oldId === linkedinJobId && oldFinal === jobUrlFinal) {
      unchanged += 1
      continue
    }
    update.run(linkedinJobId, jobUrlFinal, row.id)
    changed += 1
  }
  db.exec('COMMIT')
} catch (error) {
  db.exec('ROLLBACK')
  throw error
}

const summary = db.prepare(`
  SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN COALESCE(linkedin_job_id, '') <> '' THEN 1 ELSE 0 END) AS with_linkedin_job_id,
    SUM(CASE WHEN COALESCE(job_url_final, '') LIKE 'https://www.linkedin.com/jobs/view/%/' THEN 1 ELSE 0 END) AS canonical_urls
  FROM job_posts
`).get()

console.log(JSON.stringify({
  dbPath,
  changed,
  unchanged,
  unresolved,
  summary,
}, null, 2))
