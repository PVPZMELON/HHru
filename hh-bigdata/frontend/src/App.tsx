import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { SalaryPage, SkillsPage, GeographyPage } from './AnalyticsPages'
import {
  Activity, ArrowUpRight, BriefcaseBusiness, ChartNoAxesCombined,
  Database, GraduationCap, MapPinned, Search, Sparkles, Wallet,
} from 'lucide-react'

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')

type ApiState = 'checking' | 'online' | 'offline'
type Page = 'Обзор' | 'Каталог вакансий' | 'Зарплаты' | 'Навыки' | 'География' | 'Что выучить' | 'Прогноз' | 'Качество данных'

type Overview = {
  sample: { vacancies: number; employers: number }
  salary: { currency: string | null; gross: boolean | null; comparable_count: number; median: number | null; mean: number | null }
  salary_disclosure: { count: number; share: number }
  top_skill: { name: string | null; vacancies: number }
}

type Vacancy = {
  id: number
  title: string
  employer_name: string | null
  region_name: string | null
  role_name: string | null
  experience: string | null
  employment: string | null
  schedule: string | null
  salary: { from: number | null; to: number | null; currency: string | null; gross: boolean | null; kind: string | null }
  published_at: string | null
  url: string | null
  data_origin: string
  skills: string[]
}

type CatalogResponse = { items: Vacancy[]; total: number; page: number; page_size: number }
type Facets = { experience: string[]; employment: string[]; skills: string[] }
type FilterOptions = { regions: string[]; roles: string[]; origins: string[]; date_min: string | null; date_max: string | null; total: number }

const navigation: { label: Page; icon: typeof ChartNoAxesCombined }[] = [
  { label: 'Обзор', icon: ChartNoAxesCombined },
  { label: 'Зарплаты', icon: Wallet },
  { label: 'Навыки', icon: Sparkles },
  { label: 'География', icon: MapPinned },
  { label: 'Что выучить', icon: GraduationCap },
  { label: 'Прогноз', icon: Activity },
  { label: 'Каталог вакансий', icon: BriefcaseBusiness },
  { label: 'Качество данных', icon: Database },
]

const money = (value: number | null, currency: string | null) => {
  if (value === null) return 'Не указана'
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(value) + (currency === 'RUB' ? ' ₽' : currency ? ` ${currency}` : '')
}

