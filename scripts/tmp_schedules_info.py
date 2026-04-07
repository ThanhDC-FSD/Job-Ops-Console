import sqlite3
conn=sqlite3.connect('input/crawled_job/linkedin_jobs_jd.sqlite')
cur=conn.cursor()
cur.execute('PRAGMA table_info(automation_schedules)')
print(cur.fetchall())
conn.close()
