"""Генератор СИНТЕТИЧЕСКИХ демонстрационных вакансий.

Это НЕ реальные данные hh.ru. Набор нужен, чтобы показать работу конвейера и дашборда без токена и
доступа к API. Все записи помечаются data_origin = 'synthetic' (идентификаторы вида demo-000001,
работодатели «Демо-компания N», ссылок на источник нет), а дашборд показывает предупреждение.

Зависимости зарплаты от региона, опыта и навыков здесь ЗАДАНЫ ГЕНЕРАТОРОМ — выводы о реальном рынке
труда по этому набору делать нельзя. В набор намеренно добавлены «грязные» записи (дубли, конфликтующие
версии, некорректные зарплаты, пропуски), чтобы проверялись очистка и контроль качества.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

REGIONS = {  # название -> множитель зарплаты (параметр генератора)
    "Москва": 1.25, "Санкт-Петербург": 1.10, "Новосибирск": 0.92, "Екатеринбург": 0.95,
    "Казань": 0.90, "Нижний Новгород": 0.88, "Краснодар": 0.87, "Самара": 0.85,
    "Ростов-на-Дону": 0.86, "Воронеж": 0.82,
}
REGION_WEIGHTS = [30, 18, 8, 8, 7, 6, 6, 6, 5, 6]

# роль -> (базовая зарплата, ядро навыков, дополнительные навыки)
ROLES = {
    "Программист, разработчик": (150_000, ["Python", "SQL", "Git"],
                                 ["Django", "FastAPI", "PostgreSQL", "Docker", "Linux", "REST API", "Redis", "Java", "JavaScript", "React"]),
    "Аналитик": (120_000, ["SQL", "Excel"],
                 ["Python", "Power BI", "Tableau", "Статистика", "A/B тесты", "Pandas", "ClickHouse"]),
    "Дата-сайентист": (190_000, ["Python", "Machine Learning"],
                       ["Pandas", "NumPy", "Scikit-learn", "PyTorch", "TensorFlow", "SQL", "Apache Spark", "Статистика"]),
    "Инженер данных": (200_000, ["Python", "SQL", "ETL"],
                       ["Apache Airflow", "Apache Kafka", "Apache Spark", "PostgreSQL", "ClickHouse", "Docker", "Hadoop", "Linux"]),
    "DevOps-инженер": (210_000, ["Linux", "Docker"],
                       ["Kubernetes", "Terraform", "CI/CD", "Jenkins", "Python", "AWS", "Git"]),
    "Тестировщик": (100_000, ["Git"],
                    ["Python", "Selenium", "Pytest", "SQL", "Jira", "REST API"]),
}
ROLE_WEIGHTS = [28, 22, 12, 12, 12, 14]
TITLES = {
    "Программист, разработчик": ["Python-разработчик", "Backend-разработчик (Python)", "Java-разработчик", "Fullstack-разработчик"],
    "Аналитик": ["Аналитик данных", "BI-аналитик", "Продуктовый аналитик", "Системный аналитик"],
    "Дата-сайентист": ["Data Scientist", "ML-инженер", "Специалист по машинному обучению"],
    "Инженер данных": ["Data Engineer", "Инженер данных", "ETL-разработчик"],
    "DevOps-инженер": ["DevOps-инженер", "SRE-инженер", "Инженер по инфраструктуре"],
    "Тестировщик": ["QA-инженер", "Тестировщик ПО", "Автотестировщик (Python)"],
}
EXPERIENCE = [("Нет опыта", 0.65, 12), ("От 1 года до 3 лет", 0.9, 38), ("От 3 до 6 лет", 1.25, 38), ("Более 6 лет", 1.6, 12)]
EMPLOYMENT = [("Полная занятость", 85), ("Частичная занятость", 5), ("Проектная работа", 7), ("Стажировка", 3)]
SCHEDULE = [("Полный день", 55), ("Удаленная работа", 28), ("Гибкий график", 14), ("Сменный график", 3)]
SKILL_BONUS = {  # условная надбавка, ЗАДАНА генератором
    "Apache Spark": 0.10, "Apache Kafka": 0.08, "Kubernetes": 0.09, "PyTorch": 0.08, "Terraform": 0.07,
    "ClickHouse": 0.06, "Apache Airflow": 0.05, "Scikit-learn": 0.04,
}
SKILL_ALIASES = {"Python": ["питон"], "PostgreSQL": ["postgres"], "Docker": ["докер"], "Linux": ["линукс"]}


def _weighted(rng: random.Random, pairs):
    values, weights = zip(*[(p[:-1] if len(p) > 2 else p[0], p[-1]) for p in pairs])
    return rng.choices(values, weights=weights, k=1)[0]


def generate(n: int = 600, seed: int = 42, now: datetime | None = None, days: int = 60,
             with_defects: bool = True) -> list[dict]:
    """Возвращает список словарей в формате ответа hh.ru. Детерминирован при фиксированных seed и now."""
    rng = random.Random(seed)
    now = now or datetime.now(timezone.utc)
    employers = [f"Демо-компания {i:03d}" for i in range(1, 121)]
    emp_weights = [1 / (i + 1) ** 0.7 for i in range(len(employers))]
    region_names = list(REGIONS)
    role_names = list(ROLES)
    items: list[dict] = []

    for i in range(1, n + 1):
        role = rng.choices(role_names, weights=ROLE_WEIGHTS, k=1)[0]
        base, core, extra = ROLES[role]
        region = rng.choices(region_names, weights=REGION_WEIGHTS, k=1)[0]
        exp_name, exp_mult, _ = rng.choices(EXPERIENCE, weights=[e[2] for e in EXPERIENCE], k=1)[0]
        skills = list(core) + rng.sample(extra, k=min(len(extra), rng.randint(1, 4)))
        bonus = 1 + sum(SKILL_BONUS.get(s, 0) for s in skills)
        midpoint = base * REGIONS[region] * exp_mult * bonus * math.exp(rng.gauss(0, 0.14))

        published = now - timedelta(days=rng.random() * days, hours=rng.random() * 5)
        employer = rng.choices(employers, weights=emp_weights, k=1)[0]
        item: dict = {
            "id": f"demo-{i:06d}",
            "name": rng.choice(TITLES[role]),
            "area": {"id": None, "name": region},
            "employer": {"id": None, "name": employer},
            "professional_roles": [{"id": None, "name": role}],
            "published_at": published.astimezone(timezone(timedelta(hours=3))).strftime("%Y-%m-%dT%H:%M:%S%z"),
            "experience": {"name": exp_name},
            "employment": {"name": _weighted(rng, EMPLOYMENT)},
            "schedule": {"name": _weighted(rng, SCHEDULE)},
            "alternate_url": None,
            "description": "<p>Демонстрационная вакансия (синтетические данные).</p><ul>"
                           + "".join(f"<li>{s}</li>" for s in rng.sample(skills, k=min(2, len(skills)))) + "</ul>",
        }
        if rng.random() < 0.88:
            shown = [rng.choice(SKILL_ALIASES[s]) if s in SKILL_ALIASES and rng.random() < 0.15 else s for s in skills]
            item["key_skills"] = [{"name": s} for s in shown]

        roll = rng.random()
        if roll < 0.55:  # зарплата указана
            gross = rng.random() < 0.6
            currency = rng.choices(["RUR", "USD", "EUR"], weights=[95, 3, 2], k=1)[0]
            scale = 1.0 if currency == "RUR" else (1 / 90 if currency == "USD" else 1 / 100)
            mid = round(midpoint * scale, -2 if currency == "RUR" else -1)
            kind = rng.random()
            if kind < 0.70:
                low, high = round(mid * 0.85, -2), round(mid * 1.15, -2)
            elif kind < 0.90:
                low, high = round(mid * 0.9, -2), None
            else:
                low, high = None, round(mid * 1.1, -2)
            item["salary"] = {"from": low, "to": high, "currency": currency, "gross": gross}
        if rng.random() < 0.03:
            item.pop("employer")
        if rng.random() < 0.05:
            item.pop("professional_roles")
        if rng.random() < 0.03:
            item.pop("experience")
        items.append(item)

    if with_defects and n >= 50:
        defects: list[dict] = []
        for src in rng.sample(items, k=max(2, n // 50)):  # точные дубли
            defects.append(dict(src))
        for src in rng.sample(items, k=max(2, n // 100)):  # конфликтующие версии: изменилась зарплата
            conflict = dict(src)
            conflict["salary"] = {"from": 100_000, "to": 140_000, "currency": "RUR", "gross": True}
            defects.append(conflict)
        bad_salaries = [
            {"from": 300_000, "to": 100_000, "currency": "RUR", "gross": True},      # from > to
            {"from": -5, "to": 50_000, "currency": "RUR", "gross": False},           # отрицательное
            {"from": "abc", "to": None, "currency": "RUR", "gross": True},           # не число
            {"from": 90_000_000, "to": 95_000_000, "currency": "RUR", "gross": True},  # лишние нули
            {"from": 100_000, "to": 120_000, "currency": None, "gross": True},       # нет валюты
        ]
        for k, salary in enumerate(bad_salaries):
            bad = dict(rng.choice(items))
            bad["id"] = f"demo-bad-{k + 1:02d}"
            bad["salary"] = salary
            defects.append(bad)
        defects.append({"id": "demo-bad-noname", "area": {"name": "Москва"}})       # без названия
        defects.append({"name": "Вакансия без id"})                                  # без id
        items.extend(defects)
        rng.shuffle(items)
    return items
