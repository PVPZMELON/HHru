-- 002: аналитические представления.
-- Сопоставимая зарплата: только вакансии с обеими границами (kind = 'range'),
-- в одной валюте. Одностороннее значение (from_only/to_only) НЕ считается точной зарплатой.

CREATE VIEW v_vacancy_flat AS
SELECT
    v.id,
    v.source_id,
    v.title,
    v.published_at,
    v.employment,
    v.schedule,
    v.experience,
    v.salary_from,
    v.salary_to,
    v.salary_currency,
    v.salary_gross,
    v.salary_kind,
    v.salary_mid,
    v.url,
    v.description,
    v.data_origin,
    e.name  AS employer_name,
    e.id    AS employer_id,
    r.name  AS region_name,
    pr.name AS role_name
FROM vacancies v
LEFT JOIN employers e          ON e.id  = v.employer_id
LEFT JOIN regions r            ON r.id  = v.region_id
LEFT JOIN professional_roles pr ON pr.id = v.role_id;

CREATE VIEW v_skill_demand AS
SELECT
    s.id AS skill_id,
    s.name AS skill_name,
    count(*) AS vacancies_count
FROM vacancy_skills vs
JOIN skills s ON s.id = vs.skill_id
GROUP BY s.id, s.name;

CREATE VIEW v_last_etl_run AS
SELECT * FROM etl_runs ORDER BY started_at DESC, id DESC LIMIT 1;
