import sqlite3
DB='apps/backend/app/job_ops_schema.sqlite'
conn=sqlite3.connect(DB)
conn.execute("UPDATE job_posts SET normalized_work_model=?, validated_work_model=? WHERE id=?", ('hybrid','hybrid',2310))
conn.commit()
print('updated rows:', conn.total_changes)
