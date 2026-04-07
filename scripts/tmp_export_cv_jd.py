import sqlite3
conn=sqlite3.connect('input/crawled_job/linkedin_jobs_jd.sqlite')
cur=conn.cursor()
job_id=457
cur.execute('SELECT cv_text, cover_letter_text FROM job_generated_artifact_sets WHERE job_post_id=? LIMIT 1', (job_id,))
row=cur.fetchone()
if row:
    cv, cover = row
    open('tmp_cv_457.txt', 'w', encoding='utf-8').write(cv or '')
    open('tmp_cover_457.txt', 'w', encoding='utf-8').write(cover or '')
cur.execute('SELECT jd_text FROM job_jd_contents WHERE job_post_id=? ORDER BY id LIMIT 1', (job_id,))
row=cur.fetchone()
if row:
    open('tmp_jd_457.txt', 'w', encoding='utf-8').write(row[0] or '')
conn.close()
