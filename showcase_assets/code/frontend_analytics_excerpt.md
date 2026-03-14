# Rule-Based Prioritization Excerpt

This excerpt focuses on the **rule-based decision layer** used to prioritize or suppress jobs depending on manual rules and inferred company-level conditions.

```python
@classmethod
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

@staticmethod
def _priority_sort_bucket(item: dict[str, Any]) -> tuple[int, int]:
    flag = str(item.get("effective_priority_flag", "") or "").strip().lower()
    is_manual_only = 1 if flag in {
        "manual_only",
        "company_under_review",
        "onsite_only",
        "full_time_only",
        "part_time_only",
    } else 0
    is_low = 1 if flag == "low_priority" else 0
    is_closed = 1 if flag == "closed_no_longer_accepting" else 0
    return (is_manual_only, is_low + is_closed)
```

Why this matters:

- business rules can come from multiple sources
- explicit user rules and inferred rules are merged consistently
- prioritization remains explainable instead of hidden in ad hoc UI logic

Design pattern showcased:

- rule evaluation layer
- strategy-like prioritization by computed flag
- centralized decision logic
