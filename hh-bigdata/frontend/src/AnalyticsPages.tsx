import { useEffect, useState } from 'react'

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\\/$/, '')

type SalaryRow = { name: string | null; vacancies: number; salary_share: number | null; comparable: number; median: number | null; mean: number | null; reliable: boolean }
type SalaryData = { basis: { currency: string; gross: boolean; label: string } | null; sample: { vacancies: number; comparable: number }; statistics: { median: number | null; mean: number | null; p25: number | null; p75: number | null; min: number | null; max: number | null }; by_region: SalaryRow[]; by_role: SalaryRow[] }
type SkillItem = { name: string; vacancies: number; share: number; salary: { with_skill_median: number; without_skill_median: number; difference: number; comparable_with: number; comparable_without: number } | null }
type SkillsData = { sample: { vacancies: number; skills: number }; salary_basis: { label: string; currency: string } | null; items: SkillItem[] }
type RegionItem = { region: string | null; vacancies: number; salary_disclosure_share: number | null; comparable_salary_count: number; median_salary: number | null; mean_salary: number | null; reliable_salary: boolean }
type RegionsData = { sample: { vacancies: number; regions: number }; salary_basis: { label: string } | null; items: RegionItem[] }

function useAnalytics<T>(endpoint: string, region: string) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    const controller = new AbortController()
    const params = new URLSearchParams()
    if (region) params.append('region', region)
    setLoading(true)
    fetch(`${API_BASE}${endpoint}${params.size ? `?${params}` : ''}`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) {
          const body = await response.json().catch(() => null)
          throw new Error(body?.detail?.message ?? body?.detail ?? 'Ошибка загрузки аналитики')
        }
        return response.json() as Promise<T>
      })
      .then(value => { setData(value); setError('') })
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [endpoint, region])
  return { data, error, loading }
}

const fmt = (value: number | null | undefined, currency = 'RUB') => value == null ? '—' : new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(value) + (currency === 'RUB' ? ' ₽' : ` ${currency}`)
const pct = (value: number | null | undefined) => value == null ? '—' : `${(value * 100).toFixed(1).replace('.', ',')}%`

function State({ loading, error, empty }: { loading: boolean; error: string; empty: boolean }) {
  if (loading) return <p className="loading-note">Загружаем аналитику…</p>
  if (error) return <p className="error-panel">{error}</p>
  if (empty) return <p className="empty-panel">Недостаточно данных. Сначала загрузите вакансии в базу проекта.</p>
  return null
}

function Metric({ label, value, note }: { label: string; value: string; note?: string }) {
  return <article className="kpi-card"><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</article>
}

function Bars({ rows, nameKey, valueKey }: { rows: Array<Record<string, unknown>>; nameKey: string; valueKey: string }) {
  const max = Math.max(1, ...rows.map(row => Number(row[valueKey] ?? 0)))
  return <div className="analytics-bars">{rows.map((row, index) => {
    const value = Number(row[valueKey] ?? 0)
    return <div className="analytics-bar-row" key={String(row[nameKey] ?? index)}><span>{String(row[nameKey] ?? 'Не указано')}</span><div className="analytics-track"><i style={{ width: `${Math.max(2, value / max * 100)}%` }}/></div><b>{new Intl.NumberFormat('ru-RU').format(value)}</b></div>
  })}</div>
}

export function SalaryPage({ region }: { region: string }) {
  const { data, error, loading } = useAnalytics<SalaryData>('/api/v1/analytics/salaries', region)
  return <section className="analytics-page"><header className="section-heading"><div><span className="eyebrow">ВОЗНАГРАЖДЕНИЕ</span><h2>Аналитика зарплат</h2><p>Сравниваем только зарплаты одной валюты и одного типа: gross или net.</p></div></header>
    <State loading={loading} error={error} empty={!loading && !error && (!data || !data.sample.comparable)}/>
    {data && <><div className="analytics-note">Основа сравнения: {data.basis?.label ?? 'нет сопоставимой основы'} · {data.sample.comparable} из {data.sample.vacancies} вакансий</div><div className="kpi-grid analytics-kpis"><Metric label="МЕДИАНА" value={fmt(data.statistics.median, data.basis?.currency)}/><Metric label="СРЕДНЯЯ" value={fmt(data.statistics.mean, data.basis?.currency)}/><Metric label="25-Й ПЕРЦЕНТИЛЬ" value={fmt(data.statistics.p25, data.basis?.currency)}/><Metric label="75-Й ПЕРЦЕНТИЛЬ" value={fmt(data.statistics.p75, data.basis?.currency)}/></div><div className="analytics-grid"><article className="analytics-panel"><h3>Медианная зарплата по регионам</h3><div className="analytics-table-wrap"><table><thead><tr><th>Регион</th><th>Вакансий</th><th>Сопоставимо</th><th>Медиана</th><th>Надёжность</th></tr></thead><tbody>{data.by_region.map(row => <tr key={row.name}><td>{row.name ?? 'Не указан'}</td><td>{row.vacancies}</td><td>{row.comparable}</td><td>{row.reliable ? fmt(row.median, data.basis?.currency) : 'Недостаточно данных'}</td><td>{row.reliable ? 'Надёжная' : 'Малая выборка'}</td></tr>)}</tbody></table></div></article><article className="analytics-panel"><h3>Количество вакансий по профессиям</h3><Bars rows={data.by_role.slice(0, 12) as unknown as Array<Record<string, unknown>>} nameKey="name" valueKey="vacancies"/></article></div></>}
  </section>
}

