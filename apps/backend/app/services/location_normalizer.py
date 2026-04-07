from __future__ import annotations

import re

US_STATE_CODES = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
}

COUNTRY_ALIASES = {
    "usa": "United States",
    "u.s.a": "United States",
    "united states": "United States",
    "us": "United States",
    "uk": "United Kingdom",
    "u.k": "United Kingdom",
    "united kingdom": "United Kingdom",
    "uae": "United Arab Emirates",
    "u.a.e": "United Arab Emirates",
    "south korea": "South Korea",
    "korea": "South Korea",
    "korea, republic of": "South Korea",
    "republic of korea": "South Korea",
    "viet nam": "Vietnam",
}

REGION_HINTS = {
    "seoul": "South Korea",
    "incheon": "South Korea",
    "busan": "South Korea",
    "san francisco bay area": "United States",
    "new york": "United States",
    "greater montreal metropolitan area": "Canada",
    "greater kolkata area": "India",
    "greater madrid metropolitan area": "Spain",
    "santiago metropolitan area": "Chile",
    "brabantine city row": "Belgium",
}

COUNTRY_TO_REGION = {
    "United States": "North America",
    "Canada": "North America",
    "Mexico": "North America",
    "Brazil": "South America",
    "Argentina": "South America",
    "Chile": "South America",
    "Colombia": "South America",
    "Venezuela": "South America",
    "United Kingdom": "Western Europe",
    "France": "Western Europe",
    "Germany": "Western Europe",
    "Netherlands": "Western Europe",
    "Belgium": "Western Europe",
    "Spain": "Western Europe",
    "Portugal": "Western Europe",
    "Finland": "Western Europe",
    "Poland": "Eastern Europe",
    "Ukraine": "Eastern Europe",
    "Russia": "Eastern Europe",
    "Slovakia": "Eastern Europe",
    "South Korea": "Northeast Asia",
    "Japan": "Northeast Asia",
    "China": "Northeast Asia",
    "Mongolia": "Northeast Asia",
    "Vietnam": "Southeast Asia",
    "Thailand": "Southeast Asia",
    "Singapore": "Southeast Asia",
    "Philippines": "Southeast Asia",
    "Indonesia": "Southeast Asia",
    "Malaysia": "Southeast Asia",
    "India": "South Asia",
    "Pakistan": "South Asia",
    "Bangladesh": "South Asia",
    "Saudi Arabia": "Middle East",
    "United Arab Emirates": "Middle East",
    "Egypt": "Middle East",
    "South Africa": "Africa",
}

REGION_MEMBERSHIP_MAP = {
    "European Union": [
        "Austria",
        "Belgium",
        "Bulgaria",
        "Croatia",
        "Cyprus",
        "Czechia",
        "Denmark",
        "Estonia",
        "Finland",
        "France",
        "Germany",
        "Greece",
        "Hungary",
        "Ireland",
        "Italy",
        "Latvia",
        "Lithuania",
        "Luxembourg",
        "Malta",
        "Netherlands",
        "Poland",
        "Portugal",
        "Romania",
        "Slovakia",
        "Slovenia",
        "Spain",
        "Sweden",
    ],
}

REGION_ALIASES = {
    "north america": "North America",
    "america": "North America",
    "south america": "South America",
    "latin america": "South America",
    "western europe": "Western Europe",
    "west europe": "Western Europe",
    "eu": "European Union",
    "european union": "European Union",
    "eastern europe": "Eastern Europe",
    "east europe": "Eastern Europe",
    "northeast asia": "Northeast Asia",
    "north east asia": "Northeast Asia",
    "southeast asia": "Southeast Asia",
    "south east asia": "Southeast Asia",
    "south asia": "South Asia",
    "middle east": "Middle East",
    "africa": "Africa",
    "other": "Other",
}


def normalize_country(raw_location: str) -> tuple[str, str, float]:
    raw = str(raw_location or "").strip()
    if not raw:
        return "", "", 0.0
    lower = raw.lower()
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    last = parts[-1] if parts else raw
    last_lower = last.lower()

    if last.upper() in US_STATE_CODES:
        return "United States", last.upper(), 0.95

    if last_lower in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[last_lower], last, 0.98

    for hint, country in REGION_HINTS.items():
        if hint in lower:
            return country, hint, 0.9

    if re.fullmatch(r"[A-Z]{2,3}", last):
        if last == "UK":
            return "United Kingdom", "UK", 0.9
        if last == "UAE":
            return "United Arab Emirates", "UAE", 0.9

    clean_last = re.sub(r"\s+", " ", last).strip()
    if clean_last.lower() in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[clean_last.lower()], clean_last, 0.85

    return clean_last, clean_last, 0.6


def infer_region(country: str) -> str:
    c = str(country or "").strip()
    if not c:
        return ""
    return COUNTRY_TO_REGION.get(c, "Other")


def canonicalize_region(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    key = " ".join(raw.lower().split())
    if key in REGION_ALIASES:
        return REGION_ALIASES[key]
    return raw
