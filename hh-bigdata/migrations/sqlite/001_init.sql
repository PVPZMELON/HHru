-- 001 (SQLite): базовая схема. Даты хранятся текстом UTC «YYYY-MM-DD HH:MM:SS», JSON — текстом.
-- Это зеркало migrations/001_init.sql (PostgreSQL); различия только в типах.
-- Выполняется раннером src/db/migrate.py ровно один раз.

CREATE TABLE regions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT UNIQUE,                -- id области в источнике (если есть)
    name        TEXT NOT NULL,
    name_norm   TEXT NOT NULL UNIQUE        -- нижний регистр, без лишних пробелов
);

CREATE TABLE employers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT UNIQUE,                -- id работодателя в источнике (может отсутствовать)
    name        TEXT NOT NULL,
    name_norm   TEXT NOT NULL
);
-- Работодатели без id источника различаются по нормализованному названию.
CREATE UNIQUE INDEX uq_employers_name_norm_noid ON employers (name_norm) WHERE source_id IS NULL;
CREATE INDEX ix_employers_name_norm ON employers (name_norm);

CREATE TABLE professional_roles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT UNIQUE,
    name        TEXT NOT NULL,
    name_norm   TEXT NOT NULL UNIQUE
);

CREATE TABLE skills (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,              -- каноническое написание
    name_norm   TEXT NOT NULL UNIQUE
);

CREATE TABLE etl_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    finished_at         TEXT,
    status              TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running', 'success', 'partial', 'failed')),
    data_origin         TEXT NOT NULL CHECK (data_origin IN ('api', 'import', 'synthetic')),
    source_description  TEXT,               -- например: "hh.ru API, запросы: ..." / имя файла
    params              TEXT,
    raw_path            TEXT,               -- путь к сохранённому сырому JSONL
    fetched_count       INTEGER NOT NULL DEFAULT 0,
    valid_count         INTEGER NOT NULL DEFAULT 0,
    duplicates_removed  INTEGER NOT NULL DEFAULT 0,
    rejected_count      INTEGER NOT NULL DEFAULT 0,
    inserted_count      INTEGER NOT NULL DEFAULT 0,
    updated_count       INTEGER NOT NULL DEFAULT 0,
    unchanged_count     INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT
);

CREATE TABLE vacancies (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL DEFAULT 'hh.ru',
    source_id           TEXT NOT NULL,
    title               TEXT NOT NULL,
    employer_id         INTEGER REFERENCES employers (id),
    region_id           INTEGER REFERENCES regions (id),
    role_id             INTEGER REFERENCES professional_roles (id),
    published_at        TEXT,
    source_updated_at   TEXT,
    employment          TEXT,               -- тип занятости
    schedule            TEXT,               -- график работы
    experience          TEXT,               -- требуемый опыт
    -- Зарплата «как в источнике»
    salary_from         NUMERIC(14, 2),
    salary_to           NUMERIC(14, 2),
    salary_currency     CHAR(3),
    salary_gross        BOOLEAN,            -- NULL = источник не сообщил
    -- Аналитическая зарплата (правила см. src/etl/salary.py и docs/METRICS.md)
    salary_kind         TEXT NOT NULL DEFAULT 'none'
                        CHECK (salary_kind IN ('range', 'from_only', 'to_only', 'none', 'invalid')),
    salary_mid          NUMERIC(14, 2),     -- заполняется только для kind = 'range'
    url                 TEXT,
    description         TEXT,
    data_origin         TEXT NOT NULL CHECK (data_origin IN ('api', 'import', 'synthetic')),
    content_hash        TEXT NOT NULL,      -- хэш содержимого для определения изменений
    first_seen_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    last_seen_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    etl_run_id          INTEGER REFERENCES etl_runs (id),
    CONSTRAINT uq_vacancies_source UNIQUE (source, source_id),
    CONSTRAINT ck_salary_bounds CHECK (
        (salary_from IS NULL OR salary_from > 0) AND
        (salary_to IS NULL OR salary_to > 0) AND
        (salary_from IS NULL OR salary_to IS NULL OR salary_from <= salary_to)
    ),
    CONSTRAINT ck_salary_mid CHECK (salary_kind = 'range' OR salary_mid IS NULL)
);

CREATE INDEX ix_vacancies_published   ON vacancies (published_at);
CREATE INDEX ix_vacancies_region      ON vacancies (region_id);
CREATE INDEX ix_vacancies_role        ON vacancies (role_id);
CREATE INDEX ix_vacancies_employer    ON vacancies (employer_id);
CREATE INDEX ix_vacancies_experience  ON vacancies (experience);
CREATE INDEX ix_vacancies_salary      ON vacancies (salary_currency, salary_kind) WHERE salary_mid IS NOT NULL;

CREATE TABLE vacancy_skills (
    vacancy_id  BIGINT  NOT NULL REFERENCES vacancies (id) ON DELETE CASCADE,
    skill_id    INTEGER NOT NULL REFERENCES skills (id),
    origin      TEXT NOT NULL DEFAULT 'structured' CHECK (origin IN ('structured', 'text')),
    PRIMARY KEY (vacancy_id, skill_id)
);
CREATE INDEX ix_vacancy_skills_skill ON vacancy_skills (skill_id);

CREATE TABLE data_quality_issues (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    etl_run_id  INTEGER NOT NULL REFERENCES etl_runs (id) ON DELETE CASCADE,
    source_id   TEXT,
    issue_type  TEXT NOT NULL,
    field       TEXT,
    details     TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);
CREATE INDEX ix_dqi_run ON data_quality_issues (etl_run_id, issue_type);
