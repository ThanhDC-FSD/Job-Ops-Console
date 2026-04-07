import sqlite3, json
DB='apps/backend/app/job_ops_schema.sqlite'
conn=sqlite3.connect(DB)
conn.row_factory=sqlite3.Row
rows=conn.execute("select id, title, company, cv_source_path, generated_pdf_path, generated_docx_path, generated_cv_text_path, generated_cover_letter_pdf_path, generated_cover_letter_docx_path, cv_created_date from job_posts where company like '%Sangha%' and title like '%Full Stack Engineer%' order by id desc limit 5").fetchall()
print([dict(r) for r in rows])
