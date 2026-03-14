# Backend API and Filtering Excerpt

This excerpt shows part of the backend query pipeline used to filter and prioritize jobs while keeping manual-review and company-level rules in the loop.

```python
def _effective_priority_flag_sql(cls, job_alias: str = "jp", tracking_alias: str = "jat", company_alias: str = "cp") -> str:
    inferred_company_review = cls._company_under_review_exists_sql(job_alias=job_alias, tracking_alias=tracking_alias)
    return f"""
        CASE
          WHEN TRIM(COALESCE({tracking_alias}.priority_flag, '')) <> '' THEN COALESCE({tracking_alias}.priority_flag, '')
          WHEN TRIM(COALESCE({company_alias}.priority_flag, '')) <> '' THEN COALESCE({company_alias}.priority_flag, '')
          WHEN COALESCE({tracking_alias}.is_applied, 0) = 0 AND {inferred_company_review} THEN 'company_under_review'
          ELSE ''
        END
    """

def list_jobs(...):
    where = ["1=1"]
    if stage == "applied":
        where.append("COALESCE(jat.is_applied, 0) = 1")
    elif stage == "filtered":
        where.append("COALESCE(jat.is_applied, 0) = 0")

    if company:
        where.append("LOWER(COALESCE(jp.company, '')) LIKE ?")
        params.append(f"%{company.lower()}%")

    select_sql = f"""
        SELECT
          jp.id,
          jp.title,
          jp.company,
          COALESCE(jat.cv_source_path, '') AS cv_source_path,
          {self._effective_priority_flag_sql(...)} AS effective_priority_flag
        FROM job_posts jp
        LEFT JOIN job_application_tracking jat ON jat.job_post_id = jp.id
        LEFT JOIN company_preferences cp
          ON LOWER(TRIM(COALESCE(cp.company_name, ''))) = LOWER(TRIM(COALESCE(jp.company, '')))
        WHERE {where_clause}
    """
```

What this demonstrates:

- SQL-first filtering for performance
- company-aware application constraints
- backend-driven prioritization, not just UI sorting
