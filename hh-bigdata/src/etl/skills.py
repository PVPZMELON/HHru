"""Извлечение и нормализация навыков.

Два источника:
1. Структурированное поле key_skills вакансии (origin = 'structured') — основной и самый надёжный.
2. Текст описания (origin = 'text') — осторожный словарный поиск по ограниченному списку
   технологий с границами слов. Это НЕ NLP-модель: она находит только явные упоминания
   известных технологий и может пропустить синонимы или ловить упоминания вне требований.
   В аналитике происхождение навыка сохраняется, чтобы его можно было отфильтровать.
"""
from __future__ import annotations

import re
from typing import Iterable

# Каноническое имя -> алиасы (в нижнем регистре). Алиасы используются и для нормализации
# структурированных навыков, и для поиска в тексте.
SKILL_CATALOG: dict[str, list[str]] = {
    "Python": ["python", "питон"],
    "SQL": ["sql"],
    "PostgreSQL": ["postgresql", "postgres", "постгрес"],
    "MySQL": ["mysql"],
    "MongoDB": ["mongodb", "mongo db"],
    "Redis": ["redis"],
    "ClickHouse": ["clickhouse"],
    "Java": ["java"],
    "Kotlin": ["kotlin"],
    "JavaScript": ["javascript", "js"],
    "TypeScript": ["typescript"],
    "React": ["react", "react.js", "reactjs"],
    "Vue.js": ["vue", "vue.js", "vuejs"],
    "Node.js": ["node.js", "nodejs", "node js"],
    "C++": ["c++"],
    "C#": ["c#"],
    ".NET": [".net", "dotnet"],
    "Go": ["golang"],
    "PHP": ["php"],
    "Ruby": ["ruby"],
    "Scala": ["scala"],
    "Rust": ["rust"],
    "Django": ["django"],
    "Flask": ["flask"],
    "FastAPI": ["fastapi"],
    "Spring": ["spring"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "Apache Spark": ["spark", "pyspark", "apache spark"],
    "Apache Kafka": ["kafka", "apache kafka"],
    "Apache Airflow": ["airflow", "apache airflow"],
    "Hadoop": ["hadoop"],
    "Docker": ["docker", "докер"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Git": ["git"],
    "Linux": ["linux", "линукс"],
    "CI/CD": ["ci/cd", "cicd"],
    "Jenkins": ["jenkins"],
    "Terraform": ["terraform"],
    "AWS": ["aws"],
    "Azure": ["azure"],
    "ETL": ["etl"],
    "Power BI": ["power bi", "powerbi"],
    "Tableau": ["tableau"],
    "Excel": ["excel", "эксель"],
    "Machine Learning": ["machine learning", "машинное обучение", "ml"],
    "Scikit-learn": ["scikit-learn", "sklearn"],
    "TensorFlow": ["tensorflow"],
    "PyTorch": ["pytorch"],
    "REST API": ["rest api", "restful", "rest"],
    "Selenium": ["selenium"],
    "Pytest": ["pytest"],
    "Jira": ["jira"],
    "1С": ["1с", "1c"],
    "Статистика": ["статистика", "статистический анализ"],
    "A/B тесты": ["a/b тесты", "a/b-тесты", "ab тесты", "a/b тестирование"],
}

_ALIAS_TO_CANON: dict[str, str] = {}
for _canon, _aliases in SKILL_CATALOG.items():
    _ALIAS_TO_CANON[_canon.lower()] = _canon
    for _a in _aliases:
        _ALIAS_TO_CANON[_a.lower()] = _canon


def _alias_pattern(alias: str) -> re.Pattern:
    # Границы «слова», учитывающие символы вроде + # . / в названиях технологий.
    return re.compile(r"(?<![\w+#./])" + re.escape(alias) + r"(?![\w+#]|\.\w)", re.IGNORECASE)


# Короткие и неоднозначные алиасы не используются для поиска в свободном тексте.
_TEXT_EXCLUDED = {"go", "rest", "ml", "js", "spring", "rust", "ruby", "git", "excel"}
_TEXT_PATTERNS: list[tuple[str, re.Pattern]] = []
for _canon, _aliases in SKILL_CATALOG.items():
    for _a in {_canon.lower(), *_aliases}:
        if _a in _TEXT_EXCLUDED or len(_a) < 2:
            continue
        _TEXT_PATTERNS.append((_canon, _alias_pattern(_a)))
# «Git», «Excel», «Spring», «Rust», «Ruby» достаточно однозначны — разрешаем при заглавной букве.
_CAPITALIZED_ONLY = {"Git": "Git", "Excel": "Excel", "Spring": "Spring", "Rust": "Rust", "Ruby": "Ruby", "Go": "Golang"}
_CAP_PATTERNS = [(c, re.compile(r"(?<![\w+#./])" + re.escape(w) + r"(?![\w+#])")) for c, w in _CAPITALIZED_ONLY.items()]


def normalize_skill_name(raw: str) -> tuple[str, str] | None:
    """Возвращает (каноническое_имя, нормализованный_ключ) или None для пустых значений."""
    if raw is None:
        return None
    name = re.sub(r"\s+", " ", str(raw)).strip()
    if not name or len(name) > 80:
        return None
    canon = _ALIAS_TO_CANON.get(name.lower(), name)
    return canon, canon.lower()


def extract_structured(key_skills: Iterable | None) -> list[str]:
    """key_skills из API: [{'name': 'Python'}, ...] или список строк."""
    result: dict[str, str] = {}
    for item in key_skills or []:
        raw = item.get("name") if isinstance(item, dict) else item
        normalized = normalize_skill_name(raw)
        if normalized:
            canon, key = normalized
            result.setdefault(key, canon)
    return list(result.values())


def extract_from_text(text: str | None) -> list[str]:
    """Явные упоминания известных технологий в описании."""
    if not text:
        return []
    found: dict[str, str] = {}
    for canon, pattern in _TEXT_PATTERNS:
        if canon not in found and pattern.search(text):
            found[canon] = canon
    for canon, pattern in _CAP_PATTERNS:
        if canon not in found and pattern.search(text):
            found[canon] = canon
    return sorted(found.values())
