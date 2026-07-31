import { useEffect, useMemo, useRef, useState } from 'react'
import type { LucideIcon } from 'lucide-react'
import type { AgentResponse } from '@/api/client'
import { getSessionState, sendMessage } from '@/api/client'
import * as maplibregl from 'maplibre-gl'
import type { FeatureCollection, Geometry, Position } from 'geojson'
import 'maplibre-gl/dist/maplibre-gl.css'
import ChatBar from '@/components/dashboard/ChatBar'
import {
  ArrowUpRight,
  Building2,
  CalendarDays,
  ChevronRight,
  CloudRain,
  CloudSun,
  Compass,
  Footprints,
  Globe2,
  MapPin,
  Menu,
  Plane,
  Search,
  SlidersHorizontal,
  Sparkles,
  Star,
  TrainFront,
  Utensils,
  X,
} from 'lucide-react'
import {
  featuredDestinations,
  flights,
  hotels,
  restaurants,
  topDeals,
  weatherForecast,
} from '@/data/mock'
import type { Flight, Hotel, Restaurant, WeatherDay } from '@/data/mock'

type View = 'wonder' | 'flights' | 'trains' | 'hotels' | 'restaurants' | 'weather' | 'map'

interface NavItem {
  id: View
  label: string
  icon: LucideIcon
  comingSoon?: boolean
}

const navItems: NavItem[] = [
  { id: 'wonder', label: 'Wonder', icon: Star },
  { id: 'flights', label: 'Flights', icon: Plane },
  { id: 'trains', label: 'Trains', icon: TrainFront, comingSoon: true },
  { id: 'hotels', label: 'Hotels', icon: Building2 },
  { id: 'restaurants', label: 'Restaurants', icon: Utensils },
  { id: 'weather', label: 'Weather', icon: CloudSun },
  { id: 'map', label: 'Map', icon: MapPin },
]

const currency = new Intl.NumberFormat('en-IN')

type TripState = AgentResponse['trip_state']
type DataRecord = Record<string, unknown>

function isRecord(value: unknown): value is DataRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function textValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim() ? value : fallback
}

function numberValue(value: unknown, fallback = 0): number {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? number : fallback
}

// The backend stores each tool's latest payload under trip_state.live_data, keyed by
// domain. Shapes below mirror Duffel (flights), liteAPI (hotels), OpenWeatherMap
// (weather) and Foursquare (restaurants) exactly as app/tools/* return them.
function liveBucket(state: TripState, name: string): DataRecord | null {
  const live = state.live_data
  if (!isRecord(live)) return null
  const bucket = live[name]
  return isRecord(bucket) ? bucket : null
}

function bucketRows(bucket: DataRecord | null, key: string): DataRecord[] {
  const value = bucket?.[key]
  return Array.isArray(value) ? value.filter(isRecord) : []
}

const CURRENCY_SYMBOLS: Record<string, string> = { INR: '₹', USD: '$', EUR: '€', GBP: '£', JPY: '¥' }

function currencySymbol(code: unknown, fallback = '₹'): string {
  const raw = textValue(code).toUpperCase()
  if (!raw) return fallback
  return CURRENCY_SYMBOLS[raw] ?? `${raw} `
}

