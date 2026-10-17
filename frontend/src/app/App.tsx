import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUpRight, Check, ChevronDown, Compass, Heart, MapPin, Menu, PawPrint, Plus, Search, SlidersHorizontal, Sparkles, X } from 'lucide-react'
import { placeService } from '../services'
import { useDiscovery } from '../features/discovery/useDiscovery'
import { ContributionDialog } from '../features/community/ContributionDialog'
import { PlaceCard as FeaturePlaceCard } from '../features/place/PlaceCard'
import { PlaceDetail } from '../features/place/PlaceDetail'
import type { ContributionKind, Facility, Place, PlaceCategory } from '../types/place'

const categories: { id: PlaceCategory | ''; label: string; icon: string }[] = [
  { id: '', label: 'All places', icon: '✳' }, { id: 'dog_park', label: 'Dog parks', icon: '◉' }, { id: 'beach', label: 'Beaches', icon: '⌁' }, { id: 'walk', label: 'Walks', icon: '↗' }, { id: 'hiking_area', label: 'Hiking', icon: '△' }, { id: 'cafe', label: 'Cafés', icon: '⌂' },
]
const areas = ['Brisbane City', 'Brisbane North', 'Gold Coast', 'Moreton Bay', 'Sunshine Coast']
const facilities: Facility[] = ['Fenced', 'Off-leash area', 'Drinking water', 'Shade', 'Picnic tables', 'Accessible paths']

