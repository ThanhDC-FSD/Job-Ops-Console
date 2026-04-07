import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "you",
    "your",
    "our",
    "are",
    "have",
    "has",
    "will",
    "into",
    "about",
    "they",
    "them",
    "their",
    "through",
    "using",
    "build",
    "help",
    "work",
    "role",
    "team",
    "strong",
    "experience",
    "product",
    "candidate",
    "candidates",
}

TECH_TERMS = {
    "react",
    "typescript",
    "javascript",
    "python",
    "fastapi",
    "django",
    "flask",
    "sql",
    "postgresql",
    "mysql",
    "oracle",
    "docker",
    "jenkins",
    "nginx",
    "llm",
    "llms",
    "langchain",
    "chroma",
    "mcp",
    "supabase",
    "chakra",
    "tanstackdb",
    "ux",
    "ui",
    "saas",
}

ACTION_VERBS = {
    "built",
    "developed",
    "designed",
    "implemented",
    "integrated",
    "automated",
    "delivered",
    "created",
    "contributed",
    "improved",
}

DOMAIN_TERMS = {
    "saas",
    "startup",
    "frontend",
    "full",
    "fullstack",
    "ux",
    "ai",
    "ownership",
    "scale",
    "product",
}

COUNTRY_ALIASES = {
    "usa": "United States",
    "gbr": "United Kingdom",
    "can": "Canada",
    "aut": "Austria",
    "bel": "Belgium",
    "fra": "France",
    "deu": "Germany",
    "lie": "Liechtenstein",
    "lux": "Luxembourg",
    "mco": "Monaco",
    "nld": "Netherlands",
    "che": "Switzerland",
    "bgr": "Bulgaria",
    "cze": "Czechia",
    "hun": "Hungary",
    "mda": "Moldova",
    "pol": "Poland",
    "rou": "Romania",
    "svk": "Slovakia",
    "vnm": "Vietnam",
    "viet nam": "Vietnam",
    "vietnam": "Vietnam",
    "puerto rico": "Puerto Rico",
    "argentina": "Argentina",
    "peru": "Peru",
    "colombia": "Colombia",
    "dominica": "Dominica",
    "brazil": "Brazil",
    "mexico": "Mexico",
    "belize": "Belize",
    "costa rica": "Costa Rica",
    "dominican republic": "Dominican Republic",
    "el salvador": "El Salvador",
    "nicaragua": "Nicaragua",
    "panama": "Panama",
    "trinidad and tobago": "Trinidad and Tobago",
    "bolivia": "Bolivia",
    "chile": "Chile",
    "ecuador": "Ecuador",
    "paraguay": "Paraguay",
    "venezuela": "Venezuela",
    "uruguay": "Uruguay",
    "honduras": "Honduras",
    "guatemala": "Guatemala",
    "united states": "United States",
    "canada": "Canada",
    "sweden": "Sweden",
}
COUNTRY_PATTERNS = [
    (canonical, re.compile(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", re.IGNORECASE))
    for alias, canonical in sorted(COUNTRY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True)
]
LOCATION_LIST_MARKERS = (
    "location requirements",
    "locations:",
    "location:",
    "countries:",
    "country:",
    "eligible locations",
    "we hire in",
    "hiring in",
    "must be located in",
    "can be located in",
    "residing in",
    "reside in",
)
ISO3_TOKEN_PATTERN = re.compile(r"\b[A-Z]{3}\b")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]*", text.lower())


def keyword_pool(tokens: list[str]) -> list[str]:
    kept = []
    for token in tokens:
        if len(token) < 3:
            continue
        if token in STOPWORDS:
            continue
        if token.isdigit():
            continue
        kept.append(token)
    return kept


def top_keywords(jd_text: str, limit: int = 40) -> list[str]:
    tokens = keyword_pool(tokenize(jd_text))
    counts = Counter(tokens)
    return [word for word, _ in counts.most_common(limit)]


def keyword_coverage_score(jd_keywords: list[str], cv_tokens_set: set[str]) -> tuple[float, list[str], list[str]]:
    if not jd_keywords:
        return 100.0, [], []
    matched = [k for k in jd_keywords if k in cv_tokens_set]
    missing = [k for k in jd_keywords if k not in cv_tokens_set]
    return (len(matched) / len(jd_keywords)) * 100.0, matched, missing


def technical_fit_score(jd_tokens_set: set[str], cv_tokens_set: set[str]) -> float:
    jd_tech = sorted(jd_tokens_set.intersection(TECH_TERMS))
    if not jd_tech:
        return 70.0
    hit = [t for t in jd_tech if t in cv_tokens_set]
    return (len(hit) / len(jd_tech)) * 100.0


def domain_fit_score(jd_tokens_set: set[str], cv_tokens_set: set[str]) -> float:
    jd_domain = sorted(jd_tokens_set.intersection(DOMAIN_TERMS))
    if not jd_domain:
        return 70.0
    hit = [t for t in jd_domain if t in cv_tokens_set]
    return (len(hit) / len(jd_domain)) * 100.0


def evidence_quality_score(cv_text: str) -> float:
    bullets = [line.strip().lower() for line in cv_text.splitlines() if line.strip().startswith("- ")]
    if not bullets:
        return 0.0
    rich = 0
    for bullet in bullets:
        has_verb = any(bullet.startswith(f"- {v}") for v in ACTION_VERBS)
        has_tech = any(term in bullet for term in TECH_TERMS)
        if has_verb and has_tech:
            rich += 1
    return (rich / len(bullets)) * 100.0


def _candidate_country() -> str:
    sample = str(os.getenv("LINKEDIN_LOCATION", "Hanoi, Vietnam") or "Hanoi, Vietnam").strip().lower()
    for canonical, pattern in COUNTRY_PATTERNS:
        if pattern.search(sample):
            return canonical
    return "Vietnam"


def _extract_explicit_location_countries(jd_text: str) -> list[str]:
    text = str(jd_text or "")
    if not text.strip():
        return []
    segments = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        lower_line = line.lower()
        if any(marker in lower_line for marker in LOCATION_LIST_MARKERS):
            segments.append(line.strip())
            for next_line in lines[index + 1 : index + 4]:
                cleaned = str(next_line or "").strip()
                if not cleaned:
                    break
                segments.append(cleaned)
    for match in re.finditer(
        r"(?is)(locations?|countries?|eligible locations|we hire in|hiring in|must be located in|can be located in)\s*[:\-]\s*([^\n\r]{0,500})",
        text,
    ):
        segments.append(match.group(2).strip())
    found = set()
    for segment in segments:
        for canonical, pattern in COUNTRY_PATTERNS:
            if pattern.search(segment):
                found.add(canonical)
        iso_tokens = ISO3_TOKEN_PATTERN.findall(segment.upper())
        if len(iso_tokens) >= 2:
            for token in iso_tokens:
                canonical = COUNTRY_ALIASES.get(token.lower())
                if canonical:
                    found.add(canonical)
    return sorted(found)


def _location_constraint_check(jd_text: str) -> tuple[bool, str]:
    allowed_countries = _extract_explicit_location_countries(jd_text)
    if len(allowed_countries) >= 2:
        candidate_country = _candidate_country()
        if candidate_country not in allowed_countries:
            return False, (
                f"Location constraint failed: explicit hiring countries are {', '.join(allowed_countries[:24])}; "
                f"candidate country {candidate_country} is not included."
            )
        return True, f"Location constraint passed: candidate country {candidate_country} is included in explicit hiring countries."
    jd_lower = jd_text.lower()
    candidate_country = _candidate_country().lower()
    if "only candidates residing in sweden" in jd_lower:
        if candidate_country == "sweden":
            return True, "JD requires Sweden residency and candidate country is Sweden."
        return False, "JD requires Sweden residency."
    return True, "No strict location constraint detected by rule-based check."


def constraint_score(jd_text: str, cv_text: str) -> tuple[float, str]:
    ok, note = _location_constraint_check(jd_text)
    return (100.0 if ok else 0.0), note


def hard_constraint_check(jd_text: str, mode: str = "medium") -> tuple[bool, bool, bool, str]:
    jd_lower = jd_text.lower()
    location_ok, location_note = _location_constraint_check(jd_text)
    if not location_ok:
        return False, False, False, location_note
    part_time_signals = [
        "part-time",
        "part time",
        "freelance",
        "contract",
        "hours/week",
        "hours per week",
        "hourly",
    ]
    remote_signals = [
        "remote",
        "work from home",
        "distributed",
        "asynchronous",
        "work independently and asynchronously",
    ]
    flexible_signals = [
        "hybrid",
        "flexible",
        "flexibility",
        "flexible schedule",
    ]
    hard_negative_signals = ["on-site", "onsite", "in-office", "office-based"]

    part_time_ok = any(s in jd_lower for s in part_time_signals)
    remote_ok = any(s in jd_lower for s in remote_signals)
    flexible_ok = remote_ok or any(s in jd_lower for s in flexible_signals)
    has_hard_negative = any(s in jd_lower for s in hard_negative_signals)

    mode_norm = (mode or "medium").strip().lower()
    if mode_norm not in {"hard", "medium", "soft"}:
        mode_norm = "medium"

    if mode_norm == "soft":
        if has_hard_negative and not flexible_ok:
            return False, part_time_ok, remote_ok, "Soft constraint failed: JD indicates on-site/in-office requirement."
        return True, part_time_ok, remote_ok, "Soft constraint passed."

    if mode_norm == "hard":
        if has_hard_negative and not remote_ok:
            return False, part_time_ok, remote_ok, "Hard constraint failed: JD indicates on-site/in-office requirement."
        if part_time_ok and remote_ok:
            return True, part_time_ok, remote_ok, "Hard constraint passed: JD indicates both part-time and remote."
        if not part_time_ok and not remote_ok:
            return False, part_time_ok, remote_ok, "Hard constraint failed: JD lacks part-time and remote signals."
        if not part_time_ok:
            return False, part_time_ok, remote_ok, "Hard constraint failed: JD lacks part-time/flexible signal."
        return False, part_time_ok, remote_ok, "Hard constraint failed: JD lacks remote signal."

    if has_hard_negative and not flexible_ok:
        return False, part_time_ok, remote_ok, "Medium constraint failed: JD indicates on-site/in-office requirement."
    if part_time_ok or flexible_ok:
        return True, part_time_ok, remote_ok, "Medium constraint passed: JD indicates flexible or remote-friendly setup."
    return False, part_time_ok, remote_ok, "Medium constraint failed: JD lacks flexible/remote signals."


def weighted_total(domain: float, technical: float, evidence: float, compliance: float) -> float:
    return (0.35 * domain) + (0.30 * technical) + (0.20 * evidence) + (0.15 * compliance)


def pass_fail_badge(is_pass: bool) -> str:
    if is_pass:
        return "**🟢 PASS**"
    return "**🔴 FAIL**"


def _parse_report_fields(report_text: str) -> tuple[float | None, str | None, str | None]:
    score_match = re.search(r"Total Score:\s+\*\*([0-9]+(?:\.[0-9]+)?)\/100\*\*", report_text)
    status_match = re.search(r"Status:\s+\*\*([A-Z ]+)\*\*", report_text)
    prereq_match = re.search(r"Result:.*?(PASS|FAIL)", report_text, re.IGNORECASE | re.DOTALL)
    score = float(score_match.group(1)) if score_match else None
    status = status_match.group(1).strip() if status_match else None
    prereq = prereq_match.group(1).upper().strip() if prereq_match else None
    return score, status, prereq


def build_daily_comparison(
    report_path: Path | None,
    current_jd_path: Path,
    current_total: float,
    current_status: str,
    current_prereq_pass: bool,
) -> str:
    if report_path is None:
        return "\n## Daily Comparison\n- Skipped: report path not provided.\n"

    run_folder = report_path.parent
    folder_name = run_folder.name
    folder_match = re.match(r"^(\d{6})_(\d{2})_(.+)$", folder_name)
    if not folder_match:
        return "\n## Daily Comparison\n- Skipped: run folder does not match naming convention.\n"

    day_key = folder_match.group(1)
    raw_root = run_folder.parent
    day_dirs = sorted(
        d for d in raw_root.iterdir() if d.is_dir() and re.match(rf"^{day_key}_\d{{2}}_.+$", d.name)
    )

    entries: list[dict] = []
    current_jd_name = current_jd_path.stem
    for d in day_dirs:
        jd_name = d.name.split("_", 2)[2]
        fit_files = sorted(d.glob("*_fit_report.md"))
        if fit_files:
            text = fit_files[-1].read_text(encoding="utf-8", errors="ignore")
            score, status, prereq = _parse_report_fields(text)
            if score is not None and status is not None:
                if prereq is None:
                    jd_candidate_path = Path("input/JD") / f"{jd_name}.txt"
                    if jd_candidate_path.exists():
                        jd_text = jd_candidate_path.read_text(encoding="utf-8", errors="ignore")
                        prereq = "PASS" if hard_constraint_check(jd_text)[0] else "FAIL"
                entries.append(
                    {
                        "jd": jd_name,
                        "score": score,
                        "status": status,
                        "prereq_pass": prereq == "PASS",
                    }
                )

    replaced = False
    for item in entries:
        if item["jd"] == current_jd_name:
            item["score"] = current_total
            item["status"] = current_status
            item["prereq_pass"] = current_prereq_pass
            replaced = True
            break
    if not replaced:
        entries.append(
            {
                "jd": current_jd_name,
                "score": current_total,
                "status": current_status,
                "prereq_pass": current_prereq_pass,
            }
        )

    ranked = sorted(
        entries,
        key=lambda x: (
            1 if x["prereq_pass"] else 0,
            x["score"],
        ),
        reverse=True,
    )
    current_rank = next((i + 1 for i, x in enumerate(ranked) if x["jd"] == current_jd_name), None)
    best = ranked[0] if ranked else None

    lines = []
    lines.append(f"\n## Daily Comparison ({day_key})")
    lines.append(f"- Compared JDs today: {len(ranked)}")
    if best is None:
        lines.append("- Best-fit JD today: N/A")
    else:
        lines.append(
            f"- Best-fit JD today: `{best['jd']}` ({best['score']:.2f}/100, "
            f"{pass_fail_badge(best['prereq_pass'])} prerequisite)"
        )
    if current_rank is not None:
        lines.append(f"- Current JD rank today: {current_rank}/{len(ranked)}")
    lines.append("- Ranking:")
    for idx, item in enumerate(ranked, start=1):
        lines.append(
            f"{idx}. `{item['jd']}` - {item['score']:.2f}/100 - {item['status']} - "
            f"Prerequisite {pass_fail_badge(item['prereq_pass'])}"
        )
    return "\n".join(lines) + "\n"


def build_report(
    jd_path: Path,
    cv_path: Path,
    total: float,
    domain: float,
    technical: float,
    evidence: float,
    compliance: float,
    matched_keywords: list[str],
    missing_keywords: list[str],
    constraint_note: str,
    hard_constraint_ok: bool,
    part_time_ok: bool,
    remote_ok: bool,
    hard_constraint_note: str,
    daily_comparison_section: str,
) -> str:
    if not hard_constraint_ok:
        status = "NOT COMPATIBLE"
    else:
        status = "READY TO APPLY" if total >= 85 else "NEEDS IMPROVEMENT" if total >= 70 else "NOT READY"
    top_missing = ", ".join(missing_keywords[:15]) if missing_keywords else "None"
    top_matched = ", ".join(matched_keywords[:15]) if matched_keywords else "None"
    prereq_badge = pass_fail_badge(hard_constraint_ok)
    part_time_badge = pass_fail_badge(part_time_ok)
    remote_badge = pass_fail_badge(remote_ok)
    return (
        f"# CV Fit Report\n\n"
        f"- JD: `{jd_path}`\n"
        f"- CV: `{cv_path}`\n"
        f"- Total Score: **{total:.2f}/100**\n"
        f"- Status: **{status}**\n\n"
        f"## Breakdown\n"
        f"- Domain/Experience Fit (35%): {domain:.2f}\n"
        f"- Core Technical Fit (30%): {technical:.2f}\n"
        f"- Evidence Quality (20%): {evidence:.2f}\n"
        f"- Compliance/Constraints (15%): {compliance:.2f}\n\n"
        f"## Keyword Match\n"
        f"- Matched (sample): {top_matched}\n"
        f"- Missing (sample): {top_missing}\n\n"
        f"## Constraint Check\n"
        f"- {constraint_note}\n"
        f"- {hard_constraint_note}\n"
        f"\n## Prerequisite Check (Part-time + Remote)\n"
        f"- Result: {prereq_badge}\n"
        f"- Part-time detected in JD: {part_time_badge}\n"
        f"- Remote detected in JD: {remote_badge}\n"
        f"{daily_comparison_section}"
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Simple JD-CV fit evaluator.")
    parser.add_argument("--jd", required=True, help="Path to JD file.")
    parser.add_argument("--cv", default="input/full_doc_stlye.txt", help="Path to CV base file.")
    parser.add_argument("--report", default="", help="Optional report output path (.md).")
    args = parser.parse_args()

    jd_path = Path(args.jd)
    cv_path = Path(args.cv)
    if not jd_path.exists():
        raise SystemExit(f"JD file not found: {jd_path}")
    if not cv_path.exists():
        raise SystemExit(f"CV file not found: {cv_path}")

    jd_raw = read_text(jd_path)
    cv_raw = read_text(cv_path)
    jd_clean = strip_tags(jd_raw)
    cv_clean = strip_tags(cv_raw)

    jd_tokens = tokenize(jd_clean)
    cv_tokens = tokenize(cv_clean)
    jd_tokens_set = set(jd_tokens)
    cv_tokens_set = set(cv_tokens)

    jd_keywords = top_keywords(jd_clean, limit=40)
    keyword_score, matched_keywords, missing_keywords = keyword_coverage_score(jd_keywords, cv_tokens_set)
    technical_score = technical_fit_score(jd_tokens_set, cv_tokens_set)
    domain_score = domain_fit_score(jd_tokens_set, cv_tokens_set)
    evidence_score = evidence_quality_score(cv_clean)
    compliance_score, constraint_note = constraint_score(jd_clean, cv_clean)
    hard_constraint_ok, part_time_ok, remote_ok, hard_constraint_note = hard_constraint_check(jd_clean)

    # Blend domain score with general keyword coverage for a more stable simple metric.
    domain_blended = (0.6 * domain_score) + (0.4 * keyword_score)
    total = weighted_total(domain_blended, technical_score, evidence_score, compliance_score)
    if not hard_constraint_ok:
        total = 0.0
    current_status = "NOT COMPATIBLE" if not hard_constraint_ok else (
        "READY TO APPLY" if total >= 85 else "NEEDS IMPROVEMENT" if total >= 70 else "NOT READY"
    )
    daily_comparison_section = build_daily_comparison(
        report_path=Path(args.report) if args.report else None,
        current_jd_path=jd_path,
        current_total=total,
        current_status=current_status,
        current_prereq_pass=hard_constraint_ok,
    )

    report = build_report(
        jd_path=jd_path,
        cv_path=cv_path,
        total=total,
        domain=domain_blended,
        technical=technical_score,
        evidence=evidence_score,
        compliance=compliance_score,
        matched_keywords=matched_keywords,
        missing_keywords=missing_keywords,
        constraint_note=constraint_note,
        hard_constraint_ok=hard_constraint_ok,
        part_time_ok=part_time_ok,
        remote_ok=remote_ok,
        hard_constraint_note=hard_constraint_note,
        daily_comparison_section=daily_comparison_section,
    )

    print(report)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        print(f"\nSaved report: {report_path}")


if __name__ == "__main__":
    main()
