// Hardcoded demo data — will be replaced by backend API calls later.
// Shapes intentionally mirror the backend tool payloads (Duffel, liteAPI,
// Foursquare, OpenWeatherMap) so wiring up later is a data-source swap.

export interface Flight {
  id: string
  airline: string
  airlineCode: string
  from: string
  fromCity: string
  to: string
  toCity: string
  departTime: string
  arriveTime: string
  duration: string
  stops: number
  stopCity?: string
  price: number
  currency: string
  cabin: string
}

export const flights: Flight[] = [
  { id: 'f1', airline: 'ANA', airlineCode: 'NH', from: 'DEL', fromCity: 'New Delhi', to: 'HND', toCity: 'Tokyo', departTime: '11:45', arriveTime: '22:55', duration: '7h 40m', stops: 0, price: 48250, currency: '₹', cabin: 'Economy' },
  { id: 'f2', airline: 'Japan Airlines', airlineCode: 'JL', from: 'DEL', fromCity: 'New Delhi', to: 'NRT', toCity: 'Tokyo', departTime: '08:10', arriveTime: '19:35', duration: '7h 55m', stops: 0, price: 45990, currency: '₹', cabin: 'Economy' },
  { id: 'f3', airline: 'Singapore Airlines', airlineCode: 'SQ', from: 'DEL', fromCity: 'New Delhi', to: 'HND', toCity: 'Tokyo', departTime: '23:30', arriveTime: '14:20', duration: '11h 20m', stops: 1, stopCity: 'Singapore', price: 41780, currency: '₹', cabin: 'Economy' },
  { id: 'f4', airline: 'Air India', airlineCode: 'AI', from: 'DEL', fromCity: 'New Delhi', to: 'NRT', toCity: 'Tokyo', departTime: '14:20', arriveTime: '02:05', duration: '8h 15m', stops: 0, price: 39990, currency: '₹', cabin: 'Economy' },
  { id: 'f5', airline: 'Thai Airways', airlineCode: 'TG', from: 'DEL', fromCity: 'New Delhi', to: 'HND', toCity: 'Tokyo', departTime: '13:55', arriveTime: '06:50', duration: '13h 25m', stops: 1, stopCity: 'Bangkok', price: 37450, currency: '₹', cabin: 'Economy' },
  { id: 'f6', airline: 'Cathay Pacific', airlineCode: 'CX', from: 'DEL', fromCity: 'New Delhi', to: 'NRT', toCity: 'Tokyo', departTime: '01:20', arriveTime: '15:30', duration: '10h 40m', stops: 1, stopCity: 'Hong Kong', price: 36200, currency: '₹', cabin: 'Economy' },
  { id: 'f7', airline: 'Emirates', airlineCode: 'EK', from: 'DEL', fromCity: 'New Delhi', to: 'HND', toCity: 'Tokyo', departTime: '10:15', arriveTime: '08:10', duration: '14h 25m', stops: 1, stopCity: 'Dubai', price: 52100, currency: '₹', cabin: 'Premium Economy' },
  { id: 'f8', airline: 'Korean Air', airlineCode: 'KE', from: 'DEL', fromCity: 'New Delhi', to: 'NRT', toCity: 'Tokyo', departTime: '19:40', arriveTime: '13:15', duration: '12h 05m', stops: 1, stopCity: 'Seoul', price: 43800, currency: '₹', cabin: 'Economy' },
  { id: 'f9', airline: 'Malaysia Airlines', airlineCode: 'MH', from: 'DEL', fromCity: 'New Delhi', to: 'HND', toCity: 'Tokyo', departTime: '00:10', arriveTime: '16:45', duration: '13h 05m', stops: 1, stopCity: 'Kuala Lumpur', price: 34890, currency: '₹', cabin: 'Economy' },
  { id: 'f10', airline: 'Lufthansa', airlineCode: 'LH', from: 'DEL', fromCity: 'New Delhi', to: 'NRT', toCity: 'Tokyo', departTime: '02:00', arriveTime: '08:35', duration: '17h 05m', stops: 1, stopCity: 'Frankfurt', price: 55750, currency: '₹', cabin: 'Economy' },
]

export interface Hotel {
  id: string
  name: string
  area: string
  city: string
  rating: number
  reviews: number
  pricePerNight: number
  currency: string
  tags: string[]
  image: string
}

