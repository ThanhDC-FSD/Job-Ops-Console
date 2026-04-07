const path = require("path");
const Database = require(path.resolve(__dirname, "../../tmp_sqlite_tools/node_modules/better-sqlite3"));

const dbPath = path.resolve(__dirname, "../../input/crawled_job/linkedin_jobs_jd.sqlite");
const db = new Database(dbPath);
db.pragma("journal_mode = WAL");
db.pragma("busy_timeout = 30000");
const jobIdFilter = String(process.env.JOB_ID_FILTER || "").trim();
const runId = String(process.env.JOB_OPS_RUN_ID || "").trim() || new Date().toISOString().replace(/[-:]/g, "").slice(0, 15);
const COMPONENT = "Crawl.BackfillMissingJD";

function log(level, event, payload = {}) {
  const ts = new Date().toISOString();
  const jobId = payload.job_id ?? "-";
  const message = payload.message ? String(payload.message) : "-";
  const line = `ts=${ts} level=${String(level).toUpperCase()} component=${COMPONENT} event=${event || "-"} run_id=${runId} trace_id=- job_id=${jobId} message="${message}"`;
  if (payload && Object.keys(payload).length) {
    console[level](line, payload);
  } else {
    console[level](line);
  }
}

function decodeHtmlEntities(text) {
  return String(text || "")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/&#x2013;|&#8211;/gi, "–")
    .replace(/&#x2014;|&#8212;/gi, "—");
}

function cleanText(text) {
  return decodeHtmlEntities(String(text || ""))
    .replace(/â€“/g, "–")
    .replace(/â€”/g, "—")
    .replace(/Â/g, "")
    .replace(/\r/g, "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function stripHtml(html) {
  return cleanText(
    String(html || "")
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<\/li>/gi, "\n")
      .replace(/<li[^>]*>/gi, "• ")
      .replace(/<\/p>/gi, "\n")
      .replace(/<\/(div|section|article|ul|ol|h1|h2|h3|h4|h5|h6)>/gi, "\n")
      .replace(/<[^>]+>/g, " ")
  );
}

function extractMetaContent(html, attr, name) {
  const re = new RegExp(`<meta[^>]+${attr}=["']${name}["'][^>]+content=["']([\\s\\S]*?)["'][^>]*>`, "i");
  const match = html.match(re);
  if (match) return cleanText(match[1]);
  const reRev = new RegExp(`<meta[^>]+content=["']([\\s\\S]*?)["'][^>]+${attr}=["']${name}["'][^>]*>`, "i");
  const matchRev = html.match(reRev);
  return matchRev ? cleanText(matchRev[1]) : "";
}

function extractDescriptionMarkup(html) {
  const match = html.match(/<div class="show-more-less-html__markup[\s\S]*?>([\s\S]*?)<\/div>/i);
  if (match) return stripHtml(match[1]);
  return "";
}

function normalizeFlags(title, payload, jdText) {
  const sample = [
    title,
    jdText,
    payload.description,
    payload.about_job,
    payload.meta_description,
    payload.og_description,
    payload.twitter_description,
    ...(Array.isArray(payload.job_type_tags) ? payload.job_type_tags : []),
  ]
    .filter(Boolean)
    .join("\n")
    .toLowerCase();
  let workModel = "";
  let employmentType = "";
  if (sample.includes("remote")) workModel = "remote";
  else if (sample.includes("hybrid")) workModel = "hybrid";
  else if (sample.includes("on-site") || sample.includes("onsite") || sample.includes("in-office")) workModel = "on_site";

  if (sample.includes("full-time") || sample.includes("full time")) employmentType = "full_time";
  else if (sample.includes("part-time") || sample.includes("part time")) employmentType = "part_time";
  else if (sample.includes("freelance") || sample.includes("freelancer") || sample.includes("contract")) employmentType = "contract";
  else if (sample.includes("internship")) employmentType = "internship";

  const applyUrl = String(payload.apply_url || "").toLowerCase();
  const easyApply = sample.includes("easy apply") || applyUrl.includes("linkedin.com") || applyUrl.includes("easyapply") || applyUrl.includes("onsiteapply") ? 1 : 0;
  return { workModel, employmentType, easyApply };
}

async function fetchText(url) {
  const res = await fetch(url, {
    headers: {
      "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
      "accept-language": "en-US,en;q=0.9",
    },
    redirect: "follow",
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return await res.text();
}

async function main() {
  log("info", "start", { db_path: dbPath });
  const rows = db.prepare(`
    SELECT
      jp.id,
      COALESCE(jp.linkedin_job_id, '') AS linkedin_job_id,
      COALESCE(jp.title, '') AS title,
      COALESCE(jp.job_url_final, jp.job_url, '') AS job_url,
      COALESCE(jp.latest_payload_json, '{}') AS latest_payload_json,
      COALESCE(jp.normalized_work_model, '') AS normalized_work_model,
      COALESCE(jp.normalized_employment_type, '') AS normalized_employment_type,
      COALESCE(jp.normalized_easy_apply, 0) AS normalized_easy_apply,
      jo.id AS observation_id,
      jjc.id AS jd_content_id,
      COALESCE(jjc.jd_text, '') AS jd_text,
      COALESCE(jjc.jd_source, '') AS jd_source
    FROM job_posts jp
    JOIN job_observations jo ON jo.job_post_id = jp.id
    LEFT JOIN job_jd_contents jjc ON jjc.observation_id = jo.id
    WHERE (
      jjc.id IS NULL
      OR LOWER(TRIM(COALESCE(jjc.jd_text, ''))) LIKE 'job context (fallback jd):%'
      OR LOWER(TRIM(COALESCE(jjc.jd_text, ''))) LIKE 'fallback jd:%'
      OR COALESCE(TRIM(jjc.jd_text), '') = ''
    )
    ${jobIdFilter ? "AND COALESCE(jp.linkedin_job_id, '') = ?" : ""}
    ORDER BY jo.id DESC
  `).all(...(jobIdFilter ? [jobIdFilter] : []));

  let scanned = 0;
  let updated = 0;
  for (const row of rows) {
    scanned += 1;
    const url = String(row.job_url || "").trim();
    if (!url) continue;
    try {
      const html = await fetchText(url);
      const description = extractDescriptionMarkup(html);
      const metaDescription = extractMetaContent(html, "name", "description");
      const ogDescription = extractMetaContent(html, "property", "og:description");
      const twitterDescription = extractMetaContent(html, "name", "twitter:description");
      const jdText = description || metaDescription || ogDescription || twitterDescription;
      if (!jdText || jdText.length < 120) continue;

      let payload = {};
      try {
        payload = JSON.parse(String(row.latest_payload_json || "{}"));
      } catch {
        payload = {};
      }
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) payload = {};
      payload.description = description || payload.description || "";
      payload.meta_description = metaDescription || payload.meta_description || "";
      payload.og_description = ogDescription || payload.og_description || "";
      payload.twitter_description = twitterDescription || payload.twitter_description || "";
      payload.jd = jdText;
      payload.jd_source = description ? "job_url_html_detail" : "meta_description";

      const nowIso = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
      const flags = normalizeFlags(row.title, payload, jdText);
      db.prepare(`
        UPDATE job_posts
        SET latest_payload_json = ?,
            normalized_work_model = CASE WHEN COALESCE(TRIM(normalized_work_model), '') = '' THEN ? ELSE normalized_work_model END,
            normalized_employment_type = CASE WHEN COALESCE(TRIM(normalized_employment_type), '') = '' THEN ? ELSE normalized_employment_type END,
            normalized_easy_apply = CASE WHEN COALESCE(normalized_easy_apply, 0) = 0 THEN ? ELSE normalized_easy_apply END,
            updated_at = ?
        WHERE id = ?
      `).run(JSON.stringify(payload), flags.workModel, flags.employmentType, flags.easyApply, nowIso, row.id);

      if (row.jd_content_id) {
        db.prepare(`
          UPDATE job_jd_contents
          SET jd_text = ?, jd_source = ?, updated_at = ?
          WHERE id = ?
        `).run(jdText, payload.jd_source, nowIso, row.jd_content_id);
      } else {
        db.prepare(`
          INSERT INTO job_jd_contents (observation_id, job_post_id, jd_text, jd_source, created_at, updated_at)
          VALUES (?, ?, ?, ?, ?, ?)
        `).run(row.observation_id, row.id, jdText, payload.jd_source, nowIso, nowIso);
      }
      updated += 1;
      if (jobIdFilter) {
        log("info", "job_updated", { job_id: row.id, linkedin_job_id: row.linkedin_job_id });
      }
    } catch (error) {
      if (jobIdFilter) {
        log("warn", "job_skipped", { job_id: row.id, linkedin_job_id: row.linkedin_job_id, message: error.message });
      }
    }
  }

  log("info", "complete", { scanned, updated, db_path: dbPath });
}

main()
  .catch((error) => {
    log("error", "fatal", { message: error?.message || String(error) });
    process.exitCode = 1;
  })
  .finally(() => {
    try {
      db.close();
    } catch {}
  });
