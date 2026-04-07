from __future__ import annotations

import re
from functools import lru_cache

LANGUAGE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Python", re.compile(r"\bpython\b", re.IGNORECASE)),
    ("JavaScript", re.compile(r"\bjavascript\b", re.IGNORECASE)),
    ("TypeScript", re.compile(r"\btypescript\b", re.IGNORECASE)),
    ("Java", re.compile(r"\bjava\b", re.IGNORECASE)),
    ("Go", re.compile(r"\bgolang\b|\bgo\b", re.IGNORECASE)),
    ("Rust", re.compile(r"\brust\b", re.IGNORECASE)),
    ("Kotlin", re.compile(r"\bkotlin\b", re.IGNORECASE)),
    ("Swift", re.compile(r"\bswift\b", re.IGNORECASE)),
    ("PHP", re.compile(r"\bphp\b", re.IGNORECASE)),
    ("Ruby", re.compile(r"\bruby\b", re.IGNORECASE)),
    ("Scala", re.compile(r"\bscala\b", re.IGNORECASE)),
    ("Dart", re.compile(r"\bdart\b", re.IGNORECASE)),
    ("C++", re.compile(r"\bc\+\+\b", re.IGNORECASE)),
    ("C#", re.compile(r"(?<!\w)c#(?!\w)|\bc-sharp\b", re.IGNORECASE)),
    ("C#", re.compile(r"(?<!\w)\.net(?!\w)|\basp\.net\b|\bdotnet\b", re.IGNORECASE)),
    ("SQL", re.compile(r"\bsql\b|\bpostgres(?:ql)?\b|\bmysql\b|\bsqlite\b", re.IGNORECASE)),
    ("HTML", re.compile(r"\bhtml(?:5)?\b", re.IGNORECASE)),
    ("CSS", re.compile(r"\bcss(?:3)?\b", re.IGNORECASE)),
]
INVALID_LANGUAGE_VALUES = {"", "-", "unknown", "n/a", "na", "none", "null"}

TITLE_HINTS: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"\bc/c\+\+\b|\bc\+\+\b", re.IGNORECASE), ["C++"]),
    (re.compile(r"\bfrontend\b|\bfront-end\b", re.IGNORECASE), ["JavaScript", "TypeScript", "HTML", "CSS"]),
    (re.compile(r"\breact\b|\bvue\b|\bangular\b", re.IGNORECASE), ["JavaScript", "TypeScript"]),
    (re.compile(r"\bnode(?:\.js)?\b", re.IGNORECASE), ["JavaScript"]),
    (re.compile(r"\b\.net\b|\basp\.net\b|\bdotnet\b", re.IGNORECASE), ["C#"]),
    (re.compile(r"\bjava\b", re.IGNORECASE), ["Java"]),
    (re.compile(r"\bpython\b", re.IGNORECASE), ["Python"]),
    (re.compile(r"\bdevops\b", re.IGNORECASE), ["Python"]),
]

# Phrase -> canonical programming languages (EntityRuler-like KB).
SKILL_TO_LANGUAGES: dict[str, list[str]] = {
    "python": ["Python"],
    "django": ["Python"],
    "flask": ["Python"],
    "fastapi": ["Python"],
    "pandas": ["Python"],
    "numpy": ["Python"],
    "java": ["Java"],
    "spring": ["Java"],
    "spring boot": ["Java"],
    "kotlin": ["Kotlin", "Java"],
    "scala": ["Scala", "Java"],
    "javascript": ["JavaScript"],
    "typescript": ["TypeScript", "JavaScript"],
    "node.js": ["JavaScript"],
    "nodejs": ["JavaScript"],
    "react": ["JavaScript", "TypeScript"],
    "next.js": ["JavaScript", "TypeScript"],
    "nextjs": ["JavaScript", "TypeScript"],
    "vue": ["JavaScript", "TypeScript"],
    "angular": ["TypeScript", "JavaScript"],
    "php": ["PHP"],
    "laravel": ["PHP"],
    "symfony": ["PHP"],
    "ruby": ["Ruby"],
    "rails": ["Ruby"],
    "go": ["Go"],
    "golang": ["Go"],
    "rust": ["Rust"],
    "swift": ["Swift"],
    "swiftui": ["Swift"],
    "c++": ["C++"],
    "c#": ["C#"],
    ".net": ["C#"],
    "asp.net": ["C#"],
    "dotnet": ["C#"],
    "sql": ["SQL"],
    "postgresql": ["SQL"],
    "mysql": ["SQL"],
    "sqlite": ["SQL"],
    "html": ["HTML"],
    "css": ["CSS"],
}


@lru_cache(maxsize=1)
def _load_spacy_entity_ruler():
    try:
        import spacy

        nlp = spacy.blank("en")
        ruler = nlp.add_pipe("entity_ruler")
        patterns = [{"label": "SKILL", "pattern": phrase} for phrase in sorted(SKILL_TO_LANGUAGES.keys(), key=len, reverse=True)]
        ruler.add_patterns(patterns)
        return nlp
    except Exception:
        return None


def _extract_with_spacy_entity_ruler(text: str) -> list[str]:
    nlp = _load_spacy_entity_ruler()
    if nlp is None:
        return []
    doc = nlp(str(text or ""))
    found: set[str] = set()
    for ent in doc.ents:
        for lang in SKILL_TO_LANGUAGES.get(ent.text.strip().lower(), []):
            found.add(lang)
    return sorted(found)


def extract_programming_languages(text: str, *, allow_unknown: bool = False) -> list[str]:
    sample = str(text or "").strip()
    if not sample:
        return ["Unknown"] if allow_unknown else []
    found: list[str] = []
    for language, pattern in LANGUAGE_PATTERNS:
        if pattern.search(sample):
            found.append(language)
    if not found:
        for pattern, hinted in TITLE_HINTS:
            if pattern.search(sample):
                found.extend(hinted)
    # Upgrade unknown cases by rule-based NER via spaCy EntityRuler.
    if not found:
        found.extend(_extract_with_spacy_entity_ruler(sample))
    unique = sorted({str(x).strip() for x in found if str(x).strip()})
    unique = [x for x in unique if x.lower() not in INVALID_LANGUAGE_VALUES]
    if not unique and allow_unknown:
        return ["Unknown"]
    return unique