export function SkillsPage({ region }: { region: string }) {
  const { data, error, loading } = useAnalytics<SkillsData>('/api/v1/analytics/skills', region)
  return <section className="analytics-page"><header className="section-heading"><div><span className="eyebrow">ВОСТРЕБОВАННОСТЬ</span><h2>Навыки рынка</h2><p>Какие компетенции чаще всего встречаются в вакансиях.</p></div></header>
    <State loading={loading} error={error} empty={!loading && !error && (!data || !data.items.length)}/>
    {data && <><div className="analytics-note">В выборке {data.sample.vacancies} вакансий · найдено упоминаний навыков: {data.sample.skills}{data.salary_basis ? ` · ${data.salary_basis.label}` : ''}</div><div className="analytics-grid"><article className="analytics-panel"><h3>Топ навыков по спросу</h3><Bars rows={data.items as unknown as Array<Record<string, unknown>>} nameKey="name" valueKey="vacancies"/></article><article className="analytics-panel"><h3>Сравнение зарплат</h3><div className="analytics-table-wrap"><table><thead><tr><th>Навык</th><th>Доля вакансий</th><th>Медиана с навыком</th><th>Без навыка</th></tr></thead><tbody>{data.items.map(item => <tr key={item.name}><td>{item.name}</td><td>{pct(item.share)}</td><td>{item.salary ? fmt(item.salary.with_skill_median, data.salary_basis?.currency) : 'Мало данных'}</td><td>{item.salary ? fmt(item.salary.without_skill_median, data.salary_basis?.currency) : 'Мало данных'}</td></tr>)}</tbody></table></div><p className="analytics-footnote">Сравнение зарплат показывается только при достаточном количестве вакансий в обеих группах.</p></article></div></>}
  </section>
}

export function GeographyPage({ region }: { region: string }) {
  const { data, error, loading } = useAnalytics<RegionsData>('/api/v1/analytics/regions', region)
  return <section className="analytics-page"><header className="section-heading"><div><span className="eyebrow">РАСПРЕДЕЛЕНИЕ СПРОСА</span><h2>География вакансий</h2><p>Распределение объявлений и сопоставимых зарплат по регионам.</p></div></header>
    <State loading={loading} error={error} empty={!loading && !error && (!data || !data.items.length)}/>
    {data && <><div className="kpi-grid analytics-kpis"><Metric label="ВАКАНСИЙ" value={data.sample.vacancies.toLocaleString('ru-RU')}/><Metric label="РЕГИОНОВ" value={data.sample.regions.toLocaleString('ru-RU')}/><Metric label="ОСНОВА ЗАРПЛАТ" value={data.salary_basis?.label ?? 'Нет данных'}/></div><div className="analytics-grid"><article className="analytics-panel"><h3>Рейтинг регионов по числу вакансий</h3><Bars rows={data.items as unknown as Array<Record<string, unknown>>} nameKey="region" valueKey="vacancies"/></article><article className="analytics-panel"><h3>Зарплаты по регионам</h3><div className="analytics-table-wrap"><table><thead><tr><th>Регион</th><th>Вакансий</th><th>Зарплата</th><th>Доля с зарплатой</th></tr></thead><tbody>{data.items.map(item => <tr key={item.region}><td>{item.region ?? 'Не указан'}</td><td>{item.vacancies}</td><td>{item.reliable_salary ? fmt(item.median_salary, data.salary_basis?.currency) : 'Малая выборка'}</td><td>{pct(item.salary_disclosure_share)}</td></tr>)}</tbody></table></div></article></div></>}
  </section>
}
