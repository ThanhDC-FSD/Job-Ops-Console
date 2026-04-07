const fs = require('fs');
const path = require('path');
const PDFDocument = require('../../tmp_sqlite_tools/node_modules/pdfkit');
const Database = require('../../tmp_sqlite_tools/node_modules/better-sqlite3');

const projectRoot = path.resolve(__dirname, '..', '..');
const dbPath = path.join(projectRoot, 'input', 'crawled_job', 'linkedin_jobs_jd.sqlite');
const videoUrl = 'https://github.com/ThanhDC-FSD/Job-Ops-Console/blob/showcase/showcase_assets/video/job_ops_project_showcase.mp4';
const repoUrl = 'https://github.com/ThanhDC-FSD/Job-Ops-Console/tree/showcase';

function resolveExisting(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  const target = path.isAbsolute(raw) ? path.resolve(raw) : path.resolve(projectRoot, raw);
  return fs.existsSync(target) ? target : '';
}

function derivePortfolioPdf(baseArtifactPath) {
  const parsed = path.parse(baseArtifactPath);
  let stem = parsed.name;
  if (stem.startsWith('CV_')) stem = `PORTFOLIO_${stem.slice(3)}`;
  else if (stem.startsWith('COVER_LETTER_')) stem = `PORTFOLIO_${stem.slice('COVER_LETTER_'.length)}`;
  else stem = `PORTFOLIO_${stem}`;
  return path.join(parsed.dir, `${stem}.pdf`);
}

function writeParagraph(doc, text, opts = {}) {
  if (!text) return;
  doc
    .font(opts.font || 'Helvetica')
    .fontSize(opts.size || 11)
    .fillColor(opts.color || '#122033')
    .text(String(text), { align: opts.align || 'left' });
  doc.moveDown(opts.gap == null ? 0.6 : opts.gap);
}

function buildPdf(outPath, row) {
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  return new Promise((resolve, reject) => {
    const doc = new PDFDocument({ size: 'A4', margin: 48 });
    const stream = fs.createWriteStream(outPath);
    stream.on('finish', resolve);
    stream.on('error', reject);
    doc.pipe(stream);

    writeParagraph(doc, 'PORTFOLIO SHOWCASE', { size: 18, font: 'Helvetica-Bold', align: 'center', gap: 0.4 });
    writeParagraph(doc, row.generated_headline || row.title || 'Portfolio', { size: 15, font: 'Helvetica-Bold', gap: 0.3 });
    const meta = [row.company, row.location, row.latest_posted_time].filter(Boolean).join(' | ');
    if (meta) writeParagraph(doc, meta, { size: 10, font: 'Helvetica-Oblique', color: '#526071', gap: 0.8 });

    writeParagraph(doc, 'Overview', { size: 13, font: 'Helvetica-Bold', color: '#1f8b4c', gap: 0.3 });
    writeParagraph(
      doc,
      'This portfolio summary was generated from tailored CV artifacts and reflects the current Job Ops workflow (crawl, evaluation, RAG rewrite, validation, and artifact delivery).',
      { gap: 0.8 }
    );

    writeParagraph(doc, 'Workflow Highlights', { size: 13, font: 'Helvetica-Bold', color: '#1f8b4c', gap: 0.3 });
    writeParagraph(doc, '- Crawl and normalize job posts with structured parsers and repeat observations.', { gap: 0.2 });
    writeParagraph(doc, '- Fit evaluation and rule gating for priorities, Easy Apply, and constraints.', { gap: 0.2 });
    writeParagraph(doc, '- Evidence-first RAG rewrite with hybrid retrieval, validators, and fallbacks.', { gap: 0.6 });

    if (row.generated_summary) {
      writeParagraph(doc, 'Professional Summary', { size: 13, font: 'Helvetica-Bold', color: '#1f8b4c', gap: 0.3 });
      writeParagraph(doc, row.generated_summary, { gap: 0.8 });
    }
    if (row.generated_experience_summary) {
      writeParagraph(doc, 'Experience Highlights', { size: 13, font: 'Helvetica-Bold', color: '#1f8b4c', gap: 0.3 });
      writeParagraph(doc, row.generated_experience_summary, { gap: 0.8 });
    }

    writeParagraph(doc, 'Tech Snapshot', { size: 13, font: 'Helvetica-Bold', color: '#1f8b4c', gap: 0.3 });
    writeParagraph(doc, 'FastAPI + Uvicorn + Pydantic, SQLite, APScheduler, React + Vite, D3 Geo/TopoJSON.', { gap: 0.2 });
    writeParagraph(doc, 'Playwright + HTML parsers for crawl; sentence-transformers + FAISS for retrieval.', { gap: 0.2 });
    writeParagraph(doc, 'Offline qwen2.5 gateway with validators and deterministic fallback templates.', { gap: 0.8 });

    writeParagraph(doc, 'Project Showcase Video', { size: 13, font: 'Helvetica-Bold', color: '#1f8b4c', gap: 0.3 });
    writeParagraph(doc, videoUrl, { size: 10, color: '#1d4ed8', gap: 0.8 });

    writeParagraph(doc, 'Public Showcase Repository', { size: 13, font: 'Helvetica-Bold', color: '#1f8b4c', gap: 0.3 });
    writeParagraph(doc, repoUrl, { size: 10, color: '#1d4ed8', gap: 0.8 });

    writeParagraph(doc, 'Selected Code Snippets', { size: 13, font: 'Helvetica-Bold', color: '#1f8b4c', gap: 0.3 });
    writeParagraph(doc, 'Backend API: showcase_assets/code/backend_api_excerpt.md', { size: 10, gap: 0.2 });
    writeParagraph(doc, 'CV workflow: showcase_assets/code/cv_generation_excerpt.md', { size: 10, gap: 0.2 });
    writeParagraph(doc, 'Frontend analytics: showcase_assets/code/frontend_analytics_excerpt.md', { size: 10, gap: 0.6 });

    doc.end();
  });
}

