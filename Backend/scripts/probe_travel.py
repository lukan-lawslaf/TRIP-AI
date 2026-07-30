"""Throwaway read-only probe of travel APIs. Never prints key material."""
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

ENV_PATH = pathlib.Path(r"C:\Users\Nakul\OneDrive\Documents\Tripai\.env")
env = {}
for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

SECRETS = [v for v in env.values() if len(v) > 12]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass


def scrub(text):
    if not isinstance(text, str):
        text = str(text)
    for s in SECRETS:
        text = text.replace(s, "<REDACTED>")
        text = text.replace(urllib.parse.quote(s), "<REDACTED>")
    return text


def shape(obj, depth=0, maxdepth=3):
    pad = "  " * depth
    if isinstance(obj, dict):
        out = []
        for k, v in list(obj.items())[:14]:
            if depth >= maxdepth:
                out.append(f"{pad}{k}: {type(v).__name__}")
            elif isinstance(v, (dict, list)):
                out.append(f"{pad}{k}:")
                out.append(shape(v, depth + 1, maxdepth))
            else:
                sv = scrub(repr(v))
                out.append(f"{pad}{k}: {type(v).__name__} = {sv[:90]}")
        return "\n".join(out)
    if isinstance(obj, list):
        if not obj:
            return f"{pad}[] (empty)"
        return f"{pad}[{len(obj)} items] first:\n" + shape(obj[0], depth + 1, maxdepth)
    return f"{pad}{type(obj).__name__} = {scrub(repr(obj))[:90]}"


def req(label, url, headers=None, method="GET", body=None, show=True, maxdepth=3):
    print("=" * 70)
    print(f"### {label}")
    print("URL:", scrub(url))
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    r = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(r, timeout=45) as resp:
            raw = resp.read().decode("utf-8", "replace")
            print("STATUS:", resp.status)
            interesting = {k: v for k, v in resp.headers.items()
                           if any(t in k.lower() for t in
                                  ("ratelimit", "rate-limit", "retry", "quota", "x-request", "x-ratelimit"))}
            if interesting:
                print("RL HEADERS:", scrub(json.dumps(interesting)))
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception as ee:
            raw = f"<body unreadable: {type(ee).__name__}>"
        print("STATUS:", e.code)
        interesting = {k: v for k, v in e.headers.items()
                       if any(t in k.lower() for t in ("ratelimit", "rate-limit", "retry", "quota"))}
        if interesting:
            print("RL HEADERS:", scrub(json.dumps(interesting)))
        print("ERR BODY:", scrub(raw)[:900])
        return None
    except Exception as e:
        print("EXC:", scrub(type(e).__name__ + ": " + str(e))[:400])
        return None
    try:
        j = json.loads(raw)
    except Exception:
        print("NON-JSON len", len(raw), scrub(raw)[:300])
        return None
    if show:
        print("SHAPE:")
        print(shape(j, 0, maxdepth))
    return j


FUTURE = (date.today() + timedelta(days=30)).isoformat()
FUTURE2 = (date.today() + timedelta(days=32)).isoformat()
sec = sys.argv[1] if len(sys.argv) > 1 else "all"


def run(n):
    return sec in ("all", n)


# 1 OpenWeatherMap
if run("1"):
    k = env["WEATHER_API_KEY"]
    req("OWM 2.5 current", f"https://api.openweathermap.org/data/2.5/weather?q=Kyoto&units=metric&appid={k}")
    req("OWM 2.5 forecast", f"https://api.openweathermap.org/data/2.5/forecast?q=Kyoto&units=metric&cnt=2&appid={k}", maxdepth=4)
    req("OWM 3.0 onecall", f"https://api.openweathermap.org/data/3.0/onecall?lat=35.01&lon=135.76&exclude=minutely,hourly&appid={k}", maxdepth=2)

# 2 Google Maps
if run("2"):
    k = env["GOOGLE_MAPS_DEMO_API_KEY"]
    req("GMaps Geocode", f"https://maps.googleapis.com/maps/api/geocode/json?address=Kyoto,Japan&key={k}", maxdepth=4)
    req("GMaps Directions", f"https://maps.googleapis.com/maps/api/directions/json?origin=Kyoto+Station&destination=Kinkaku-ji&mode=transit&key={k}", maxdepth=2)
    req("GMaps Places TextSearch (legacy)", f"https://maps.googleapis.com/maps/api/place/textsearch/json?query=ramen+in+Kyoto&key={k}", maxdepth=3)
    req("GMaps Places v1 searchText", "https://places.googleapis.com/v1/places:searchText",
        headers={"X-Goog-Api-Key": k, "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.rating,places.priceLevel,places.location"},
        method="POST", body={"textQuery": "ramen in Kyoto", "maxResultCount": 2}, maxdepth=4)
    req("Routes API computeRoutes", "https://routes.googleapis.com/directions/v2:computeRoutes",
        headers={"X-Goog-Api-Key": k, "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.legs.steps.transitDetails"},
        method="POST", body={
            "origin": {"address": "Kyoto Station, Japan"},
            "destination": {"address": "Kinkaku-ji, Kyoto, Japan"},
            "travelMode": "TRANSIT"}, maxdepth=3)

