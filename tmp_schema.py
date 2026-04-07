import sqlite3
conn=sqlite3.connect('apps/backend/app/job_ops_schema.sqlite')
rows=conn.execute('PRAGMA table_info(job_posts)').fetchall()
for r in rows:
    print(r)