async function main() {
  const db = new Database(dbPath, { timeout: 30000 });
  db.pragma('journal_mode = WAL');
  db.pragma('busy_timeout = 30000');
  const rows = db.prepare(`
    SELECT
      jat.job_post_id,
      COALESCE(jat.cv_source_path,'') AS cv_source_path,
      COALESCE(jat.generated_headline,'') AS generated_headline,
      COALESCE(jat.generated_summary,'') AS generated_summary,
      COALESCE(jat.generated_experience_summary,'') AS generated_experience_summary,
      COALESCE(jp.title,'') AS title,
      COALESCE(jp.company,'') AS company,
      COALESCE(jp.location,'') AS location,
      COALESCE(jp.latest_posted_time,'') AS latest_posted_time
    FROM job_application_tracking jat
    JOIN job_posts jp ON jp.id = jat.job_post_id
    WHERE COALESCE(jat.has_cv, 0) = 1
  `).all();
  let created = 0;
  let updated = 0;
  for (const row of rows) {
    const cvSource = resolveExisting(row.cv_source_path);
    if (!cvSource) continue;
    const docx = cvSource.toLowerCase().endsWith('.docx') ? cvSource : resolveExisting(cvSource.replace(/\\.txt$/i, '.docx').replace(/\\.pdf$/i, '.docx'));
    const pdf = cvSource.toLowerCase().endsWith('.pdf') ? cvSource : resolveExisting(cvSource.replace(/\\.txt$/i, '.pdf').replace(/\\.docx$/i, '.pdf'));
    const baseArtifact = docx || pdf || cvSource;
    const portfolioPdf = derivePortfolioPdf(baseArtifact);
    await buildPdf(portfolioPdf, row);
    if (fs.existsSync(portfolioPdf)) {
      created += 1;
      updated += 1;
    }
  }

  console.log(JSON.stringify({ rows: rows.length, created, updated }, null, 2));
  db.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
