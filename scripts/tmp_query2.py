import sqlite3
conn=sqlite3.connect('input/crawled_job/linkedin_jobs_jd.sqlite')
cur=conn.cursor()
cur.execute('SELECT id, title, company, location, normalized_work_model, normalized_employment_type, job_url FROM job_posts WHERE id=457')
print('job_post', cur.fetchone())
cur.execute('SELECT jd_text FROM job_jd_contents WHERE job_post_id=457')
for jd in cur.fetchall():
    print('jd lens', len(jd[0] or ''))
    print(jd[0][:500])
conn.close()
