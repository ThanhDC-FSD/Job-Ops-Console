from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SchedulePayload(BaseModel):
    name: str = Field(min_length=2)
    enabled: bool = True
    cron_expr: str = Field(default="0 */6 * * *")
    timezone: str = Field(default="Asia/Ho_Chi_Minh")
    pipeline_type: str = Field(default="filtered_jobs")
    crawl_config: dict[str, Any] = Field(default_factory=dict)
    auto_eval_fit: bool = True
    fit_cv_profile: str = Field(default="full_doc_stlye")
    auto_generate_cv: bool = False
    fit_threshold: float = 75.0


class ScheduleUpdatePayload(BaseModel):
    name: str = Field(default="New Schedule", min_length=2)
    enabled: bool = True
    cron_expr: str = Field(default="0 */6 * * *")
    timezone: str = Field(default="Asia/Ho_Chi_Minh")
    crawl_config: dict[str, Any] = Field(default_factory=dict)
    auto_eval_fit: bool = True
    fit_cv_profile: str = Field(default="full_doc_stlye")
    auto_generate_cv: bool = False
    fit_threshold: float = 75.0


class ScheduleOccurrenceUpdatePayload(BaseModel):
    occurrence_at: str = Field(min_length=10)
    run_at: str = Field(min_length=10)
    name: str = Field(default="New Schedule", min_length=2)
    timezone: str = Field(default="Asia/Ho_Chi_Minh")
    crawl_config: dict[str, Any] = Field(default_factory=dict)
    auto_eval_fit: bool = True
    fit_cv_profile: str = Field(default="full_doc_stlye")
    auto_generate_cv: bool = False
    fit_threshold: float = 75.0


class ActionTriggerPayload(BaseModel):
    action_type: str
    args: list[str] = Field(default_factory=list)
    schedule_id: int | None = None
    run_at: str = Field(default="")


class ActionArgsPayload(BaseModel):
    args: list[str] = Field(default_factory=list)


class JobsDeletePayload(BaseModel):
    job_ids: list[int] = Field(default_factory=list)


class JobPriorityPayload(BaseModel):
    priority_flag: str = Field(default="")
    note: str = Field(default="")


class CompanyPriorityPayload(BaseModel):
    company_name: str = Field(min_length=1)
    priority_flag: str = Field(default="")
    note: str = Field(default="")


class JobManualApplyPayload(BaseModel):
    note: str = Field(default="")


class FitEvaluatePayload(BaseModel):
    cv_path: str = "input/full_doc_stlye.txt"
    stage: str = "all"
    limit: int = 0
    constraint_mode: str = Field(default="medium")
    posted_within_days: int = Field(default=0, ge=0, le=3650)
    sort_by: str = Field(default="posted_date_desc")


class CvRewriteRenderPayload(BaseModel):
    cv_master_path: str = "input/full_doc_stlye.txt"
    jd_path: str
    guide_path: str = "CV_REWRITE_STRICT_GUIDE.md"
    user_prompt: str = (
        "Bay gio hay dua vao cac dau vao [full_doc_stlye.txt](input/full_doc_stlye.txt) "
        "+ jd [<jd>.txt](input/JD/<jd>.txt) cung voi file [CV_REWRITE_STRICT_GUIDE.md]"
        "(CV_REWRITE_STRICT_GUIDE.md), thuc hien cac cong viec trong guide. "
        "Tat ca output CV, cover letter, headline, summary, experience summary, va notes deu phai viet bang tieng Anh. "
        "Hay sang tao hon trong cach dien dat, sap xep evidence, va reframe kinh nghiem de CV fit gan nhat voi JD, "
        "nhung van phai giu dung ban chat thong tin goc, khong duoc bia them fact. "
        "Neu CV da co nhung diem tuong dong voi JD, hay noi ro va som cac diem overlap do thay vi viet chung chung. "
        "Neu JD co cong nghe/toolling minh chua lam truc tiep, khong duoc bia kinh nghiem; "
        "hay viet theo huong transferable skills, adjacent stack, kha nang hoc nhanh, "
        "dong thoi the hien ro dong co muon lam viec cho cong ty do va san sang dong gop lau dai, "
        "de tao ly do de recruiter van nen xem ky CV."
    )
    output_slug: str = ""
    llm_model: str = "gpt-4.1-mini"
    temperature: float = Field(default=0.45, ge=0.0, le=1.5)
    render_docx: bool = True
    render_pdf: bool = False
    run_fit_report: bool = True


