import sqlite3, textwrap
conn=sqlite3.connect('input/crawled_job/linkedin_jobs_jd.sqlite')
cur=conn.cursor()
cur.execute('SELECT id, job_post_id, cv_text, cover_letter_text FROM job_generated_artifact_sets WHERE cv_text<>"" LIMIT 5;')
rows=cur.fetchall()
for r in rows:
    print('id',r[0],'job_post_id',r[1],'cv len',len(r[2] or ''))
    print(textwrap.shorten(r[2] or '', width=200, placeholder='...'))
    print('cover len',len(r[3] or ''))
print('rows',len(rows))
conn.close()
