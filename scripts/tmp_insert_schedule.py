import sqlite3, datetime
conn=sqlite3.connect('input/crawled_job/linkedin_jobs_jd.sqlite')
cur=conn.cursor()
now=datetime.datetime.utcnow().isoformat()+"+00:00"
cur.execute("INSERT INTO automation_schedules (name, enabled, cron_expr, timezone, pipeline_type, crawl_config_json, auto_eval_fit, fit_cv_profile, auto_generate_cv, fit_threshold, created_at, updated_at) VALUES (?,1,?, ?,?, ?,1,'full_doc_stlye',0,75.0,?,?)",(
    'Filtered Jobs 16:00',
    '0 16 * * *',
    'Asia/Ho_Chi_Minh',
    'filtered_jobs',
    '{"url": "https://www.linkedin.com/jobs/search/?keywords=Full%20Stack%20Engineer", "window_days": 30, "max_jobs": 200}',
    now,
    now
))
conn.commit()
conn.close()