class CvRewriteFromJobPayload(BaseModel):
    cv_master_path: str = "input/full_doc_stlye.txt"
    guide_path: str = "CV_REWRITE_STRICT_GUIDE.md"
    user_prompt: str = (
        "Bay gio hay dua vao cac dau vao [full_doc_stlye.txt](input/full_doc_stlye.txt) "
        "+ jd [jd_xxx.txt](input/JD/jd_xxx.txt) cung voi file [CV_REWRITE_STRICT_GUIDE.md]"
        "(CV_REWRITE_STRICT_GUIDE.md), thuc hien cac cong viec trong guide. "
        "Tat ca output CV, cover letter, headline, summary, experience summary, va notes deu phai viet bang tieng Anh. "
        "Hay sang tao hon trong cach dien dat, sap xep evidence, va reframe kinh nghiem de CV fit gan nhat voi JD, "
        "nhung van phai giu dung ban chat thong tin goc, khong duoc bia them fact. "
        "Neu CV da co nhung diem tuong dong voi JD, hay noi ro va som cac diem overlap do thay vi viet chung chung. "
        "Neu JD co cong nghe/toolling minh chua lam truc tiep, khong duoc bia kinh nghiem; "
        "hay viet theo huong transferable skills, adjacent stack, kha nang hoc nhanh, "
        "dong thoi the hien ro dong co muon lam viec cho cong ty do va san sang dong gop lau dai, "
        "de tao ly do de recruiter van nen xem ky CV."
    )
    output_slug: str = ""
    llm_model: str = "gpt-4.1-mini"
    temperature: float = Field(default=0.45, ge=0.0, le=1.5)
    render_docx: bool = True
    render_pdf: bool = False
    run_fit_report: bool = True


class CvRewriteFromJobsPayload(CvRewriteFromJobPayload):
    job_ids: list[int] = Field(default_factory=list)


class LinkedinApplyPayload(BaseModel):
    job_ids: list[int] = Field(default_factory=list)
    cv_paths: list[str] = Field(default_factory=list)
    dry_run: bool = False


class CvFilesPayload(BaseModel):
    extensions: list[str] = Field(default_factory=lambda: ["pdf", "docx"])


class LearningQuizRequestPayload(BaseModel):
    topic_key: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=20)
    lang: str = Field(default="en")


class LearningQuizSubmitItemPayload(BaseModel):
    question_id: int = Field(ge=1)
    # Accept negative IDs because frontend encodes distractors with negative keys.
    selected_answer_id: int | None = Field(default=None)
    selected_text: str = Field(default="")


class LearningQuizSubmitPayload(BaseModel):
    topic_key: str = Field(min_length=1)
    lang: str = Field(default="en")
    items: list[LearningQuizSubmitItemPayload] = Field(default_factory=list)


class LearningSchedulePayload(BaseModel):
    name: str = Field(default="Daily Learning ETL", min_length=2)
    cron_expr: str = Field(default="15 2 * * *")
    timezone: str = Field(default="Asia/Ho_Chi_Minh")
    enabled: bool = True
    topic_keys: list[str] = Field(default_factory=list)
    daily_target_per_topic: int = Field(default=20, ge=1, le=100)
    seed_path: str = Field(default="learning_plan.md")
    enqueue_now: bool = True
    max_attempts: int = Field(default=3, ge=1, le=10)
    crawl_enabled: bool = Field(default=True)
    crawl_per_topic_limit: int = Field(default=10, ge=1, le=50)
    crawl_sources: list[str] = Field(default_factory=list)