export default function App() {
  const { query, places, loading, error, updateQuery, refresh } = useDiscovery(placeService)
  const [favourites, setFavourites] = useState<string[]>([])
  const [selected, setSelected] = useState<Place | null>(null)
  const [showFilters, setShowFilters] = useState(false)
  const [signedIn, setSignedIn] = useState(false)
  const [dialog, setDialog] = useState<'contribute' | 'report' | null>(null)
  const [kind, setKind] = useState<ContributionKind>('review')
  const [rating, setRating] = useState(5)
  const [message, setMessage] = useState('')
  const [writeError, setWriteError] = useState('')
  const [reportTargetType, setReportTargetType] = useState<'place' | 'contribution'>('place')
  const [reportTargetId, setReportTargetId] = useState('')
  const [notice, setNotice] = useState('')
  const [mobileMenu, setMobileMenu] = useState(false)
  const [view, setView] = useState<'explore' | 'favourites'>('explore')
  const dialogTriggerRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    void placeService.listFavourites().then(setFavourites).catch(() => setFavourites([]))
    const resolveRoute = async () => {
      const match = window.location.pathname.match(/^\/places\/([^/]+)\/?$/)
      setSelected(match ? await placeService.getPlace(match[1]) : null)
    }
    const onPopState = () => { void resolveRoute() }
    if (window.location.pathname.startsWith('/places/')) void resolveRoute()
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const visiblePlaces = useMemo(() => view === 'favourites' ? places.filter((place) => favourites.includes(place.id)) : places, [places, favourites, view])
  const openDialog = (type: 'contribute' | 'report', nextKind?: ContributionKind, targetType: 'place' | 'contribution' = 'place') => {
    const trigger = document.activeElement
    dialogTriggerRef.current = trigger instanceof HTMLElement ? trigger : null
    setWriteError('')
    if (nextKind) setKind(nextKind)
    if (type === 'report') { setReportTargetType(targetType); setReportTargetId(targetType === 'place' ? selected?.id ?? places[0]?.id ?? '' : '') }
    setDialog(type)
  }
  const closeDialog = () => {
    setDialog(null)
    setTimeout(() => dialogTriggerRef.current?.focus(), 0)
  }
  const toggleFacility = (facility: Facility) => updateQuery({ ...query, facilities: query.facilities?.includes(facility) ? query.facilities.filter((item) => item !== facility) : [...(query.facilities ?? []), facility] })
  const toggleFavourite = async (place: Place) => {
    if (!signedIn) { setNotice('Sign in to save favourites.'); return }
    try { await placeService.toggleFavourite(place.id); setFavourites(await placeService.listFavourites()) }
    catch { setNotice('We couldn’t update your saved places. Please try again.') }
  }
  const openPlace = async (place: Place) => { window.history.pushState({}, '', `/places/${place.id}`); setSelected(await placeService.getPlace(place.id)) }
  const closePlace = () => { window.history.pushState({}, '', '/'); setSelected(null) }
  const sharePlace = async (place: Place) => {
    const url = `${window.location.origin}/places/${place.id}`
    try { await navigator.clipboard.writeText(url); setNotice('Link copied — ready to share!') }
    catch { setNotice(url) }
  }
  const submit = async () => {
    if (!signedIn) { setNotice('Sign in to contribute to PawLocal.'); return }
    if (!message.trim()) return
    try {
      if (dialog === 'report') await placeService.submitReport({ targetType: reportTargetType, targetId: reportTargetId.trim(), reason: message.trim() })
      else await placeService.submitContribution({ kind, placeId: selected?.id, rating: kind === 'review' ? rating : undefined, body: message.trim() })
      setMessage(''); setWriteError(''); closeDialog()
      setNotice(dialog === 'report' ? 'Thanks. Your report has been sent for review.' : 'Thanks for helping the PawLocal community!')
    } catch {
      setWriteError('We couldn’t send that just now. Your note is still here; please try again.')
    }
  }

  return <div className="app-shell min-h-screen">
    <header className="topbar">
      <a className="brand" href="/" onClick={(event) => { event.preventDefault(); closePlace(); setView('explore') }}><span className="brand-mark"><PawPrint size={20} fill="currentColor" /></span><span>pawlocal<span className="brand-period">.</span></span></a>
      <nav className={mobileMenu ? 'main-nav is-open' : 'main-nav'} aria-label="Main navigation">
        <button className={view === 'explore' ? 'nav-link active' : 'nav-link'} onClick={() => { closePlace(); setView('explore') }}><Compass size={17} /> Explore</button>
        <button className={view === 'favourites' ? 'nav-link active' : 'nav-link'} onClick={() => { setView('favourites'); setMobileMenu(false) }}><Heart size={17} /> Saved places</button>
      </nav>
      <div className="header-actions"><span className="demo-label"><span /> Demo mode</span><button className="signin-button" onClick={() => { setSignedIn(!signedIn); setNotice(signedIn ? 'You are viewing as a visitor.' : 'You are signed in as a demo member.') }}>{signedIn ? 'Demo member' : 'Sign in'} <ChevronDown size={15} /></button></div>
      <button className="mobile-menu" aria-label="Open navigation" onClick={() => setMobileMenu(!mobileMenu)}>{mobileMenu ? <X /> : <Menu />}</button>
    </header>

    {selected ? <PlaceDetail place={selected} saved={favourites.includes(selected.id)} signedIn={signedIn} onBack={closePlace} onSave={() => void toggleFavourite(selected)} onShare={() => void sharePlace(selected)} onContribute={(nextKind) => openDialog('contribute', nextKind)} onReport={(targetType) => openDialog('report', undefined, targetType)} /> : <>
      <section className="hero"><div className="hero-inner"><div className="eyebrow"><span className="eyebrow-line" /> GOOD DAYS START HERE</div><h1>More wag.<br /><em>Less wondering.</em></h1><p className="hero-copy">Find the places your dog will love, from salty swims to shady strolls.</p><div className="hero-search"><Search size={20} /><label className="sr-only" htmlFor="place-search">Search places or areas</label><input id="place-search" value={query.q} onChange={(event) => updateQuery({ ...query, q: event.target.value })} placeholder="Try ‘off-leash near Brisbane’" /><span className="search-divider" /><MapPin size={18} /><label className="sr-only" htmlFor="hero-area">Select an area</label><select id="hero-area" value={query.area} onChange={(event) => updateQuery({ ...query, area: event.target.value })}><option value="">Everywhere</option>{areas.map((area) => <option key={area}>{area}</option>)}</select><button aria-label="Search places" onClick={() => void refresh()}><ArrowUpRight size={20} /></button></div><div className="hero-foot"><span><Sparkles size={15} /> Good spots, shared by locals</span><span className="hero-foot-note">South East Queensland <span>↘</span></span></div></div><div className="hero-stamp" aria-hidden="true"><span>MADE FOR</span><PawPrint size={25} /><span>THE OUTSIDE</span></div><div className="hero-doodle" aria-hidden="true">✳</div></section>

      <main className="content-wrap"><div className="section-heading"><div><div className="section-kicker">A LITTLE FRESH AIR</div><h2>{view === 'favourites' ? 'Your saved places' : 'Find your kind of outside'}<span className="heading-dot">.</span></h2></div><button className="contribute-top" onClick={() => openDialog('contribute', 'location_suggestion')}><Plus size={16} /> Add a place</button></div>
        <div className="category-row" role="group" aria-label="Filter by place category">{categories.map((item) => <button key={item.id || 'all'} className={query.category === item.id ? 'category-chip selected' : 'category-chip'} aria-pressed={query.category === item.id} onClick={() => updateQuery({ ...query, category: item.id })}><span className="category-icon">{item.icon}</span>{item.label}</button>)}<button className={showFilters ? 'filter-button on' : 'filter-button'} onClick={() => setShowFilters(!showFilters)}><SlidersHorizontal size={16} /> Filters{query.facilities?.length ? <span className="filter-count">{query.facilities.length}</span> : null}</button></div>
        {showFilters && <div className="filter-panel"><div><strong>Good to know</strong><span className="filter-hint">Only verified details appear here</span></div>{facilities.map((facility) => <label className="filter-option" key={facility}><input type="checkbox" checked={query.facilities?.includes(facility) ?? false} onChange={() => toggleFacility(facility)} />{facility}</label>)}</div>}
        <div className="result-line"><span>{loading ? 'Finding your places…' : `${visiblePlaces.length} lovely ${visiblePlaces.length === 1 ? 'place' : 'places'} to explore`}</span></div>
        {loading ? <div className="place-grid" aria-label="Loading places">{[1, 2, 3].map((number) => <div className="skeleton-card" key={number}><div /><span /><span /></div>)}</div> : error ? <div className="state-card"><div className="state-icon">↻</div><h3>We couldn't find the places</h3><p>Something interrupted the search. Give it another go.</p><button className="primary-button" onClick={() => void refresh()}>Try again</button></div> : visiblePlaces.length === 0 ? <div className="state-card"><div className="state-icon">⌕</div><h3>No spots on this search</h3><p>Try a different area or clear a filter to see more places.</p><button className="text-button" onClick={() => { setView('explore'); updateQuery({ q: '', area: '', category: '', facilities: [] }) }}>Clear all filters <ArrowUpRight size={15} /></button></div> : <div className="place-grid">{visiblePlaces.map((place, index) => <FeaturePlaceCard key={place.id} place={place} index={index} saved={favourites.includes(place.id)} onOpen={() => void openPlace(place)} onSave={() => void toggleFavourite(place)} />)}</div>}
        <div className="community-banner"><div className="banner-spark">✳</div><div><span className="section-kicker">BETTER, TOGETHER</span><h3>Know a spot we should know?</h3><p>Help another dog find their new favourite place.</p></div><button onClick={() => openDialog('contribute', 'location_suggestion')}>Share a place <ArrowUpRight size={16} /></button></div>
        <footer><a className="footer-brand" href="/" onClick={(event) => event.preventDefault()}><PawPrint size={15} /> pawlocal.</a><span>A little more outside, together.</span><span>South East Queensland, Australia</span></footer>
      </main>
    </>}
    <ContributionDialog dialog={dialog} signedIn={signedIn} setSignedIn={setSignedIn} kind={kind} setKind={setKind} rating={rating} setRating={setRating} message={message} setMessage={setMessage} writeError={writeError} reportTargetType={reportTargetType} reportTargetId={reportTargetId} setReportTargetType={setReportTargetType} setReportTargetId={setReportTargetId} onClose={closeDialog} onSubmit={() => void submit()} onNotice={setNotice} />
    {notice && <div className="toast" role="status"><Check size={17} />{notice}<button aria-label="Dismiss notification" onClick={() => setNotice('')}><X size={15} /></button></div>}
  </div>
}
