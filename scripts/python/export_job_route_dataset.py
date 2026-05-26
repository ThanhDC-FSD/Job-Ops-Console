from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PROJECT_NAME = "Job-Ops-Console"
SQLITE_FILENAME = "linkedin_jobs_jd.sqlite"
DEFAULT_MODEL_NAME = "prajjwal1/bert-tiny"


def _default_repo_root() -> Path:
    for candidate in (
        Path(f"/content/{PROJECT_NAME}"),
        Path.cwd(),
    ):
        if candidate.exists():
            return candidate
    return Path.cwd()


DEFAULT_REPO_ROOT = _default_repo_root()
DEFAULT_DB_PATH = DEFAULT_REPO_ROOT / "input" / "crawled_job" / SQLITE_FILENAME
DEFAULT_OUT_DIR = DEFAULT_REPO_ROOT / "artifacts" / "ml" / "job_route"
LINKEDIN_HOST_TOKENS = ("linkedin.com", "lnkd.in", "onsiteapply", "easyapply")
TEXT_KEYS = (
    "description",
    "job_description",
    "jobDescription",
    "full_description",
    "jd_text",
    "summary",
)


def _candidate_sqlite_paths(*, repo_root: Path | None = None) -> list[Path]:
    root = repo_root or DEFAULT_REPO_ROOT
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path)
        if key not in seen:
            seen.add(key)
            candidates.append(path)

    env_paths = [
        os.getenv("JOB_ROUTE_SQLITE_DB", "").strip(),
        os.getenv("JOB_DB_PATH", "").strip(),
    ]
    for env_path in env_paths:
        if env_path:
            add(Path(env_path))

    add(root / "input" / "crawled_job" / SQLITE_FILENAME)
    add(Path("/content") / PROJECT_NAME / "input" / "crawled_job" / SQLITE_FILENAME)
    add(Path("/content") / SQLITE_FILENAME)
    add(Path("/content/drive/MyDrive") / SQLITE_FILENAME)
    add(Path("/content/drive/MyDrive") / PROJECT_NAME / "input" / "crawled_job" / SQLITE_FILENAME)
    add(Path("/content/drive/MyDrive/Colab Notebooks") / SQLITE_FILENAME)
    return candidates


def _resolve_sqlite_db(user_value: str | Path | None) -> Path:
    raw = str(user_value or "").strip()
    if raw:
        path = Path(raw)
        if path.exists():
            return path
        tried = [str(path)]
    else:
        tried = []
        for candidate in _candidate_sqlite_paths():
            tried.append(str(candidate))
            if candidate.exists():
                return candidate
    raise FileNotFoundError(
        "Could not locate SQLite DB for job-route export.\n"
        "Tried these paths:\n- "
        + "\n- ".join(tried)
        + "\n\n"
        "If you are in Colab, either:\n"
        "1. clone the repo and place the DB under /content/Job-Ops-Console/input/crawled_job/\n"
        "2. upload the DB to /content/\n"
        "3. mount Google Drive and pass --sqlite-db /content/drive/MyDrive/linkedin_jobs_jd.sqlite"
    )


def _safe_json_loads(raw: Any) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _extract_apply_url(payload: dict[str, Any]) -> str:
    return str(payload.get("apply_url") or payload.get("external_apply_url") or "").strip()


def _extract_public_apply_mode(payload: dict[str, Any]) -> str:
    return str(payload.get("public_apply_mode") or "").strip().lower()


def _is_easy_apply_url(url: str) -> bool:
    low = str(url or "").strip().lower()
    if not low:
        return False
    return any(token in low for token in LINKEDIN_HOST_TOKENS)


def _url_host(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    return (parsed.netloc or "").strip().lower()


def _truncate(text: str, limit: int) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def _collect_text_candidates(value: Any, out: list[str]) -> None:
    if value in (None, ""):
        return
    if isinstance(value, str):
        out.append(value)
        return
    if isinstance(value, list):
        for item in value:
            _collect_text_candidates(item, out)
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key or "") in TEXT_KEYS:
                _collect_text_candidates(nested, out)
            elif isinstance(nested, (dict, list)):
                _collect_text_candidates(nested, out)


