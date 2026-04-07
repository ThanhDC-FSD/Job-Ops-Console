import sqlite3
conn=sqlite3.connect('input/crawled_job/linkedin_jobs_jd.sqlite')
cur=conn.cursor()
cur.execute('SELECT id, name, cron_expr, timezone, enabled FROM automation_schedules')
rows=cur.fetchall()
for row in rows:
    print(row)
conn.close()