function App() {
  const [apiState, setApiState] = useState<ApiState>('checking')
  const [page, setPage] = useState<Page>('Обзор')
  const [overview, setOverview] = useState<Overview | null>(null)
  const [overviewError, setOverviewError] = useState('')
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null)
  const [catalogError, setCatalogError] = useState('')
  const [facets, setFacets] = useState<Facets>({ experience: [], employment: [], skills: [] })
  const [filterOptions, setFilterOptions] = useState<FilterOptions>({ regions: [], roles: [], origins: [], date_min: null, date_max: null, total: 0 })
  const [query, setQuery] = useState('')
  const [region, setRegion] = useState('')
  const [experience, setExperience] = useState('')
  const [employment, setEmployment] = useState('')
  const [skill, setSkill] = useState('')
  const [sort, setSort] = useState('published_desc')
  const [pageNumber, setPageNumber] = useState(1)
  const [loadingCatalog, setLoadingCatalog] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    fetch(`${API_BASE}/api/v1/health`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error('API unavailable'); return response.json() })
      .then(() => setApiState('online'))
      .catch(() => { if (!controller.signal.aborted) setApiState('offline') })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (page !== 'Обзор') return
    const controller = new AbortController()
    fetch(`${API_BASE}/api/v1/overview`, { signal: controller.signal })
      .then(async (response) => { if (!response.ok) throw new Error('Не удалось загрузить обзор. Проверьте подключение к БД.'); return response.json() as Promise<Overview> })
      .then((data) => { setOverview(data); setOverviewError('') })
      .catch((error: Error) => { if (!controller.signal.aborted) setOverviewError(error.message) })
    return () => controller.abort()
  }, [page])

  useEffect(() => {
    if (page !== 'Каталог вакансий') return
    const controller = new AbortController()
    Promise.all([
      fetch(`${API_BASE}/api/v1/vacancies/facets`, { signal: controller.signal }),
      fetch(`${API_BASE}/api/v1/filters/options`, { signal: controller.signal }),
    ]).then(async ([facetResponse, optionResponse]) => {
      if (!facetResponse.ok || !optionResponse.ok) throw new Error('Не удалось загрузить справочники фильтров')
      const [facetData, optionData] = await Promise.all([facetResponse.json(), optionResponse.json()])
      setFacets(facetData)
      setFilterOptions(optionData)
    }).catch((error: Error) => { if (!controller.signal.aborted) setCatalogError(error.message) })
    return () => controller.abort()
  }, [page])

  useEffect(() => {
    if (page !== 'Каталог вакансий') return
    const controller = new AbortController()
    const params = new URLSearchParams({ page: String(pageNumber), page_size: '25', sort })
    if (query.trim()) params.set('q', query.trim())
    if (region) params.set('region', region)
    if (experience) params.set('experience', experience)
    if (employment) params.set('employment', employment)
    if (skill) params.append('skills', skill)
    setLoadingCatalog(true)
    fetch(`${API_BASE}/api/v1/vacancies?${params.toString()}`, { signal: controller.signal })
      .then(async (response) => { if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(body?.detail?.message ?? body?.detail ?? 'Не удалось загрузить вакансии') }; return response.json() as Promise<CatalogResponse> })
      .then((data) => { setCatalog(data); setCatalogError('') })
      .catch((error: Error) => { if (!controller.signal.aborted) setCatalogError(String(error.message)) })
      .finally(() => { if (!controller.signal.aborted) setLoadingCatalog(false) })
    return () => controller.abort()
  }, [page, pageNumber, query, region, experience, employment, skill, sort])

  const pageCount = useMemo(() => Math.max(1, Math.ceil((catalog?.total ?? 0) / 25)), [catalog?.total])

  const applySearch = (event: FormEvent) => {
    event.preventDefault()
    setPageNumber(1)
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#top"><span className="brand-mark">hh</span><span>рынок<span className="brand-muted">.аналитика</span></span></a>
        <div className="nav-caption">РАБОЧЕЕ ПРОСТРАНСТВО</div>
        <nav>{navigation.map(({ label, icon: Icon }) => <button className={page === label ? 'nav-item active' : 'nav-item'} key={label} onClick={() => setPage(label)}><Icon size={17}/><span>{label}</span></button>)}</nav>
        <div className="sidebar-bottom"><span className="status-dot"/><span>Учебный аналитический проект</span></div>
      </aside>

      <main className="main-content" id="top">
        <header className="topbar"><span>АНАЛИТИКА РЫНКА ТРУДА</span><div className="api-status"><i className={apiState === 'online' ? 'dot online' : 'dot'}/>{apiState === 'checking' ? 'Проверяем API' : apiState === 'online' ? 'API доступен' : 'API не подключён'}</div></header>

        {page === 'Обзор' && <>
          <section className="hero">
            <div className="hero-copy"><span className="eyebrow"><span className="eyebrow-dot"/> ДАННЫЕ ИССЛЕДОВАНИЯ</span><h1>Понимай рынок.<br/><em>Выбирай будущее.</em></h1><p>Исследуйте спрос на специалистов, сравнивайте зарплаты и находите навыки, которые востребованы работодателями.</p><button className="primary-button" onClick={() => setPage('Каталог вакансий')}>Открыть каталог <ArrowUpRight size={17}/></button></div>
            <div className="hero-art"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="art-card"><span className="art-label">РЫНОК ВАКАНСИЙ</span><strong>Возможности<br/>начинаются<br/><b>с данных.</b></strong><div className="art-bars"><i/><i/><i/><i/><i/><i/><i/><i/><i/></div><span className="art-foot">HH.RU · DATA INSIGHTS</span></div><div className="floating-chip"><Sparkles size={16}/> Аналитика навыков</div></div>
          </section>
          <section className="section-heading"><div><span className="eyebrow">ОБЗОР РЫНКА</span><h2>Ключевые показатели</h2><p>Показатели загружаются из базы данных проекта.</p></div><div className="section-count">LIVE DATA</div></section>
          {overviewError && <p className="error-panel">{overviewError}</p>}
          <section className="kpi-grid">
            <article className="kpi-card"><span>ВАКАНСИЙ В ВЫБОРКЕ</span><strong>{overview ? overview.sample.vacancies.toLocaleString('ru-RU') : '—'}</strong></article>
            <article className="kpi-card"><span>РАБОТОДАТЕЛЕЙ</span><strong>{overview ? overview.sample.employers.toLocaleString('ru-RU') : '—'}</strong></article>
            <article className="kpi-card"><span>МЕДИАННАЯ ЗАРПЛАТА</span><strong>{overview ? money(overview.salary.median, overview.salary.currency) : '—'}</strong><small>{overview?.salary.comparable_count ?? 0} сопоставимых вакансий</small></article>
            <article className="kpi-card"><span>ПОПУЛЯРНЫЙ НАВЫК</span><strong className="kpi-skill">{overview?.top_skill.name ?? '—'}</strong><small>{overview?.top_skill.vacancies ?? 0} вакансий</small></article>
          </section>
        </>}

        {page === 'Каталог вакансий' && <section className="catalog-page">
          <div className="section-heading catalog-heading"><div><span className="eyebrow">БАЗА ВАКАНСИЙ</span><h2>Каталог вакансий</h2><p>Поиск по реальным записям в базе проекта.</p></div><div className="section-count">{catalog?.total ?? 0} НАЙДЕНО</div></div>
          <form className="catalog-filters" onSubmit={applySearch}>
            <label className="search-field"><Search size={18}/><input value={query} onChange={(event) => { setQuery(event.target.value); setPageNumber(1) }} placeholder="Должность или ключевые слова"/></label>
            <select value={region} onChange={(event) => { setRegion(event.target.value); setPageNumber(1) }}><option value="">Все регионы</option>{filterOptions.regions.map((item) => <option key={item}>{item}</option>)}</select>
            <select value={experience} onChange={(event) => { setExperience(event.target.value); setPageNumber(1) }}><option value="">Любой опыт</option>{facets.experience.map((item) => <option key={item}>{item}</option>)}</select>
            <select value={employment} onChange={(event) => { setEmployment(event.target.value); setPageNumber(1) }}><option value="">Любая занятость</option>{facets.employment.map((item) => <option key={item}>{item}</option>)}</select>
            <select value={skill} onChange={(event) => { setSkill(event.target.value); setPageNumber(1) }}><option value="">Любой навык</option>{facets.skills.map((item) => <option key={item}>{item}</option>)}</select>
            <select value={sort} onChange={(event) => { setSort(event.target.value); setPageNumber(1) }}><option value="published_desc">Сначала новые</option><option value="published_asc">Сначала старые</option><option value="salary_desc">Сначала высокая зарплата</option><option value="salary_asc">Сначала низкая зарплата</option><option value="title_asc">По названию</option></select>
            <button className="primary-button filter-submit" type="submit">Найти вакансии <Search size={16}/></button>
          </form>
          {catalogError && <p className="error-panel">{catalogError}</p>}
          {loadingCatalog && <p className="loading-note">Загружаем вакансии…</p>}
          <div className="catalog-results">{catalog?.items.map((item) => <article className="vacancy-card" key={item.id}>
            <div className="vacancy-main"><div className="vacancy-meta"><span>{item.region_name ?? 'Регион не указан'}</span><span>{item.experience ?? 'Опыт не указан'}</span></div><h3>{item.title}</h3><p className="vacancy-employer">{item.employer_name ?? 'Работодатель не указан'}{item.employment ? ` · ${item.employment}` : ''}</p>
              <div className="skill-tags">{item.skills.slice(0, 6).map((name) => <span key={name}>{name}</span>)}</div></div>
            <div className="vacancy-side"><strong>{item.salary.from !== null || item.salary.to !== null ? `${money(item.salary.from, item.salary.currency)} — ${money(item.salary.to, item.salary.currency)}` : 'Зарплата не указана'}</strong>{item.published_at && <small>{new Date(item.published_at).toLocaleDateString('ru-RU')}</small>}{item.url && <a href={item.url} target="_blank" rel="noreferrer">Открыть на hh.ru <ArrowUpRight size={14}/></a>}</div>
          </article>)}</div>
          {catalog && !loadingCatalog && catalog.items.length === 0 && <p className="empty-panel">По заданным условиям вакансии не найдены.</p>}
          <div className="pagination"><span>Страница {pageNumber} из {pageCount}</span><div><button disabled={pageNumber <= 1} onClick={() => setPageNumber((n) => n - 1)}>Назад</button><button disabled={pageNumber >= pageCount} onClick={() => setPageNumber((n) => n + 1)}>Дальше</button></div></div>
        </section>}

        {page === 'Зарплаты' && <SalaryPage region={region}/>}
        {page === 'Навыки' && <SkillsPage region={region}/>}
        {page === 'География' && <GeographyPage region={region}/>}
        {!['Обзор', 'Каталог вакансий', 'Зарплаты', 'Навыки', 'География'].includes(page) && <section className="coming-soon"><span className="eyebrow">СЛЕДУЮЩИЙ ЭТАП</span><h2>{page}</h2><p>Этот раздел подключается к серверным данным. Пока можно исследовать реальные вакансии и базовые аналитические показатели.</p><button className="primary-button" onClick={() => setPage('Каталог вакансий')}>Перейти к вакансиям <ArrowUpRight size={17}/></button></section>}
        <footer className="footer"><span>HHRU MARKET INTELLIGENCE</span><span>Данные → Аналитика → Решения</span></footer>
      </main>
    </div>
  )
}

export default App
