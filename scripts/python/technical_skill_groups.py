"""Static technical skill groups and color rules used by CV renderer."""

TECHNICAL_SKILL_GROUPS = {
    "Languages": [
        "Java",
        "Python",
        "JavaScript",
        "JavaScript (ES6+)",
        "TypeScript",
        "SQL",
    ],
    "Frontend": ["React", "HTML5", "CSS3", "Angular", "Vite", "D3 Geo", "TopoJSON", "world-atlas"],
    "Backend/Frameworks": [
        "FastAPI",
        "Flask",
        "Django",
        "Spring Boot",
        "Starlette",
        "SQLAlchemy",
        "Pydantic",
        "APScheduler",
        "Uvicorn",
    ],
    "Databases": ["PostgreSQL", "Oracle", "SQL Server", "MySQL", "SQLite"],
    "Data Tools": [
        "pandas",
        "numpy",
        "ExcelJS",
        "openpyxl",
        "XlsxWriter",
        "FAISS",
        "sentence-transformers",
        "OBIEE",
        "ODI",
    ],
    "Automation & Crawling": ["Playwright", "BeautifulSoup"],
    "LLM/RAG": ["LangChain", "Chroma", "qwen2.5"],
    "Security": ["Azure MSAL", "JWT", "passlib", "cryptography", "Spring Security"],
    "DevOps": ["Jenkins", "Docker", "docker-compose", "Nginx", "Linux"],
    "Others": ["Lodash", "RxJS", "Axios", "requests", "python-pptx", "Jinja2"],
}

# Color strategy (positive readability):
# - green: core strengths you want recruiters to notice first.
# - orange: supporting stack/tools that provide breadth.
# Color names must exist in render color map (default or .env override).
TECHNICAL_SKILL_GROUP_COLORS = {
    "Languages": "green",
    "Frontend": "orange",
    "Backend/Frameworks": "green",
    "Databases": "orange",
    "Data Tools": "orange",
    "Automation & Crawling": "orange",
    "LLM/RAG": "green",
    "Security": "green",
    "DevOps": "green",
    "Others": "orange",
}