def _extract_description(payload: dict[str, Any], *, limit: int) -> str:
    values: list[str] = []
    for key in TEXT_KEYS:
        if key in payload:
            _collect_text_candidates(payload.get(key), values)
    if not values:
        _collect_text_candidates(payload, values)
    merged = " ".join(v.strip() for v in values if str(v or "").strip())
    return _truncate(merged, limit)


def _effective_easy_apply(
    *,
    normalized_easy_apply: int,
    validated_easy_apply: int,
    payload: dict[str, Any],
) -> int:
    if int(validated_easy_apply or 0) == 1:
        return 1
    if int(normalized_easy_apply or 0) == 1:
        return 1
    public_apply_mode = _extract_public_apply_mode(payload)
    if public_apply_mode == "onsite":
        return 1
    apply_url = _extract_apply_url(payload)
    if _is_easy_apply_url(apply_url):
        return 1
    if str(payload.get("easy_apply") or "").strip() in {"1", "true", "True"}:
        return 1
    return 0


def _label_row(row: sqlite3.Row, payload: dict[str, Any]) -> tuple[str, str]:
    manual_review_required = int(row["manual_review_required"] or 0)
    normalized_easy_apply = int(row["normalized_easy_apply"] or 0)
    validated_easy_apply = int(row["validated_easy_apply"] or 0)
    public_apply_mode = _extract_public_apply_mode(payload)
    apply_url = _extract_apply_url(payload)
    effective_easy = _effective_easy_apply(
        normalized_easy_apply=normalized_easy_apply,
        validated_easy_apply=validated_easy_apply,
        payload=payload,
    )

    if manual_review_required == 1:
        return "manual_review_candidate", "manual_review_required=1"
    if effective_easy == 1 and public_apply_mode != "offsite":
        return "easy_apply", "effective_easy_apply=1"
    if public_apply_mode == "offsite":
        return "offsite", "public_apply_mode=offsite"
    if apply_url and not _is_easy_apply_url(apply_url):
        return "offsite", "external_apply_url"
    return "", "ambiguous_or_unlabeled"


def _build_model_text(row: sqlite3.Row, payload: dict[str, Any], *, description_chars: int) -> str:
    apply_url = _extract_apply_url(payload)
    lines = [
        f"title: {str(row['title'] or '').strip()}",
        f"company: {str(row['company'] or '').strip()}",
        f"location: {str(row['location'] or '').strip()}",
        f"work_model: {str(row['normalized_work_model'] or '').strip()}",
        f"employment_type: {str(row['normalized_employment_type'] or '').strip()}",
        f"posted_time: {str(row['latest_posted_time'] or '').strip()}",
        f"public_apply_mode: {_extract_public_apply_mode(payload)}",
        f"apply_url_host: {_url_host(apply_url)}",
        f"job_url_host: {_url_host(str(row['job_url_final'] or row['job_url'] or '').strip())}",
        f"description: {_extract_description(payload, limit=description_chars)}",
    ]
    return "\n".join(lines).strip()


def _iter_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    query = """
        SELECT
          jp.id,
          jp.title,
          jp.company,
          jp.location,
          COALESCE(jp.normalized_work_model, '') AS normalized_work_model,
          COALESCE(jp.normalized_employment_type, '') AS normalized_employment_type,
          COALESCE(jp.normalized_easy_apply, 0) AS normalized_easy_apply,
          COALESCE(jdv.easy_apply, 0) AS validated_easy_apply,
          COALESCE(jat.manual_review_required, 0) AS manual_review_required,
          COALESCE(jat.manual_review_note, '') AS manual_review_note,
          COALESCE(jp.job_url, '') AS job_url,
          COALESCE(jp.job_url_final, '') AS job_url_final,
          COALESCE(jp.latest_posted_time, '') AS latest_posted_time,
          COALESCE(jp.latest_payload_json, '') AS latest_payload_json
        FROM job_posts jp
        LEFT JOIN job_detail_validations jdv ON jdv.job_post_id = jp.id
        LEFT JOIN job_application_tracking jat ON jat.job_post_id = jp.id
        WHERE COALESCE(jp.latest_payload_json, '') <> ''
          AND COALESCE(jp.title, '') <> ''
          AND COALESCE(jp.company, '') <> ''
    """
    return list(conn.execute(query).fetchall())