function clockTime(iso: unknown): string {
  const parsed = new Date(textValue(iso))
  return Number.isNaN(parsed.getTime())
    ? '--:--'
    : parsed.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

function durationLabel(minutes: number): string {
  if (!minutes) return 'See details'
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m`
}

// Duffel returns the carrier's display name but no IATA code, so initials stand in.
function initials(airline: string): string {
  const words = airline.replace(/[^A-Za-z ]/g, '').trim().split(/\s+/).filter(Boolean)
  if (!words.length) return 'AI'
  return (words.length > 1 ? words[0][0] + words[1][0] : words[0].slice(0, 2)).toUpperCase()
}

function liveFlights(state: TripState): Flight[] {
  const bucket = liveBucket(state, 'flights')
  return bucketRows(bucket, 'offers').map((offer, index): Flight => {
    const slices = Array.isArray(offer.slices) ? offer.slices.filter(isRecord) : []
    const outbound = slices[0]
    const segments = Array.isArray(outbound?.segments) ? outbound.segments.filter(isRecord) : []
    const first = segments[0]
    const last = segments[segments.length - 1]
    const airline = textValue(offer.airline, 'Airline')
    const from = textValue(outbound?.origin ?? first?.origin ?? bucket?.origin, '—')
    const to = textValue(outbound?.destination ?? last?.destination ?? bucket?.destination, '—')
    const stops = numberValue(offer.total_stops ?? outbound?.stops)
    return {
      id: textValue(offer.offer_id, `offer-${index}`),
      airline,
      airlineCode: initials(airline),
      from,
      fromCity: from,
      to,
      toCity: to,
      departTime: clockTime(first?.departing_at),
      arriveTime: clockTime(last?.arriving_at),
      duration: durationLabel(numberValue(offer.total_duration_minutes ?? outbound?.duration_minutes)),
      stops,
      stopCity: stops > 0 ? textValue(first?.destination) || undefined : undefined,
      price: Math.round(numberValue(offer.price_amount)),
      currency: currencySymbol(offer.price_currency),
      cabin: textValue(outbound?.fare_brand, 'Economy'),
    }
  })
}

const HOTEL_FALLBACK_IMAGE = 'https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800&q=70'
const FOOD_FALLBACK_IMAGE = 'https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=800&q=70'

function liveHotels(state: TripState): Hotel[] {
  const bucket = liveBucket(state, 'hotels')
  const city = textValue(bucket?.city, 'Your destination')
  const bucketCurrency = currencySymbol(bucket?.currency)
  return bucketRows(bucket, 'hotels').map((row, index): Hotel => {
    const stars = numberValue(row.stars)
    return {
      id: textValue(row.hotel_id, `hotel-${index}`),
      name: textValue(row.name, 'Selected stay'),
      area: textValue(row.address, city),
      city,
      rating: numberValue(row.rating, stars),
      reviews: numberValue(row.review_count),
      pricePerNight: Math.round(numberValue(row.cheapest_price)),
      currency: row.currency ? currencySymbol(row.currency) : bucketCurrency,
      tags: stars ? [`${stars}-star`] : [],
      image: textValue(row.photo, HOTEL_FALLBACK_IMAGE),
    }
  })
}

function liveRestaurants(state: TripState): Restaurant[] {
  const bucket = liveBucket(state, 'restaurants')
  const near = textValue(bucket?.near, 'Nearby')
  return bucketRows(bucket, 'places').map((row, index): Restaurant => {
    const categories = Array.isArray(row.categories)
      ? row.categories.filter((item): item is string => typeof item === 'string')
      : []
    const meters = numberValue(row.distance_meters)
    return {
      id: textValue(row.place_id, `place-${index}`),
      name: textValue(row.name, 'Local favourite'),
      cuisine: categories[0] ?? 'Local',
      area: textValue(row.address, near),
      city: near,
      rating: 0,
      priceLevel: 2,
      distance: meters ? `${(meters / 1000).toFixed(1)} km` : '—',
      highlight: categories.slice(0, 3).join(' · ') || 'Recommended near your stay',
      image: FOOD_FALLBACK_IMAGE,
    }
  })
}

function weekdayLabel(value: unknown, index: number): string {
  const parsed = new Date(textValue(value))
  return Number.isNaN(parsed.getTime())
    ? `Day ${index + 1}`
    : parsed.toLocaleDateString('en-US', { weekday: 'short' })
}

function liveWeather(state: TripState): { city: string; current: DataRecord | null; days: WeatherDay[]; note: string } {
  const bucket = liveBucket(state, 'weather')
  const days = bucketRows(bucket, 'daily').map((row, index): WeatherDay => {
    const conditions = textValue(row.conditions).toLowerCase()
    const condition = /rain|drizzle|storm|snow/.test(conditions)
      ? 'rain'
      : /clear|sun/.test(conditions)
        ? 'sun'
        : 'cloud'
    return {
      day: weekdayLabel(row.date, index),
      condition,
      high: Math.round(numberValue(row.temp_max_c)),
      low: Math.round(numberValue(row.temp_min_c)),
      pop: Math.round(numberValue(row.precipitation_chance_pct)),
    } as WeatherDay
  })
  return {
    city: textValue(bucket?.city),
    current: isRecord(bucket?.current) ? bucket.current : null,
    days,
    note: textValue(bucket?.note),
  }
}

interface TripSummary {
  origin: string | null
  destination: string | null
  country: string | null
  dateLabel: string | null
  center: [number, number] | null
}

function shortDate(value: unknown): string {
  const parsed = new Date(textValue(value))
  return Number.isNaN(parsed.getTime())
    ? ''
    : parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function tripSummary(state: TripState): TripSummary {
  const destinations = (Array.isArray(state.destinations) ? state.destinations : []).filter(isRecord)
  const primary = destinations[0]
  const start = shortDate(state.start_date)
  const end = shortDate(state.end_date)
  const lat = numberValue(primary?.latitude, NaN)
  const lng = numberValue(primary?.longitude, NaN)
  return {
    origin: textValue(state.origin) || null,
    destination: textValue(primary?.city) || null,
    country: textValue(primary?.country) || null,
    dateLabel: start ? (end ? `${start} – ${end}` : start) : null,
    center: Number.isFinite(lat) && Number.isFinite(lng) ? [lng, lat] : null,
  }
}

function SectionHeading({ eyebrow, title, action }: { eyebrow?: string; title: string; action?: string }) {
  return (
    <div className="flex items-end justify-between gap-4">
      <div>
        {eyebrow && <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.22em] text-[#7b8792]">{eyebrow}</p>}
        <h2 className="font-display text-4xl leading-none tracking-[-0.04em] text-[#202a36] md:text-5xl">{title}</h2>
      </div>
      {action && <button className="hidden items-center gap-1 text-sm font-semibold text-[#2a6074] transition hover:text-[#173c4d] sm:flex">{action}<ArrowUpRight size={15} /></button>}
    </div>
  )
}

// Demo fixtures are Tokyo-only. Showing them under a real trip to somewhere else is
// what made the dashboard look like it never updated, so they are only used before a
// destination exists — after that, an honest empty state replaces them.
function NoLiveData({ label, destination }: { label: string; destination: string }) {
  return (
    <div className="rounded-[30px] border border-dashed border-[#c8d5da] bg-white/70 p-10 text-center">
      <Sparkles className="mx-auto text-[#2a6074]" size={30} />
      <h3 className="mt-4 font-display text-3xl text-[#202a36]">No {label} for {destination} yet</h3>
      <p className="mx-auto mt-3 max-w-sm text-sm leading-relaxed text-[#71808a]">
        TripAI hasn't looked these up for this trip. Ask for them in the chat below and they'll appear here.
      </p>
    </div>
  )
}

function Sidebar({ active, onChange, onLogoClick }: { active: View; onChange: (view: View) => void; onLogoClick: () => void }) {
  return (
    <aside className="fixed inset-y-5 left-5 z-30 hidden w-[238px] flex-col rounded-[38px] bg-white px-5 py-8 shadow-[0_18px_55px_rgba(32,42,54,0.08)] lg:flex">
      <button onClick={onLogoClick} className="mb-14 px-5 text-left font-display text-[42px] leading-none tracking-[-0.06em] text-[#202a36] transition hover:text-[#2a6074]">tripai</button>
      <nav className="space-y-2" aria-label="TripAI sections">
        {navItems.map((item) => {
          const Icon = item.icon
          const selected = item.id === active
          return (
            <button key={item.id} onClick={() => onChange(item.id)} className={`group flex w-full items-center gap-4 rounded-2xl px-5 py-3.5 text-left transition ${selected ? 'bg-[#e9f2f5] text-[#2a6074]' : 'text-[#405260] hover:bg-[#f4f7f8]'} ${item.comingSoon && !selected ? 'opacity-70' : ''}`} aria-current={selected ? 'page' : undefined}>
              <Icon size={24} strokeWidth={1.8} />
              <span className="text-[15px] font-semibold">{item.label}</span>
              {item.comingSoon && <span className="ml-auto text-[8px] font-bold uppercase tracking-[0.14em]">Soon</span>}
            </button>
          )
        })}
      </nav>
      <div className="mt-auto rounded-3xl bg-[#f4f7f8] p-4">
        <div className="mb-3 flex items-center gap-2 text-[#2a6074]"><Sparkles size={16} /><span className="text-[11px] font-bold uppercase tracking-[0.14em]">TripAI guide</span></div>
        <p className="text-sm leading-relaxed text-[#64717b]">Your next great day is closer than you think.</p>
      </div>
    </aside>
  )
}

function MobileNav({ active, onChange }: { active: View; onChange: (view: View) => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mb-6 lg:hidden">
      <div className="flex items-center justify-between rounded-3xl bg-white px-5 py-4 shadow-[0_12px_35px_rgba(32,42,54,0.07)]">
        <span className="font-display text-3xl tracking-[-0.05em] text-[#202a36]">tripai</span>
        <button onClick={() => setOpen(!open)} className="rounded-full bg-[#e9f2f5] p-2 text-[#2a6074]" aria-label="Toggle navigation">{open ? <X size={20} /> : <Menu size={20} />}</button>
      </div>
      {open && <div className="mt-2 grid grid-cols-2 gap-2 rounded-3xl bg-white p-3 shadow-[0_12px_35px_rgba(32,42,54,0.07)]">{navItems.map((item) => { const Icon = item.icon; return <button key={item.id} onClick={() => { onChange(item.id); setOpen(false) }} className={`flex items-center gap-2 rounded-2xl px-3 py-3 text-left text-sm font-semibold ${active === item.id ? 'bg-[#e9f2f5] text-[#2a6074]' : 'text-[#405260]'}`}><Icon size={17} />{item.label}</button> })}</div>}
    </div>
  )
}

function SearchBar({ value, onChange, placeholder = 'Search destinations, stays, food...' }: { value: string; onChange: (value: string) => void; placeholder?: string }) {
  return <label className="flex h-14 items-center gap-3 rounded-2xl border border-[#dce4e7] bg-white px-5 shadow-[0_10px_25px_rgba(32,42,54,0.05)]"><Search size={20} className="text-[#2a6074]" /><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="w-full bg-transparent text-base text-[#202a36] outline-none placeholder:text-[#98a3aa]" /></label>
}

function WonderView({ onChange, agentMessage, tripState }: { onChange: (view: View) => void; agentMessage?: string; tripState: TripState }) {
  const [query, setQuery] = useState('')
  const trip = tripSummary(tripState)
  const destination = useMemo(() => featuredDestinations.find((item) => item.name.toLowerCase().includes(query.toLowerCase())) ?? featuredDestinations[0], [query])
  return (
    <div className="space-y-10">
      <div className="mx-auto max-w-3xl text-center"><p className="mb-3 text-[11px] font-bold uppercase tracking-[0.25em] text-[#8a959d]">Your travel companion</p><h1 className="font-display text-5xl leading-[0.9] tracking-[-0.06em] text-[#202a36] md:text-7xl">Explore your next adventure</h1></div>
      {agentMessage && (
        <div className="rounded-[26px] bg-[#e9f2f5] border border-[#c8dde4] p-6">
          <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.2em] text-[#2a6074]">TripAI says</p>
          <p className="text-sm leading-relaxed text-[#202a36] whitespace-pre-wrap">{agentMessage}</p>
        </div>
      )}
      <SearchBar value={query} onChange={setQuery} />
      <div className="grid gap-8 xl:grid-cols-[1fr_1fr]">
        <section><SectionHeading title="Featured destination" action="View all" /><div className="mt-5 grid min-h-[430px] grid-cols-[1.1fr_0.9fr] overflow-hidden rounded-[30px] bg-white shadow-[0_16px_45px_rgba(32,42,54,0.08)]"><div className="relative min-h-[330px]"><img src={destination.image} alt={destination.name} className="absolute inset-0 h-full w-full object-cover" /><div className="absolute inset-0 bg-gradient-to-t from-[#173d4c]/75 via-transparent to-transparent" /><div className="absolute bottom-7 left-7 text-white"><p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em]">{destination.country}</p><h3 className="font-display text-4xl">{destination.name}</h3></div></div><div className="flex flex-col justify-between p-7"><div><Compass className="mb-8 text-[#2a6074]" size={34} strokeWidth={1.5} /><h3 className="font-display text-3xl leading-none text-[#202a36]">A trip made for your kind of curious.</h3><p className="mt-4 text-sm leading-relaxed text-[#71808a]">{destination.blurb}. Discover a slower, more memorable way to see the world.</p></div><button onClick={() => onChange('flights')} className="flex w-fit items-center gap-2 rounded-full bg-[#2a6074] px-5 py-3 text-sm font-bold text-white transition hover:bg-[#173c4d]">Start exploring <ChevronRight size={16} /></button></div></div></section>
        <section><SectionHeading title="Top deals" action="View all" /><div className="mt-5 space-y-4">{topDeals.map((deal) => <article key={deal.id} className="group flex min-h-[126px] overflow-hidden rounded-[26px] bg-white shadow-[0_12px_30px_rgba(32,42,54,0.06)]"><img src={deal.image} alt="" className="w-[38%] object-cover transition duration-700 group-hover:scale-105" /><div className="flex flex-1 items-center justify-between gap-4 p-5"><div><p className="mb-1 text-[11px] font-bold uppercase tracking-[0.16em] text-[#849098]">{deal.discount}</p><h3 className="font-display text-2xl leading-none text-[#202a36]">{deal.title}</h3><p className="mt-2 text-sm text-[#73818a]">{deal.subtitle}</p></div><ArrowUpRight className="shrink-0 text-[#2a6074]" /></div></article>)}</div></section>
      </div>
      <section><SectionHeading eyebrow="A first draft, just for you" title={trip.destination ? `Your ${trip.destination} moodboard` : 'Your trip moodboard'} /><div className="mt-5 grid gap-4 md:grid-cols-4">{['Old streets at blue hour', 'One perfect bowl of ramen', 'A quiet mountain trail', 'Coffee worth crossing town for'].map((item, index) => <div key={item} className="group relative min-h-[170px] overflow-hidden rounded-3xl bg-[#2a6074] p-5 text-white"><div className={`absolute inset-0 opacity-60 ${index % 2 ? 'bg-gradient-to-br from-[#799cad] to-[#173c4d]' : 'bg-gradient-to-br from-[#d1a76c] to-[#294c59]'}`} /><div className="relative flex h-full flex-col justify-end"><p className="text-lg font-semibold leading-tight">{item}</p><span className="mt-2 text-xs uppercase tracking-[0.15em] text-white/70">Day {index + 1}</span></div></div>)}</div></section>
    </div>
  )
}

function FlightsView({ tripState }: { tripState: TripState }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const flightVideo = 'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260328_091828_e240eb17-6edc-4129-ad9d-98678e3fd238.mp4'
  const live = liveFlights(tripState)
  const isLive = live.length > 0
  const trip = tripSummary(tripState)
  const routeFlights = isLive ? live : trip.destination ? [] : flights
  const cheapest = routeFlights.reduce((low, item) => (item.price > 0 && item.price < low ? item.price : low), Number.POSITIVE_INFINITY)
  const originChip = isLive ? routeFlights[0].from : trip.origin ?? 'New Delhi · DEL'
  const destinationChip = isLive ? routeFlights[0].to : trip.destination ?? 'Tokyo · HND'
  const fareChip = Number.isFinite(cheapest) ? `From ${routeFlights[0].currency}${currency.format(cheapest)}` : 'Ask TripAI'
  return (
    <div>
      <section className="relative min-h-[760px] overflow-hidden rounded-[34px] bg-gray-50 font-inter text-[#202A36]">
      <video src={flightVideo} autoPlay muted loop playsInline className="absolute inset-0 h-full w-full object-cover" />
      <div className="absolute inset-0 bg-gradient-to-b from-white/85 via-white/45 to-white/75" />
      <div className="relative flex min-h-[760px] flex-col">
        <nav className="mx-auto flex w-full max-w-7xl items-center justify-between px-6 py-6 md:px-8">
          <span className="text-2xl font-semibold tracking-[-0.04em]">tripai air</span>
          <div className="hidden items-center gap-8 text-sm text-gray-900 md:flex"><button className="transition-colors hover:text-gray-700">Start</button><button className="transition-colors hover:text-gray-700">Story</button><button className="transition-colors hover:text-gray-700">Rates</button><button className="transition-colors hover:text-gray-700">Benefits</button><button className="transition-colors hover:text-gray-700">FAQ</button></div>
          <button onClick={() => setMenuOpen(!menuOpen)} className="rounded-full bg-white/80 p-3 shadow-sm backdrop-blur md:hidden" aria-label="Toggle flight navigation">{menuOpen ? <X size={19} /> : <Menu size={19} />}</button>
          <button className="hidden rounded-full bg-[#202A36] px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[#1a2229] md:block">Explore flights</button>
        </nav>
        {menuOpen && <div className="absolute left-5 right-5 top-20 z-20 rounded-3xl bg-white/95 p-5 shadow-xl backdrop-blur md:hidden"><div className="grid gap-4 text-lg text-gray-900"><button className="text-left">Start</button><button className="text-left">Story</button><button className="text-left">Rates</button><button className="text-left">Benefits</button><button className="text-left">FAQ</button></div></div>}
        <main className="flex flex-1 items-center justify-center px-6 pb-20 pt-16 text-center md:-mt-24 md:px-10">
          <div className="max-w-4xl"><p className="mb-4 text-sm font-semibold tracking-wider text-gray-600">TRIPAI FLIGHTS</p><h1 className="font-inter text-6xl font-normal leading-none tracking-tighter text-gray-500 md:text-7xl lg:text-8xl">Premium.<br /><span className="-mt-3 block text-[#202A36]">Personal.</span></h1><p className="mx-auto mb-7 mt-7 max-w-2xl text-lg text-gray-600 md:text-xl">Every route should feel like it was chosen for the way you travel.</p><div className="flex flex-wrap justify-center gap-4"><button className="rounded-full bg-gray-300 px-5 py-2.5 font-medium text-gray-800 transition-colors hover:bg-gray-400">Discover flights</button><button className="rounded-full bg-[#202A36] px-5 py-2.5 font-medium text-white transition-colors hover:bg-[#1a2229]">Plan this route</button></div><div className="mx-auto mt-10 grid max-w-xl grid-cols-3 gap-2 rounded-3xl border border-white/60 bg-white/45 p-3 text-left shadow-sm backdrop-blur-md"><div className="rounded-2xl bg-white/70 p-3"><p className="text-[10px] uppercase tracking-wider text-gray-500">From</p><p className="mt-1 text-sm font-semibold">{originChip}</p></div><div className="rounded-2xl bg-white/70 p-3"><p className="text-[10px] uppercase tracking-wider text-gray-500">To</p><p className="mt-1 text-sm font-semibold">{destinationChip}</p></div><div className="rounded-2xl bg-white/70 p-3"><p className="text-[10px] uppercase tracking-wider text-gray-500">{isLive ? 'Cheapest fare' : 'Sample fare'}</p><p className="mt-1 text-sm font-semibold">{fareChip}</p></div></div></div>
        </main>
      </div>
      </section>
      <section className="mt-6 rounded-[30px] bg-white/70 p-5 shadow-[0_12px_30px_rgba(32,42,54,0.05)] backdrop-blur md:p-7">
        <div className="mb-5 flex items-end justify-between gap-4"><div><p className="mb-2 text-[11px] font-bold uppercase tracking-[0.22em] text-[#7b8792]">Live or demo availability</p><h2 className="font-display text-3xl text-[#202a36] md:text-4xl">More routes to explore</h2></div><span className="rounded-full bg-[#e9f2f5] px-3 py-1.5 text-xs font-semibold text-[#2a6074]">{isLive ? 'Live results' : routeFlights.length ? 'Demo results' : 'Nothing fetched yet'}</span></div>
        {!routeFlights.length && <NoLiveData label="flights" destination={trip.destination ?? 'this trip'} />}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{routeFlights.map((flight) => <article key={flight.id} className="rounded-2xl border border-[#e8eef0] bg-white p-4"><div className="flex items-start justify-between gap-3"><div><p className="font-semibold text-[#202a36]">{flight.airline}</p><p className="mt-1 text-xs text-[#849098]">{flight.from} → {flight.to} · {flight.stops === 0 ? 'Non-stop' : `${flight.stops} stop`}</p></div><span className="rounded-xl bg-[#e9f2f5] px-2.5 py-1 text-xs font-bold text-[#2a6074]">{flight.airlineCode}</span></div><div className="mt-4 flex items-end justify-between border-t border-[#eef2f3] pt-3"><p className="font-display text-2xl text-[#202a36]">{flight.currency}{currency.format(flight.price)}</p><p className="text-xs text-[#849098]">{flight.duration}</p></div></article>)}</div>
      </section>
    </div>
  )
}

const trainScenes = [
  { label: 'Golden hour', src: 'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260702_081127_0992a171-d3c6-4978-8213-0ec5df8b6d63.mp4' },
  { label: 'Still water', src: 'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260702_092026_dd05b805-ea0f-40b2-8c52-332b88502592.mp4' },
  { label: 'Deep woods', src: 'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260702_081042_df7202bf-bd80-4b2b-bbc6-1f09ba2870e9.mp4' },
  { label: 'Quiet dawn', src: 'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260702_080959_4cac5234-3573-464e-a5b7-76b94b8a7d61.mp4' },
]

function TrainsView() {
  const [activeVideo, setActiveVideo] = useState(0)
  const [isTransitioning, setIsTransitioning] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [email, setEmail] = useState('')
  useEffect(() => { if (!isTransitioning) return; const timer = window.setTimeout(() => setIsTransitioning(false), 1000); return () => window.clearTimeout(timer) }, [isTransitioning])
  const chooseScene = (index: number) => { if (index === activeVideo || isTransitioning) return; setActiveVideo(index); setIsTransitioning(true) }
  const contentTone = activeVideo === 2 ? 'text-[#182C41]' : 'text-white'
  return (
    <section className="relative min-h-[820px] overflow-hidden rounded-[34px] bg-[#0b1118] font-serifdisplay text-white">
      {trainScenes.map((item, index) => <video key={item.src} src={item.src} autoPlay muted loop playsInline className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-1000 ease-in-out ${activeVideo === index ? 'opacity-100' : 'opacity-0'}`} />)}
      <div className="absolute inset-0 z-[1] bg-[#0b1118]" />
      <div className="absolute inset-5 z-[2] overflow-hidden rounded-[58px] bg-black md:inset-8 md:rounded-[108px]">
        {trainScenes.map((item, index) => <video key={`window-${item.src}`} src={item.src} autoPlay muted loop playsInline className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-1000 ease-in-out ${activeVideo === index ? 'opacity-100' : 'opacity-0'}`} />)}
        <div className="absolute inset-0 bg-gradient-to-b from-black/20 via-transparent to-black/45" />
      </div>
      <img src="https://soft-zoom-63098134.figma.site/_assets/v11/0b4a435b2df2747593c43d7a1c9b4578f7d8d90c.png" alt="" aria-hidden="true" className="anim-slow-bob pointer-events-none absolute inset-0 z-[4] h-full w-full object-cover opacity-55" />
      <div className="absolute inset-5 z-[3] flex min-h-0 flex-col md:inset-8">
        <nav className="flex items-center justify-between px-5 py-6 md:px-8 md:py-7"><span className="text-2xl italic text-white">tripai rails</span><div className="hidden items-center gap-2 rounded-full liquid-glass p-1.5 md:flex"><button className="rounded-full px-4 py-2 text-sm text-white/90 transition hover:text-white">Rail stories</button><button className="rounded-full px-4 py-2 text-sm text-white/90 transition hover:text-white">Features</button><button className="rounded-full px-4 py-2 text-sm text-white/90 transition hover:text-white">Scenic routes</button><button className="rounded-full px-4 py-2 text-sm text-white/90 transition hover:text-white">Community</button><button className="rounded-full bg-white px-4 py-2 text-sm font-medium text-[#182C41]">Coming soon</button></div><button onClick={() => setMenuOpen(!menuOpen)} className="rounded-full liquid-glass p-3 text-white md:hidden" aria-label="Toggle train navigation">{menuOpen ? <X size={19} /> : <Menu size={19} />}</button></nav>
        {menuOpen && <div className="absolute inset-x-5 top-20 z-50 rounded-3xl bg-black/75 p-7 backdrop-blur-md md:hidden"><div className="grid gap-5 text-2xl text-white"><button className="text-left">Rail stories</button><button className="text-left">Features</button><button className="text-left">Scenic routes</button><button className="text-left">Community</button><button className="mt-5 rounded-full bg-white px-5 py-3 text-base font-semibold text-[#182C41]">Coming soon</button></div></div>}
        <main className={`flex flex-1 flex-col items-center px-5 pt-12 text-center transition-colors duration-700 md:px-8 md:pt-20 ${contentTone}`}>
          <div className="liquid-glass rounded-full px-4 py-2 text-xs tracking-wide">Rail journeys are being carefully mapped</div>
          <h1 className="mt-7 max-w-4xl text-5xl leading-[1.05] md:text-7xl lg:text-[5.5rem]">Quiet routes through<br />extraordinary places</h1>
          <p className="mt-6 max-w-xl font-sans text-sm leading-relaxed opacity-80 md:text-base">We are designing a slower way to travel: wide windows, quiet stations, and landscapes between the highlights. Train planning is coming soon.</p>
          <div className="liquid-glass mt-7 flex w-full max-w-sm items-center gap-2 rounded-full p-1.5 font-sans"><input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="Your best email" type="email" className="min-w-0 flex-1 bg-transparent px-4 py-2 text-sm text-white outline-none placeholder:text-white/60" /><button className="shrink-0 rounded-full bg-white px-4 py-2 text-xs font-semibold text-[#182C41]">Notify me</button></div>
          <div className="mt-10 flex flex-wrap justify-center gap-2 font-sans">{trainScenes.map((item, index) => <button key={item.label} onClick={() => chooseScene(index)} aria-pressed={activeVideo === index} className={`border-b px-3 py-2 text-xs transition-all ${activeVideo === index ? 'border-current opacity-100' : 'border-transparent opacity-50 hover:opacity-80'}`}><span className="mr-2 text-[10px]">0{index + 1}</span>{item.label}</button>)}</div>
        </main>
        <footer className="flex flex-wrap items-center justify-center gap-3 px-5 pb-7 pt-8 font-sans text-xs text-white/70 sm:gap-5 md:px-8 md:text-sm"><span>Train search coming soon</span><span className="hidden text-white/40 sm:inline">|</span><span>0 fake schedules</span><span className="hidden text-white/40 sm:inline">|</span><span>Scenic-first design</span><span className="hidden text-white/40 sm:inline">|</span><span>TripAI rail studio</span></footer>
      </div>
    </section>
  )
}

function HotelsView({ tripState }: { tripState: TripState }) {
  const live = liveHotels(tripState)
  const trip = tripSummary(tripState)
  const stayOptions = live.length ? live : trip.destination ? [] : hotels
  const place = live[0]?.city || trip.destination
  return <div className="space-y-8"><div className="relative min-h-[240px] overflow-hidden rounded-[32px] bg-[#173c4d] text-white"><video src="/videos/hotel.mp4" autoPlay muted loop playsInline className="absolute inset-0 h-full w-full object-cover opacity-55" /><div className="absolute inset-0 bg-gradient-to-r from-[#102d39]/90 via-[#102d39]/45 to-transparent" /><div className="relative max-w-xl p-8 md:p-12"><p className="mb-3 text-[11px] font-bold uppercase tracking-[0.22em] text-white/70">Stay somewhere memorable</p><h1 className="font-display text-5xl leading-[0.9] tracking-[-0.05em] md:text-6xl">A room with a point of view.</h1><p className="mt-4 max-w-md text-sm leading-relaxed text-white/75">Handpicked stays in the neighbourhoods that make a city feel like itself.</p></div></div><div className="flex flex-wrap items-center justify-between gap-3"><SectionHeading eyebrow={live.length ? 'Live availability' : 'Demo availability'} title={place ? `Stays in ${place}` : 'Stays for your trip'} /><button className="flex items-center gap-2 rounded-full bg-white px-4 py-2 text-sm font-semibold text-[#62727c]"><SlidersHorizontal size={15} /> Refine</button></div>{!stayOptions.length && <NoLiveData label="stays" destination={place ?? 'this trip'} />}<div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">{stayOptions.map((hotel) => <article key={hotel.id} className="group overflow-hidden rounded-[26px] bg-white shadow-[0_12px_30px_rgba(32,42,54,0.06)]"><div className="relative h-48 overflow-hidden"><img src={hotel.image} alt={hotel.name} className="h-full w-full object-cover transition duration-700 group-hover:scale-105" /><span className="absolute right-4 top-4 rounded-full bg-white/90 px-3 py-1 text-xs font-bold text-[#202a36]">{hotel.rating || '—'} <span className="text-amber-500">★</span></span></div><div className="p-5"><p className="text-[10px] font-bold uppercase tracking-[0.17em] text-[#849098]">{hotel.area} · {hotel.city}</p><h3 className="mt-2 font-display text-2xl text-[#202a36]">{hotel.name}</h3><div className="mt-4 flex flex-wrap gap-2">{hotel.tags.map((tag) => <span key={tag} className="rounded-full bg-[#f3f6f7] px-2.5 py-1 text-[11px] font-semibold text-[#61717a]">{tag}</span>)}</div><div className="mt-5 flex items-end justify-between border-t border-[#eef2f3] pt-4"><p><span className="font-display text-2xl text-[#202a36]">{hotel.currency}{currency.format(hotel.pricePerNight)}</span><span className="text-xs text-[#849098]"> / night</span></p><button className="rounded-full bg-[#2a6074] px-4 py-2 text-sm font-bold text-white">Explore</button></div></div></article>)}</div></div>
}

function RestaurantsView({ tripState }: { tripState: TripState }) {
  const live = liveRestaurants(tripState)
  const trip = tripSummary(tripState)
  const tables = live.length ? live : trip.destination ? [] : restaurants
  return <div className="space-y-8"><div className="relative min-h-[240px] overflow-hidden rounded-[32px] bg-[#202a36] text-white"><video src="/videos/restaurant.mp4" autoPlay muted loop playsInline className="absolute inset-0 h-full w-full object-cover opacity-50" /><div className="absolute inset-0 bg-gradient-to-r from-[#202a36]/95 via-[#202a36]/45 to-transparent" /><div className="relative max-w-xl p-8 md:p-12"><p className="mb-3 text-[11px] font-bold uppercase tracking-[0.22em] text-white/70">Eat like you belong</p><h1 className="font-display text-5xl leading-[0.9] tracking-[-0.05em] md:text-6xl">Follow the good smells.</h1><p className="mt-4 max-w-md text-sm leading-relaxed text-white/75">Local favourites, tiny counters, and the tables worth planning a day around.</p></div></div><SectionHeading eyebrow={live.length ? 'Live results' : 'Demo results'} title="Places worth the detour" action="View all" />{!tables.length && <NoLiveData label="restaurants" destination={trip.destination ?? 'this trip'} />}<div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">{tables.map((restaurant) => <article key={restaurant.id} className="overflow-hidden rounded-[26px] bg-white shadow-[0_12px_30px_rgba(32,42,54,0.06)]"><img src={restaurant.image} alt={restaurant.name} className="h-48 w-full object-cover" /><div className="p-5"><div className="flex items-center justify-between"><p className="text-[10px] font-bold uppercase tracking-[0.17em] text-[#849098]">{restaurant.cuisine} · {restaurant.area}</p>{restaurant.rating > 0 && <span className="text-sm font-bold text-amber-500">★ {restaurant.rating}</span>}</div><h3 className="mt-2 font-display text-2xl text-[#202a36]">{restaurant.name}</h3><p className="mt-2 text-sm leading-relaxed text-[#71808a]">{restaurant.highlight}</p><div className="mt-5 flex items-center justify-between border-t border-[#eef2f3] pt-4 text-sm"><span className="font-semibold text-[#62727c]">{'₹'.repeat(restaurant.priceLevel)} <span className="text-[#c3cdd1]">{'₹'.repeat(4 - restaurant.priceLevel)}</span></span><span className="flex items-center gap-1 text-[#62727c]"><MapPin size={14} />{restaurant.distance}</span></div></div></article>)}</div></div>
}

function WeatherView({ tripState }: { tripState: TripState }) {
  const weather = liveWeather(tripState)
  const trip = tripSummary(tripState)
  const hasLive = Boolean(weather.current) || weather.days.length > 0
  // Beyond the 5-day horizon the backend deliberately returns no daily rows. Filling
  // that gap with fixtures would be inventing a forecast the API refused to give.
  const forecast = weather.days.length ? weather.days : hasLive || trip.destination ? [] : weatherForecast
  const currentTemp = Math.round(numberValue(weather.current?.temp_c, 26))
  const currentDescription = textValue(weather.current?.conditions, 'Clear skies')
  const place = [weather.city || trip.destination, trip.country].filter(Boolean).join(', ')
  const eyebrow = [place || 'Your trip', trip.dateLabel].filter(Boolean).join(' · ')
  const driest = forecast.reduce((best, day) => (day.pop < best.pop ? day : best), forecast[0])
  const wettest = forecast.reduce((worst, day) => (day.pop > worst.pop ? day : worst), forecast[0])
  if (!hasLive && trip.destination) {
    return <div className="space-y-8"><SectionHeading eyebrow={eyebrow} title="Pack for the feeling" /><NoLiveData label="weather" destination={trip.destination} /></div>
  }
  return <div className="space-y-8"><SectionHeading eyebrow={eyebrow} title="Pack for the feeling" />{weather.note && <p className="rounded-3xl bg-[#fdf3e3] px-6 py-4 text-sm leading-relaxed text-[#7a5c2e]">{weather.note}</p>}<div className="grid gap-5 lg:grid-cols-[0.9fr_1.6fr]"><div className="rounded-[30px] bg-[#2a6074] p-8 text-white shadow-[0_14px_35px_rgba(42,96,116,0.2)]"><div className="flex items-start justify-between"><div><p className="text-sm text-white/70">Live trip weather</p><h3 className="mt-3 font-display text-7xl leading-none">{currentTemp}°</h3></div><CloudSun size={54} strokeWidth={1.3} /></div><div className="mt-14 flex items-center justify-between border-t border-white/20 pt-4 text-sm"><span className="capitalize">{currentDescription}</span><span>{weather.days.length ? 'Live forecast' : 'Demo forecast'}</span></div></div><div className="rounded-[30px] bg-white p-6 shadow-[0_12px_30px_rgba(32,42,54,0.06)]"><div className="mb-5 flex items-center justify-between"><h3 className="font-display text-2xl text-[#202a36]">Five-day outlook</h3><span className="text-xs font-semibold text-[#849098]">°C</span></div>{!forecast.length && <p className="rounded-2xl bg-[#f4f7f8] p-5 text-sm leading-relaxed text-[#71808a]">No daily forecast is available for these dates yet — only current conditions.</p>}<div className="grid grid-cols-5 gap-2">{forecast.map((day) => <div key={day.day} className="rounded-2xl bg-[#f4f7f8] p-3 text-center"><p className="text-xs font-bold text-[#62727c]">{day.day}</p><div className="my-5 flex justify-center text-[#2a6074]">{day.condition === 'rain' ? <CloudRain size={24} /> : day.condition === 'cloud' ? <CloudSun size={24} /> : <Sparkles size={23} />}</div><p className="font-semibold text-[#202a36]">{day.high}° <span className="font-normal text-[#9aa6ad]">{day.low}°</span></p><p className="mt-2 text-[10px] text-[#849098]">{day.pop}% rain</p></div>)}</div></div></div><div className="grid gap-4 md:grid-cols-3"><div className="rounded-3xl bg-white p-5"><CalendarDays className="text-[#2a6074]" size={20} /><p className="mt-6 text-sm text-[#849098]">Best day to be outside</p><p className="mt-1 font-semibold text-[#202a36]">{driest ? `${driest.day} · ${driest.high}°, ${driest.pop}% rain` : 'Ask TripAI'}</p></div><div className="rounded-3xl bg-white p-5"><Footprints className="text-[#2a6074]" size={20} /><p className="mt-6 text-sm text-[#849098]">Bring along</p><p className="mt-1 font-semibold text-[#202a36]">A light jacket + good shoes</p></div><div className="rounded-3xl bg-white p-5"><CloudRain className="text-[#2a6074]" size={20} /><p className="mt-6 text-sm text-[#849098]">Rain watch</p><p className="mt-1 font-semibold text-[#202a36]">{wettest && wettest.pop > 0 ? `${wettest.day} · ${wettest.pop}% chance` : 'Nothing in the forecast'}</p></div></div></div>
}

type RouteCollection = FeatureCollection<Geometry>

function asRouteCollection(value: unknown): RouteCollection | null {
  if (!isRecord(value)) return null
  if (value.type === 'FeatureCollection' && Array.isArray(value.features)) return value as unknown as RouteCollection
  if (isRecord(value.geojson)) return asRouteCollection(value.geojson)
  return null
}

function visitPositions(value: unknown, visit: (position: Position) => void) {
  if (!Array.isArray(value)) return
  if (value.length >= 2 && typeof value[0] === 'number' && typeof value[1] === 'number') {
    visit(value as Position)
    return
  }
  value.forEach((child) => visitPositions(child, visit))
}

function MapCanvas({ route, center }: { route: RouteCollection; center: [number, number] | null }) {
  const containerRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!containerRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: 'https://demotiles.maplibre.org/style.json',
      center: center ?? [78.9629, 20.5937],
      zoom: 5,
      attributionControl: { compact: true },
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'top-right')
    map.on('load', () => {
      map.addSource('tripai-route', { type: 'geojson', data: route })
      map.addLayer({ id: 'tripai-route-line', type: 'line', source: 'tripai-route', paint: { 'line-color': '#2a6074', 'line-width': 5, 'line-opacity': 0.9 } })
      const bounds = new maplibregl.LngLatBounds()
      route.features.forEach((feature) => {
        const geometry = feature.geometry
        if (geometry && 'coordinates' in geometry) visitPositions(geometry.coordinates, (position) => bounds.extend(position as [number, number]))
      })
      if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 80, duration: 0 })
    })
    return () => map.remove()
  }, [route, center])
  return <div ref={containerRef} className="absolute inset-0" aria-label="Trip route map" />
}

function MapView({ tripState, sessionId }: { tripState: TripState; sessionId: string | null }) {
  const [route, setRoute] = useState<RouteCollection | null>(() => asRouteCollection(tripState.route))
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    const directRoute = asRouteCollection(tripState.route)
    if (directRoute) { setRoute(directRoute); return }
    if (!sessionId) return
    let cancelled = false
    setLoading(true)
    getSessionState(sessionId).then((response) => {
      if (!cancelled) setRoute(asRouteCollection(response.trip_state.route))
    }).catch(() => undefined).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [sessionId, tripState.route])
  return <div className="space-y-8"><SectionHeading eyebrow="Your trip at a glance" title="Move through the story" /><div className="relative min-h-[560px] overflow-hidden rounded-[32px] bg-[#dce7e7] shadow-[0_14px_35px_rgba(32,42,54,0.08)]">{route ? <MapCanvas route={route} center={tripSummary(tripState).center} /> :<div className="absolute inset-0 grid place-items-center bg-[radial-gradient(circle_at_30%_20%,#f5fbf8_0,transparent_28%),linear-gradient(135deg,#dce7e7,#c3d7d4)] p-8 text-center"><div className="max-w-sm rounded-3xl bg-white/90 p-7 shadow-xl backdrop-blur"><MapPin className="mx-auto text-[#2a6074]" size={34} /><h3 className="mt-4 font-display text-3xl text-[#202a36]">Your route will appear here</h3><p className="mt-3 text-sm leading-relaxed text-[#71808a]">{loading ? 'Loading the GeoJSON route from your TripAI session…' : 'Ask TripAI for a route and this MapLibre map will render it here.'}</p></div></div>}<div className="absolute bottom-6 left-6 right-6 flex flex-col justify-between gap-4 rounded-3xl bg-white/90 p-5 backdrop-blur md:flex-row md:items-center"><div><p className="text-[10px] font-bold uppercase tracking-[0.15em] text-[#849098]">Backend GeoJSON · MapLibre GL JS</p><p className="mt-1 font-semibold text-[#202a36]">{route ? 'Route loaded from this session' : 'No route data yet'}</p></div><span className="rounded-full bg-[#e9f2f5] px-4 py-2 text-xs font-bold text-[#2a6074]">{route ? 'Route ready' : 'Waiting for route'}</span></div></div></div>
}

function ViewContent({ active, onChange, agentMessage, tripState, sessionId }: { active: View; onChange: (view: View) => void; agentMessage?: string; tripState: TripState; sessionId: string | null }) {
  if (active === 'wonder') return <WonderView onChange={onChange} agentMessage={agentMessage} tripState={tripState} />
  if (active === 'flights') return <FlightsView tripState={tripState} />
  if (active === 'trains') return <TrainsView />
  if (active === 'hotels') return <HotelsView tripState={tripState} />
  if (active === 'restaurants') return <RestaurantsView tripState={tripState} />
  if (active === 'weather') return <WeatherView tripState={tripState} />
  return <MapView tripState={tripState} sessionId={sessionId} />
}

export default function Dashboard({ onLogoClick, agentResult, sessionId, onNewResult }: {
  onLogoClick: () => void
  agentResult: AgentResponse | null
  sessionId: string | null
  onNewResult: (r: AgentResponse) => void
}) {
  const [active, setActive] = useState<View>('wonder')
  const [chatLoading, setChatLoading] = useState(false)
  const [currentMessage, setCurrentMessage] = useState<string | undefined>(agentResult?.message)
  const tripState = agentResult?.trip_state ?? {}
  const activeLabel = navItems.find((item) => item.id === active)?.label ?? 'Wonder'

  async function handleChat(text: string) {
    if (!sessionId) return
    setChatLoading(true)
    try {
      const result = await sendMessage(sessionId, text)
      setCurrentMessage(result.message)
      onNewResult(result)
    } catch {
      // silently ignore — user can retry
    } finally {
      setChatLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#f2f5f7] text-[#202a36]">
      <Sidebar active={active} onChange={setActive} onLogoClick={onLogoClick} />
      <main className="min-h-screen px-5 py-5 pb-28 md:px-8 lg:ml-[278px] lg:px-12 lg:py-8 lg:pb-28">
        <MobileNav active={active} onChange={setActive} />
        <header className="mb-10 flex items-center justify-between">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.22em] text-[#8a959d]">TripAI / {activeLabel}</p>
            <p className="mt-2 text-sm text-[#71808a]">Good morning, explorer <span aria-hidden="true">✦</span></p>
          </div>
          <div className="flex items-center gap-3">
            <button className="hidden items-center gap-2 rounded-full bg-white px-4 py-2.5 text-sm font-semibold text-[#62727c] shadow-sm sm:flex"><Globe2 size={16} /> INR · EN</button>
            <div className="grid h-11 w-11 place-items-center rounded-full bg-[#2a6074] text-sm font-bold text-white">NS</div>
          </div>
        </header>
        <ViewContent active={active} onChange={setActive} agentMessage={currentMessage} tripState={tripState} sessionId={sessionId} />
      </main>
      <ChatBar onSend={handleChat} loading={chatLoading} />
    </div>
  )
}
