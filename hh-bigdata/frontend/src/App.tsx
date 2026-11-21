import { useEffect, useState } from 'react'
import { Activity, ArrowUpRight, BriefcaseBusiness, ChartNoAxesCombined, Compass, Database, GraduationCap, MapPinned, Search, Sparkles, Wallet } from 'lucide-react'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

type ApiState = 'checking' | 'online' | 'offline'

const navigation = [
  { label: 'Обзор', icon: ChartNoAxesCombined, active: true },
  { label: 'Зарплаты', icon: Wallet },
  { label: 'Навыки', icon: Sparkles },
  { label: 'География', icon: MapPinned },
  { label: 'Что выучить', icon: GraduationCap },
  { label: 'Прогноз', icon: Activity },
  { label: 'Каталог вакансий', icon: BriefcaseBusiness },
  { label: 'Качество данных', icon: Database },
]

export default function App() {
  const [apiState, setApiState] = useState<ApiState>('checking')

  useEffect(() => {
    const controller = new AbortController()
    fetch(`${API_BASE}/api/v1/health`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('API unavailable')
        return response.json()
      })
      .then(() => setApiState('online'))
      .catch(() => { if (!controller.signal.aborted) setApiState('offline') })
    return () => controller.abort()
  }, [])

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#top"><span className="brand-mark">hh</span><span>рынок<span className="brand-muted">.аналитика</span></span></a>
        <div className="nav-caption">РАБОЧЕЕ ПРОСТРАНСТВО</div>
        <nav>{navigation.map(({ label, icon: Icon, active }) => <a className={active ? 'nav-item active' : 'nav-item'} href="#" key={label}><Icon size={17}/><span>{label}</span></a>)}</nav>
        <div className="sidebar-bottom"><span className="status-dot"/><span>Учебный аналитический проект</span></div>
      </aside>

      <main className="main-content" id="top">
        <header className="topbar"><span>АНАЛИТИКА РЫНКА ТРУДА</span><div className="api-status"><i className={apiState === 'online' ? 'dot online' : 'dot'}/>{apiState === 'checking' ? 'Проверяем API' : apiState === 'online' ? 'API доступен' : 'API не подключён'}</div></header>
        <section className="hero">
          <div className="hero-copy"><span className="eyebrow"><span className="eyebrow-dot"/> ДАННЫЕ ИССЛЕДОВАНИЯ</span><h1>Понимай рынок.<br/><em>Выбирай будущее.</em></h1><p>Исследуйте спрос на специалистов, сравнивайте зарплаты и находите навыки, которые востребованы работодателями.</p><button className="primary-button" onClick={() => document.getElementById('features')?.scrollIntoView({ behavior: 'smooth' })}>Изучить возможности <ArrowUpRight size={17}/></button></div>
          <div className="hero-art"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="art-card"><span className="art-label">РЫНОК ВАКАНСИЙ</span><strong>Возможности<br/>начинаются<br/><b>с данных.</b></strong><div className="art-bars"><i/><i/><i/><i/><i/><i/><i/><i/><i/></div><span className="art-foot">HH.RU · DATA INSIGHTS</span></div><div className="floating-chip"><Sparkles size={16}/> Аналитика навыков</div></div>
        </section>

        <section className="section-heading" id="features"><div><span className="eyebrow">ИНСТРУМЕНТЫ</span><h2>Всё для изучения рынка труда</h2><p>Выберите направление исследования и переходите к деталям.</p></div><div className="section-count">01 — 08</div></section>
        <section className="feature-grid">{[
          { n: '01', title: 'Обзор рынка', desc: 'Ключевые показатели, динамика публикаций и структура спроса.', icon: ChartNoAxesCombined },
          { n: '02', title: 'Зарплаты', desc: 'Медианы, диапазоны и сравнение профессиональных направлений.', icon: Wallet },
          { n: '03', title: 'Навыки', desc: 'Востребованные технологии и изменения спроса.', icon: Sparkles },
          { n: '04', title: 'География', desc: 'Распределение вакансий и различия между регионами.', icon: Compass },
          { n: '05', title: 'Что выучить', desc: 'Сопоставление навыков и требований вакансий.', icon: GraduationCap },
          { n: '06', title: 'Прогноз', desc: 'Оценка динамики с проверкой точности модели.', icon: Activity },
          { n: '07', title: 'Каталог вакансий', desc: 'Поиск предложений, фильтры и переход к источнику.', icon: Search },
          { n: '08', title: 'Качество данных', desc: 'История загрузок, ошибки и состояние ETL.', icon: Database },
        ].map(({ n, title, desc, icon: Icon }) => <article className="feature-card" key={n}><div className="feature-top"><span>{n}</span><Icon size={21}/></div><h3>{title}</h3><p>{desc}</p><span className="feature-arrow"><ArrowUpRight size={18}/></span></article>)}</section>
        <footer className="footer"><span>HHRU MARKET INTELLIGENCE</span><span>Данные → Аналитика → Решения</span></footer>
      </main>
    </div>
  )
}
