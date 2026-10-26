"""Клиент официального API hh.ru (https://api.hh.ru) для сбора вакансий.

Используются только документированные методы:
  GET /vacancies        — поиск (параметры text, area, page, per_page, period); ответ: items, found, pages, page
  GET /vacancies/{id}   — подробности (описание, key_skills)

Принципы работы с источником:
* вежливость: пауза между запросами, общий лимит запросов на запуск, ограничение объёма выгрузки;
* временные сбои (сеть, таймаут, HTTP 429, 5xx) — ограниченное число повторов с экспоненциальной
  паузой (для 429 учитывается Retry-After); бесконечных циклов нет;
* HTTP 401/403 (в т.ч. требование авторизации или CAPTCHA) — НЕ обходятся: сбор останавливается
  с понятным сообщением, а пользователю предлагается импорт файла;
* глубина поиска hh.ru ограничена 2000 результатами на запрос (page * per_page) — учитывается.

Токен приложения (если нужен) передаётся только через переменную окружения HH_API_TOKEN.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

import requests

from src.config import CollectorSettings

log = logging.getLogger(__name__)

HH_MAX_DEPTH = 2000          # максимум результатов, доступных по одному поисковому запросу
MAX_RETRY_AFTER_SEC = 60.0   # не ждём дольше, даже если сервер просит больше
RETRY_STATUSES = {429, 500, 502, 503, 504}


class ApiError(Exception):
    """Ошибка API, после которой продолжать этот запрос нельзя."""


class AccessDenied(ApiError):
    """401/403: нужна авторизация, нет прав или включена защита (CAPTCHA). Не обходится."""


class RequestBudgetExceeded(ApiError):
    """Исчерпан лимит запросов за запуск (COLLECT_MAX_REQUESTS)."""


@dataclass
class CollectResult:
    items: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    requests_made: int = 0
    found_by_query: dict[str, int] = field(default_factory=dict)
    details_fetched: int = 0
    stopped_reason: str | None = None  # None = штатное завершение

    @property
    def complete(self) -> bool:
        return self.stopped_reason is None and not self.errors


class HhClient:
    def __init__(self, settings: CollectorSettings, session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.cfg = settings
        self.session = session or requests.Session()
        self._sleep = sleep
        self.requests_made = 0
        headers = {
            "User-Agent": settings.user_agent,
            "HH-User-Agent": settings.user_agent,
            "Accept": "application/json",
        }
        if settings.token:
            headers["Authorization"] = f"Bearer {settings.token}"
        self.session.headers.update(headers)

    # ---------- низкоуровневый запрос ----------

    def _wait_time(self, attempt: int, response: requests.Response | None) -> float:
        if response is not None and response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.replace(".", "", 1).isdigit():
                return min(float(retry_after), MAX_RETRY_AFTER_SEC)
        return min(2.0 ** attempt, MAX_RETRY_AFTER_SEC)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        url = f"{self.cfg.api_base.rstrip('/')}{path}"
        attempts = self.cfg.max_retries + 1
        last_problem = ""
        for attempt in range(attempts):
            if self.requests_made >= self.cfg.max_requests:
                raise RequestBudgetExceeded(f"достигнут лимит запросов за запуск ({self.cfg.max_requests})")
            self.requests_made += 1
            response: requests.Response | None = None
            try:
                response = self.session.get(url, params=params, timeout=self.cfg.timeout_sec)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_problem = f"{type(exc).__name__}"
            else:
                status = response.status_code
                if status == 200:
                    try:
                        data = response.json()
                    except ValueError as exc:
                        raise ApiError(f"ответ {path} не является JSON") from exc
                    if not isinstance(data, dict):
                        raise ApiError(f"неожиданная структура ответа {path}: ожидался объект")
                    return data
                if status in (401, 403):
                    raise AccessDenied(
                        f"HTTP {status} на {path}: для этого метода нужна авторизация (HH_API_TOKEN) "
                        "либо доступ ограничен (например, CAPTCHA). Ограничение не обходится; "
                        "используйте импорт файла: python -m src.pipeline import --file ..."
                    )
                if status == 404:
                    raise ApiError(f"HTTP 404 на {path}: ресурс не найден")
                if status in RETRY_STATUSES:
                    last_problem = f"HTTP {status}"
                else:
                    raise ApiError(f"HTTP {status} на {path}")
            if attempt < attempts - 1:
                wait = self._wait_time(attempt, response)
                log.warning("Временная ошибка (%s) на %s, повтор %d/%d через %.1f с",
                            last_problem, path, attempt + 1, attempts - 1, wait)
                self._sleep(wait)
        raise ApiError(f"не удалось выполнить {path} после {attempts} попыток ({last_problem})")

    def _polite_pause(self) -> None:
        if self.cfg.delay_sec > 0:
            self._sleep(self.cfg.delay_sec)

    # ---------- методы API ----------

    def search_page(self, query: str, area: str, page: int) -> dict:
        params: dict[str, Any] = {"text": query, "area": area, "page": page, "per_page": self.cfg.per_page}
        if self.cfg.period_days:
            params["period"] = self.cfg.period_days
        data = self._get("/vacancies", params)
        if not isinstance(data.get("items"), list):
            raise ApiError("неожиданная структура ответа поиска: нет списка items")
        return data

    def iter_search(self, query: str, area: str, limit: int, found: dict[str, int] | None = None) -> Iterator[dict]:
        """Элементы выдачи по одному запросу и региону (до limit штук)."""
        yielded = 0
        page = 0
        while yielded < limit and page < self.cfg.max_pages:
            if (page + 1) * self.cfg.per_page > HH_MAX_DEPTH:
                log.info("Достигнута глубина поиска hh.ru (%d результатов)", HH_MAX_DEPTH)
                return
            data = self.search_page(query, area, page)
            if found is not None and page == 0:
                found[f"{query} / area={area}"] = int(data.get("found") or 0)
            for item in data["items"]:
                if isinstance(item, dict):
                    yield item
                    yielded += 1
                    if yielded >= limit:
                        return
            pages = int(data.get("pages") or 0)
            page += 1
            if page >= pages or not data["items"]:
                return
            self._polite_pause()

    def get_vacancy(self, vacancy_id: str) -> dict:
        return self._get(f"/vacancies/{vacancy_id}")

    # ---------- сценарий сбора ----------

    def collect(self) -> CollectResult:
        """Полный сбор: поиск по запросам×регионам, затем (опционально) детали каждой вакансии.

        Не бросает исключений наружу из-за сбоев источника: всё, что собрано к моменту ошибки,
        возвращается вместе со списком ошибок и причиной остановки.
        """
        cfg = self.cfg
        result = CollectResult()
        listed: dict[str, dict] = {}

        try:
            for area in cfg.areas:
                for query in cfg.queries:
                    remaining = cfg.max_vacancies - len(listed)
                    if remaining <= 0:
                        break
                    log.info("Поиск: «%s», регион %s", query, area)
                    for item in self.iter_search(query, area, remaining, result.found_by_query):
                        vid = str(item.get("id", "")).strip()
                        if vid and vid not in listed:
                            listed[vid] = item
                        if len(listed) >= cfg.max_vacancies:
                            break
                    self._polite_pause()
        except AccessDenied as exc:
            result.errors.append(str(exc))
            result.stopped_reason = "access_denied"
        except RequestBudgetExceeded as exc:
            result.errors.append(str(exc))
            result.stopped_reason = "request_budget"
        except ApiError as exc:
            result.errors.append(f"поиск прерван: {exc}")
            result.stopped_reason = "search_error"

        log.info("Найдено уникальных вакансий в выдаче: %d", len(listed))
        details_enabled = cfg.fetch_details
        for vid, item in listed.items():
            merged = dict(item)
            if details_enabled:
                try:
                    detail = self.get_vacancy(vid)
                    merged.update(detail)
                    result.details_fetched += 1
                    self._polite_pause()
                except (AccessDenied, RequestBudgetExceeded) as exc:
                    result.errors.append(f"детали отключены: {exc}")
                    result.stopped_reason = result.stopped_reason or (
                        "access_denied" if isinstance(exc, AccessDenied) else "request_budget")
                    details_enabled = False  # остальные вакансии сохраняем из выдачи
                except ApiError as exc:
                    result.errors.append(f"вакансия {vid}: {exc}")
            result.items.append(merged)

        result.requests_made = self.requests_made
        return result