export const hotels: Hotel[] = [
  { id: 'h1', name: 'The Celestine Kyoto Gion', area: 'Gion', city: 'Kyoto', rating: 4.8, reviews: 1240, pricePerNight: 14500, currency: '₹', tags: ['Onsen', 'Breakfast', 'Near temples'], image: 'https://images.unsplash.com/photo-1578469645742-46cae010e5d4?w=800&q=70' },
  { id: 'h2', name: 'Hotel Kanra Kyoto', area: 'Shimogyo', city: 'Kyoto', rating: 4.7, reviews: 986, pricePerNight: 12800, currency: '₹', tags: ['Machiya style', 'Spa'], image: 'https://images.unsplash.com/photo-1542051841857-5f90071e7989?w=800&q=70' },
  { id: 'h3', name: 'Park Hyatt Tokyo', area: 'Shinjuku', city: 'Tokyo', rating: 4.9, reviews: 2110, pricePerNight: 32400, currency: '₹', tags: ['Skyline view', 'Pool'], image: 'https://images.unsplash.com/photo-1540959733332-eab4deabeeaf?w=800&q=70' },
  { id: 'h4', name: 'Trunk Hotel Shibuya', area: 'Shibuya', city: 'Tokyo', rating: 4.6, reviews: 754, pricePerNight: 18900, currency: '₹', tags: ['Boutique', 'Rooftop bar'], image: 'https://images.unsplash.com/photo-1503899036084-c55cdd92da26?w=800&q=70' },
  { id: 'h5', name: 'Hoshinoya Ryokan', area: 'Arashiyama', city: 'Kyoto', rating: 4.9, reviews: 623, pricePerNight: 41200, currency: '₹', tags: ['Riverside', 'Kaiseki dining'], image: 'https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?w=800&q=70' },
  { id: 'h6', name: 'Mimaru Tokyo Ueno', area: 'Ueno', city: 'Tokyo', rating: 4.5, reviews: 431, pricePerNight: 9800, currency: '₹', tags: ['Family rooms', 'Kitchenette'], image: 'https://images.unsplash.com/photo-1526481280693-3bfa7568e0f3?w=800&q=70' },
]

export interface Restaurant {
  id: string
  name: string
  cuisine: string
  area: string
  city: string
  rating: number
  priceLevel: 1 | 2 | 3 | 4
  distance: string
  highlight: string
  image: string
}

export const restaurants: Restaurant[] = [
  { id: 'r1', name: 'Gion Karyo', cuisine: 'Kaiseki', area: 'Gion', city: 'Kyoto', rating: 4.8, priceLevel: 3, distance: '350 m', highlight: 'Seasonal 9-course kaiseki in a century-old machiya', image: 'https://images.unsplash.com/photo-1580822184713-fc5400e7fe10?w=800&q=70' },
  { id: 'r2', name: 'Ichiran Shibuya', cuisine: 'Ramen', area: 'Shibuya', city: 'Tokyo', rating: 4.5, priceLevel: 1, distance: '1.2 km', highlight: 'Solo-booth tonkotsu ramen, open till late', image: 'https://images.unsplash.com/photo-1557872943-16a5ac26437e?w=800&q=70' },
  { id: 'r3', name: 'Sushi Saito', cuisine: 'Sushi', area: 'Roppongi', city: 'Tokyo', rating: 4.9, priceLevel: 4, distance: '2.4 km', highlight: 'Three Michelin stars — book months ahead', image: 'https://images.unsplash.com/photo-1579871494447-9811cf80d66c?w=800&q=70' },
  { id: 'r4', name: '% Arabica Higashiyama', cuisine: 'Café', area: 'Higashiyama', city: 'Kyoto', rating: 4.6, priceLevel: 1, distance: '600 m', highlight: 'Hidden café with a view of Yasaka Pagoda', image: 'https://images.unsplash.com/photo-1521017432531-fbd92d768814?w=800&q=70' },
  { id: 'r5', name: 'Nishiki Warai', cuisine: 'Okonomiyaki', area: 'Nishiki Market', city: 'Kyoto', rating: 4.4, priceLevel: 2, distance: '900 m', highlight: 'Market-side okonomiyaki, big portions', image: 'https://images.unsplash.com/photo-1512058564366-18510be2db19?w=800&q=70' },
  { id: 'r6', name: 'Uobei Genki Sushi', cuisine: 'Conveyor Sushi', area: 'Shibuya', city: 'Tokyo', rating: 4.3, priceLevel: 1, distance: '1.1 km', highlight: 'High-speed rail sushi delivery, great value', image: 'https://images.unsplash.com/photo-1553621042-f6e147245754?w=800&q=70' },
]