# 3 Foursquare
if run("3"):
    k = env["RESTAURANT_API_KEY"]
    req("FSQ legacy v3", "https://api.foursquare.com/v3/places/search?query=restaurant&near=Kyoto,Japan&limit=2",
        headers={"Authorization": k, "Accept": "application/json"}, maxdepth=4)
    req("FSQ new places-api", "https://places-api.foursquare.com/places/search?query=restaurant&near=Kyoto,Japan&limit=2",
        headers={"Authorization": f"Bearer {k}", "Accept": "application/json",
                 "X-Places-Api-Version": "2025-06-17"}, maxdepth=4)

# 4 Duffel
if run("4"):
    k = env["FLIGHT_API_KEY"]
    print("Duffel key prefix kind:", "test" if k.startswith("duffel_test") else ("live" if k.startswith("duffel_live") else "unknown-prefix"))
    j = req("Duffel offer_requests", "https://api.duffel.com/air/offer_requests?return_offers=true",
            headers={"Authorization": f"Bearer {k}", "Duffel-Version": "v2", "Accept": "application/json"},
            method="POST", body={"data": {
                "slices": [{"origin": "SFO", "destination": "JFK", "departure_date": FUTURE}],
                "passengers": [{"type": "adult"}],
                "cabin_class": "economy"}}, maxdepth=2)
    if j:
        offers = j.get("data", {}).get("offers", [])
        print("OFFER COUNT:", len(offers))
        if offers:
            print("FIRST OFFER SHAPE:")
            print(shape(offers[0], 0, 3))

# 5 liteAPI
if run("5"):
    k = env["HOTEL_API_KEY"]
    h = {"X-API-Key": k, "Accept": "application/json"}
    req("liteAPI hotels", "https://api.liteapi.travel/v3.0/data/hotels?countryCode=JP&cityName=Kyoto&limit=3", headers=h, maxdepth=3)
    req("liteAPI cities", "https://api.liteapi.travel/v3.0/data/cities?countryCode=JP", headers=h, maxdepth=2)
    req("liteAPI rates", "https://api.liteapi.travel/v3.0/hotels/rates",
        headers=h, method="POST", body={
            "checkin": FUTURE, "checkout": FUTURE2,
            "currency": "USD", "guestNationality": "US",
            "occupancies": [{"adults": 2}],
            "cityName": "Kyoto", "countryCode": "JP", "limit": 2}, maxdepth=3)

# 6 Navitia
if run("6"):
    k = env["TRAIN_DEMO_GLOBAL_API_TOKEN"]
    h = {"Authorization": k}
    j = req("Navitia coverage", "https://api.navitia.io/v1/coverage", headers=h, maxdepth=2)
    if j:
        for r in j.get("regions", []):
            print(" region:", r.get("id"), "|", r.get("name"), "| status:", r.get("status"), "| start:", r.get("start_production_date"), "end:", r.get("end_production_date"))
    req("Navitia places (fr-idf)", "https://api.navitia.io/v1/coverage/fr-idf/places?q=Gare%20de%20Lyon&type[]=stop_area", headers=h, maxdepth=3)
    req("Navitia journeys", "https://api.navitia.io/v1/coverage/fr-idf/journeys?from=2.3749%3B48.8443&to=2.2945%3B48.8584&datetime=" + FUTURE.replace("-", "") + "T090000", headers=h, maxdepth=2)

# 7 RapidAPI IRCTC
if run("7"):
    k = env["TRAIN_INDIA_API_KEY"]
    for host, path in [("irctc1.p.rapidapi.com", "/api/v3/searchTrain?query=12951"),
                       ("indian-railway-irctc.p.rapidapi.com", "/api/trains/v1/train/status?departure_date=" + FUTURE + "&isH5=true&client=web&train_number=12951"),
                       ("irctc-indian-railway-pnr-status.p.rapidapi.com", "/getPNRStatus/1234567890")]:
        req(f"RapidAPI {host}", f"https://{host}{path}",
            headers={"X-RapidAPI-Key": k, "X-RapidAPI-Host": host,
                     "x-rapid-api": "rapid-api-database"}, maxdepth=3)

# 8 FLIGHT_DATA_API_KEY
if run("8"):
    k = env["FLIGHT_DATA_API_KEY"]
    req("aviationstack https", f"https://api.aviationstack.com/v1/flights?access_key={k}&limit=1", maxdepth=3)
    req("aviationstack http", f"http://api.aviationstack.com/v1/flights?access_key={k}&limit=1", maxdepth=3)
    req("flightapi.io onewaytrip", f"https://api.flightapi.io/onewaytrip/{k}/SFO/JFK/{FUTURE}/1/0/0/Economy/USD", maxdepth=2)
    req("aviationstack airports", f"https://api.aviationstack.com/v1/airports?access_key={k}&limit=1", maxdepth=3)
    req("OWM-style check (is it an OWM key?)", f"https://api.openweathermap.org/data/2.5/weather?q=Kyoto&appid={k}", maxdepth=2)
    req("amadeus-style? aerodatabox", "https://aerodatabox.p.rapidapi.com/health/services/feeds/FlightSchedules",
        headers={"X-RapidAPI-Key": k, "X-RapidAPI-Host": "aerodatabox.p.rapidapi.com"}, maxdepth=2)

