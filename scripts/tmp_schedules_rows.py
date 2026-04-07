import sqlite3
conn=sqlite3.connect('input/crawled_job/linkedin_jobs_jd.sqlite')
cur=conn.cursor()
cur.execute('SELECT * FROM automation_schedules')
for row in cur.fetchall():
    print(row)
conn.close()