export interface Destination {
  id: string
  name: string
  country: string
  blurb: string
  image: string
}

export const featuredDestinations: Destination[] = [
  { id: 'd1', name: 'Kyoto', country: 'Japan', blurb: 'Temples, tea houses and autumn maple trails', image: 'https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?w=900&q=70' },
  { id: 'd2', name: 'Hallstatt', country: 'Austria', blurb: 'Lakeside alpine village frozen in time', image: 'https://images.unsplash.com/photo-1516550893923-42d28e5677af?w=900&q=70' },
  { id: 'd3', name: 'Santorini', country: 'Greece', blurb: 'White cliffs and caldera sunsets', image: 'https://images.unsplash.com/photo-1613395877344-13d4a8e0d49e?w=900&q=70' },
]

export interface Deal {
  id: string
  title: string
  subtitle: string
  discount: string
  image: string
}

export const topDeals: Deal[] = [
  { id: 't1', title: 'Bali Monsoon Escape', subtitle: '5 nights · villa + breakfast', discount: '32% off', image: 'https://images.unsplash.com/photo-1537996194471-e657df975ab4?w=800&q=70' },
  { id: 't2', title: 'Swiss Rail Circuit', subtitle: '7 days · scenic pass included', discount: '18% off', image: 'https://images.unsplash.com/photo-1530122037265-a5f1f91d3b99?w=800&q=70' },
  { id: 't3', title: 'Dubai Long Weekend', subtitle: '3 nights · desert safari', discount: '25% off', image: 'https://images.unsplash.com/photo-1512453979798-5ea266f8880c?w=800&q=70' },
]

export interface ItineraryDay {
  day: number
  title: string
  items: { time: string; activity: string; note?: string }[]
}

export const sampleItinerary: ItineraryDay[] = [
  {
    day: 1,
    title: 'Arrival — Tokyo',
    items: [
      { time: '15:00', activity: 'Land at Haneda, Limousine Bus to Shinjuku' },
      { time: '18:00', activity: 'Check in, walk Omoide Yokocho', note: 'Tiny yakitori alleys — cash only' },
      { time: '20:30', activity: 'Night view from Tokyo Metropolitan Building', note: 'Free observation deck' },
    ],
  },
  {
    day: 2,
    title: 'Old Tokyo & Hidden Cafés',
    items: [
      { time: '08:30', activity: 'Senso-ji before the crowds', note: 'Arrive before 9am' },
      { time: '11:00', activity: 'Kappabashi kitchen street + hidden kissaten coffee' },
      { time: '15:00', activity: 'Yanaka Ginza old-town stroll' },
      { time: '19:00', activity: 'Ramen at a counter-only shop in Ueno' },
    ],
  },
  {
    day: 3,
    title: 'Shinkansen to Kyoto',
    items: [
      { time: '09:12', activity: 'Nozomi shinkansen to Kyoto', note: 'Sit on the right for Mt. Fuji' },
      { time: '13:00', activity: 'Check in near Gion, lunch at Nishiki Market' },
      { time: '16:30', activity: 'Higashiyama lanes + % Arabica coffee' },
      { time: '19:30', activity: 'Evening walk through Gion', note: 'Quietest after 7pm' },
    ],
  },
  {
    day: 4,
    title: 'Scenic Hike — Fushimi & Arashiyama',
    items: [
      { time: '07:00', activity: 'Fushimi Inari full loop hike', note: '2–3h, crowds thin past the midpoint' },
      { time: '13:00', activity: 'Arashiyama bamboo grove + riverside lunch' },
      { time: '16:00', activity: 'Okochi Sanso villa garden', note: 'Entry includes matcha' },
    ],
  },
]

export interface WeatherDay {
  day: string
  condition: 'sun' | 'cloud' | 'rain'
  high: number
  low: number
  pop: number
}

export const weatherForecast: WeatherDay[] = [
  { day: 'Today', condition: 'sun', high: 26, low: 18, pop: 0 },
  { day: 'Tue', condition: 'sun', high: 27, low: 19, pop: 10 },
  { day: 'Wed', condition: 'cloud', high: 24, low: 17, pop: 30 },
  { day: 'Thu', condition: 'rain', high: 21, low: 16, pop: 80 },
  { day: 'Fri', condition: 'cloud', high: 23, low: 16, pop: 40 },
]