def _assign_split(job_id: int, *, train_ratio: float, val_ratio: float, seed: int) -> str:
    rng = random.Random(seed + int(job_id))
    value = rng.random()
    if value < train_ratio:
        return "train"
    if value < train_ratio + val_ratio:
        return "val"
    return "test"


def export_dataset(
    *,
    sqlite_db: Path,
    out_dir: Path,
    description_chars: int,
    train_ratio: float,
    val_ratio: float,
    seed: int,
) -> dict[str, Any]:
    sqlite_db = sqlite_db.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "job_route_dataset.csv"
    jsonl_path = out_dir / "job_route_dataset.jsonl"
    summary_path = out_dir / "job_route_dataset_summary.json"

    with sqlite3.connect(str(sqlite_db)) as conn:
        rows = _iter_rows(conn)

    label_counts: Counter[str] = Counter()
    skip_counts: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    for row in rows:
        payload = _safe_json_loads(row["latest_payload_json"])
        label, reason = _label_row(row, payload)
        if not label:
            skip_counts[reason] += 1
            continue
        record = {
            "job_id": int(row["id"] or 0),
            "label": label,
            "label_reason": reason,
            "split": _assign_split(int(row["id"] or 0), train_ratio=train_ratio, val_ratio=val_ratio, seed=seed),
            "title": str(row["title"] or "").strip(),
            "company": str(row["company"] or "").strip(),
            "location": str(row["location"] or "").strip(),
            "normalized_work_model": str(row["normalized_work_model"] or "").strip(),
            "normalized_employment_type": str(row["normalized_employment_type"] or "").strip(),
            "normalized_easy_apply": int(row["normalized_easy_apply"] or 0),
            "validated_easy_apply": int(row["validated_easy_apply"] or 0),
            "manual_review_required": int(row["manual_review_required"] or 0),
            "manual_review_note": str(row["manual_review_note"] or "").strip(),
            "job_url": str(row["job_url"] or "").strip(),
            "job_url_final": str(row["job_url_final"] or "").strip(),
            "latest_posted_time": str(row["latest_posted_time"] or "").strip(),
            "public_apply_mode": _extract_public_apply_mode(payload),
            "apply_url": _extract_apply_url(payload),
            "apply_url_host": _url_host(_extract_apply_url(payload)),
            "text": _build_model_text(row, payload, description_chars=description_chars),
        }
        records.append(record)
        label_counts[label] += 1

    fieldnames = list(records[0].keys()) if records else []
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record)

    with jsonl_path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary = {
        "sqlite_db": str(sqlite_db),
        "total_rows_scanned": len(rows),
        "total_labeled_rows": len(records),
        "label_counts": dict(sorted(label_counts.items())),
        "skip_counts": dict(sorted(skip_counts.items())),
        "split_counts": dict(sorted(Counter(r["split"] for r in records).items())),
        "description_chars": int(description_chars),
        "train_ratio": float(train_ratio),
        "val_ratio": float(val_ratio),
        "test_ratio": float(max(0.0, 1.0 - train_ratio - val_ratio)),
        "seed": int(seed),
        "csv_path": str(csv_path),
        "jsonl_path": str(jsonl_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def _load_dataframe(csv_path: Path):
    import pandas as pd

    return pd.read_csv(csv_path)


def _split_frames(df):
    train_df = df[df["split"] == "train"].copy()
    val_df = df[df["split"] == "val"].copy()
    test_df = df[df["split"] == "test"].copy()
    return train_df, val_df, test_df


def run_baseline(*, csv_path: Path, out_dir: Path) -> dict[str, Any]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.pipeline import Pipeline

    df = _load_dataframe(csv_path)
    train_df, val_df, test_df = _split_frames(df)

    baseline = Pipeline(
        [
            ("tfidf", TfidfVectorizer(max_features=40000, ngram_range=(1, 2), min_df=2)),
            ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
        ]
    )
    baseline.fit(train_df["text"], train_df["label"])
    val_pred = baseline.predict(val_df["text"])
    test_pred = baseline.predict(test_df["text"])

    labels = ["easy_apply", "manual_review_candidate", "offsite"]
    results = {
        "val_classification_report": classification_report(val_df["label"], val_pred, digits=4, output_dict=True),
        "test_classification_report": classification_report(test_df["label"], test_pred, digits=4, output_dict=True),
        "test_confusion_matrix": confusion_matrix(test_df["label"], test_pred, labels=labels).tolist(),
        "labels": labels,
    }
    out_path = out_dir / "baseline_metrics.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"baseline_metrics_path": str(out_path), **results}


def _torch_runtime_config() -> dict[str, Any]:
    import torch

    has_cuda = bool(torch.cuda.is_available())
    return {
        "has_cuda": has_cuda,
        "device": "cuda" if has_cuda else "cpu",
        "fp16": has_cuda,
        "per_device_train_batch_size": 16 if has_cuda else 8,
        "per_device_eval_batch_size": 32 if has_cuda else 16,
        "max_length": 256 if has_cuda else 192,
    }


def run_transformer(
    *,
    csv_path: Path,
    out_dir: Path,
    model_name: str,
    epochs: int,
    learning_rate: float,
) -> dict[str, Any]:
    import numpy as np
    from datasets import Dataset, DatasetDict
    from sklearn.metrics import classification_report, confusion_matrix
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    from transformers import DataCollatorWithPadding, Trainer, TrainingArguments
    import evaluate

    df = _load_dataframe(csv_path)
    train_df, val_df, test_df = _split_frames(df)
    runtime_cfg = _torch_runtime_config()

    label_list = sorted(df["label"].unique().tolist())
    label2id = {label: idx for idx, label in enumerate(label_list)}
    id2label = {idx: label for label, idx in label2id.items()}

    def frame_to_dataset(frame):
        data = frame[["text", "label"]].copy()
        data["labels"] = data["label"].map(label2id)
        return Dataset.from_pandas(data[["text", "labels"]], preserve_index=False)

    dataset = DatasetDict(
        {
            "train": frame_to_dataset(train_df),
            "validation": frame_to_dataset(val_df),
            "test": frame_to_dataset(test_df),
        }
    )

    tokenizer = AutoTokenizer.from_pretrained(model_name)

    def tokenize(batch):
        return tokenizer(batch["text"], truncation=True, max_length=int(runtime_cfg["max_length"]))

    tokenized = dataset.map(tokenize, batched=True)
    data_collator = DataCollatorWithPadding(tokenizer=tokenizer)
    metric_f1 = evaluate.load("f1")
    metric_acc = evaluate.load("accuracy")

    def compute_metrics(eval_pred):
        logits, labels = eval_pred
        preds = np.argmax(logits, axis=-1)
        f1 = metric_f1.compute(predictions=preds, references=labels, average="macro")["f1"]
        acc = metric_acc.compute(predictions=preds, references=labels)["accuracy"]
        return {"accuracy": acc, "macro_f1": f1}

    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        num_labels=len(label_list),
        id2label=id2label,
        label2id=label2id,
    )

    run_dir = out_dir / "transformer_runs"
    export_dir = out_dir / "transformer_export"
    training_args = TrainingArguments(
        output_dir=str(run_dir),
        learning_rate=float(learning_rate),
        per_device_train_batch_size=int(runtime_cfg["per_device_train_batch_size"]),
        per_device_eval_batch_size=int(runtime_cfg["per_device_eval_batch_size"]),
        num_train_epochs=int(epochs),
        weight_decay=0.01,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        report_to="none",
        fp16=bool(runtime_cfg["fp16"]),
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["validation"],
        data_collator=data_collator,
        compute_metrics=compute_metrics,
    )
    train_output = trainer.train()
    test_metrics = trainer.evaluate(tokenized["test"])

    pred_output = trainer.predict(tokenized["test"])
    pred_ids = np.argmax(pred_output.predictions, axis=-1)
    true_ids = pred_output.label_ids
    pred_labels = [id2label[int(x)] for x in pred_ids]
    true_labels = [id2label[int(x)] for x in true_ids]

    labels = ["easy_apply", "manual_review_candidate", "offsite"]
    report = classification_report(true_labels, pred_labels, digits=4, output_dict=True)
    matrix = confusion_matrix(true_labels, pred_labels, labels=labels).tolist()

    export_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(export_dir))
    tokenizer.save_pretrained(str(export_dir))
    (export_dir / "label_map.json").write_text(json.dumps(label2id, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    results = {
        "model_name": model_name,
        "runtime": runtime_cfg,
        "train_metrics": dict(train_output.metrics),
        "test_metrics": dict(test_metrics),
        "test_classification_report": report,
        "test_confusion_matrix": matrix,
        "labels": labels,
        "export_dir": str(export_dir),
    }
    out_path = out_dir / "transformer_metrics.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"transformer_metrics_path": str(out_path), **results}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Export labeled dataset for job-route classifier training. "
            "Defaults auto-detect Google Colab at /content/Job-Ops-Console when available."
        )
    )
    parser.add_argument(
        "--sqlite-db",
        default="",
        help=(
            "SQLite DB path. If omitted, the script auto-detects common local/Colab/Drive locations, "
            f"including {DEFAULT_DB_PATH} and /content/drive/MyDrive/{SQLITE_FILENAME}."
        ),
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help=f"Output directory for CSV/JSONL dataset. Default: {DEFAULT_OUT_DIR}",
    )
    parser.add_argument("--description-chars", type=int, default=1600, help="Max JD/payload chars appended to the training text.")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Train split ratio.")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="Validation split ratio.")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic split seed.")
    parser.add_argument("--train-baseline", action="store_true", help="Train TF-IDF + LogisticRegression baseline after export.")
    parser.add_argument("--train-transformer", action="store_true", help="Train a small transformer classifier after export.")
    parser.add_argument("--run-all", action="store_true", help="Run export + baseline + transformer in one command.")
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME, help=f"Transformer model name. Default: {DEFAULT_MODEL_NAME}")
    parser.add_argument("--epochs", type=int, default=3, help="Transformer training epochs.")
    parser.add_argument("--learning-rate", type=float, default=3e-5, help="Transformer learning rate.")
    args = parser.parse_args()

    sqlite_db = _resolve_sqlite_db(args.sqlite_db)
    out_dir = Path(args.out_dir)
    run_baseline_flag = bool(args.train_baseline or args.run_all)
    run_transformer_flag = bool(args.train_transformer or args.run_all)
    summary = export_dataset(
        sqlite_db=sqlite_db,
        out_dir=out_dir,
        description_chars=max(200, int(args.description_chars)),
        train_ratio=max(0.5, min(0.95, float(args.train_ratio))),
        val_ratio=max(0.0, min(0.3, float(args.val_ratio))),
        seed=int(args.seed),
    )
    summary["repo_root"] = str(DEFAULT_REPO_ROOT)
    summary["resolved_sqlite_db"] = str(sqlite_db.resolve())
    summary["resolved_out_dir"] = str(out_dir.resolve())
    csv_path = out_dir / "job_route_dataset.csv"
    if run_baseline_flag:
        summary["baseline"] = run_baseline(csv_path=csv_path, out_dir=out_dir)
    if run_transformer_flag:
        summary["transformer"] = run_transformer(
            csv_path=csv_path,
            out_dir=out_dir,
            model_name=str(args.model_name).strip(),
            epochs=int(args.epochs),
            learning_rate=float(args.learning_rate),
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