# 9 follow-ups
if run("9"):
    import base64
    # Navitia: try Basic auth (token as username) + query param
    k = env["TRAIN_DEMO_GLOBAL_API_TOKEN"]
    b = base64.b64encode(f"{k}:".encode()).decode()
    req("Navitia Basic auth", "https://api.navitia.io/v1/coverage",
        headers={"Authorization": f"Basic {b}"}, maxdepth=2)
    # Routes API: driving instead of transit
    g = env["GOOGLE_MAPS_DEMO_API_KEY"]
    req("Routes DRIVE", "https://routes.googleapis.com/directions/v2:computeRoutes",
        headers={"X-Goog-Api-Key": g,
                 "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline"},
        method="POST", body={
            "origin": {"address": "Kyoto Station, Japan"},
            "destination": {"address": "Kinkaku-ji, Kyoto, Japan"},
            "travelMode": "DRIVE"}, maxdepth=3)
    req("Routes TRANSIT raw", "https://routes.googleapis.com/directions/v2:computeRoutes",
        headers={"X-Goog-Api-Key": g, "X-Goog-FieldMask": "*"},
        method="POST", body={
            "origin": {"address": "Kyoto Station, Japan"},
            "destination": {"address": "Kinkaku-ji, Kyoto, Japan"},
            "travelMode": "TRANSIT"}, maxdepth=1)
    # Places v1 nearby (for POI/attractions)
    req("Places v1 searchNearby", "https://places.googleapis.com/v1/places:searchNearby",
        headers={"X-Goog-Api-Key": g,
                 "X-Goog-FieldMask": "places.displayName,places.types,places.rating,places.userRatingCount,places.location,places.regularOpeningHours.openNow"},
        method="POST", body={
            "includedTypes": ["tourist_attraction"], "maxResultCount": 2,
            "locationRestriction": {"circle": {"center": {"latitude": 35.0116, "longitude": 135.7681}, "radius": 5000.0}}}, maxdepth=3)
    # Duffel: segment detail
    d = env["FLIGHT_API_KEY"]
    j = req("Duffel offer detail", "https://api.duffel.com/air/offer_requests?return_offers=true",
            headers={"Authorization": f"Bearer {d}", "Duffel-Version": "v2", "Accept": "application/json"},
            method="POST", body={"data": {
                "slices": [{"origin": "SFO", "destination": "JFK", "departure_date": FUTURE}],
                "passengers": [{"type": "adult"}], "cabin_class": "economy"}}, show=False)
    if j:
        o = j["data"]["offers"][0]
        print("KEY OFFER FIELDS:", scrub(json.dumps({x: o.get(x) for x in
              ("id", "total_amount", "total_currency", "expires_at", "live_mode")})))
        print("owner:", json.dumps(o.get("owner")))
        sl = o["slices"][0]
        print("SLICE keys:", list(sl.keys()))
        print("slice duration:", sl.get("duration"), "fare_brand:", sl.get("fare_brand_name"))
        seg = sl["segments"][0]
        print("SEGMENT keys:", list(seg.keys()))
        print("seg sample:", json.dumps({x: seg.get(x) for x in
              ("departing_at", "arriving_at", "duration", "aircraft", "operating_carrier_flight_number")}))
        print("origin:", json.dumps({x: seg["origin"].get(x) for x in ("iata_code", "name", "city_name", "time_zone")}))
    # aviationstack extra endpoints
    a = env["FLIGHT_DATA_API_KEY"]
    for ep in ("airports", "airlines", "routes", "timetable?iataCode=SFO&type=departure", "cities"):
        req(f"aviationstack /{ep.split('?')[0]}",
            f"https://api.aviationstack.com/v1/{ep}{'&' if '?' in ep else '?'}access_key={a}&limit=1", maxdepth=2)

# 10 identify TRAIN_DEMO_GLOBAL_API_TOKEN
if run("10"):
    k = env["TRAIN_DEMO_GLOBAL_API_TOKEN"]
    import re
    print("format uuid-like:", bool(re.fullmatch(r"[0-9a-fA-F-]{36}", k)))
    req("Navitia ?key= query param", f"https://api.navitia.io/v1/coverage?key={k}", maxdepth=1)
    req("Transitland", f"https://transit.land/api/v2/rest/feeds?apikey={k}&limit=1", maxdepth=2)
    req("Transitous/MOTIS?", "https://api.transitous.org/api/v1/plan?fromPlace=48.8443,2.3749&toPlace=48.8584,2.2945", maxdepth=1)
