# TripAI — Project Memory / Cross-Platform Handoff

> Working notes so this project can be continued from Claude Code, Codex, Antigravity, or
> any other environment. **Everything under "Verified provider facts" was tested live** —
> trust it over vendor docs and over the original build spec, both of which are stale in
> several places.
>
> Last updated: 2026-07-29 (Codex continuation)

---

## 1. What this is

Backend for an AI travel planner. Users describe trips in natural language (multilingual),
optionally attach images/video, and get multi-day itineraries with conversational
follow-ups and session memory. Agentic: the LLM decides which tools to call.

**Backend only.** No frontend. FastAPI HTTP surface for a future frontend to consume.

**Core design constraint:** model-agnostic. Every LLM call goes through a role-based
router (`app/llm/router.py`). Business logic asks for a *role* (`"orchestrator"`,
`"synthesis"`, `"memory"`, `"field_extractor"`) and never names a model. Swapping models
is an edit to `app/llm/roles.py` and nothing else.

## 2. Layout

```
Tripai/
  .env                   # 11 provisioned keys, git-ignored, NEVER commit or print
  .gitignore             # covers .env, .venv, data/, chroma/
  Projectmemeory.md       # this file
  Backend/
    .venv/               # USE THIS — see "Environment" below
    requirements.txt
    app/
      config.py          # pydantic-settings; only place that reads env
      llm/
        roles.py         # PROVIDERS + MODEL_ROLES  ← swap models HERE
        types.py         # Message/ToolCall/LLMResponse + error taxonomy
        breaker.py       # circuit breaker registry (LLM + external APIs)
        adapters.py      # provider-agnostic types → OpenAI chat-completions wire
        router.py        # role → candidate failover, breaker skip, health()
        structured.py    # native JSON mode + defensive parse
      tools/             # deterministic API layer (no LLM in the loop)
      memory/            # models + session state + summarization service
      rag/               # ChromaDB + all-MiniLM-L6-v2
      api/               # FastAPI routes
      storage/           # SQLite persistence
    scripts/             # probe_*.py — live provider verification, safe to re-run
    tests/
```

## 3. Environment

**Use the project venv, not the global interpreter.**

```bash
cd Backend
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# .venv/bin/python -m pip install -r requirements.txt          # macOS/Linux
.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

Why: installing this project's pins globally downgraded `pydantic` to 2.10.4 and broke
unrelated packages the user had installed (`realtime`, `storage3` need >=2.11.7). The
global env has been restored to pydantic 2.13.4 — keep it that way. `requirements.txt`
now pins `pydantic>=2.11.7,<3` to prevent a repeat.

Python 3.11.9. On Windows use `PYTHONIOENCODING=utf-8` when running probe scripts —
provider JSON contains characters cp1252 can't decode, and `json.load(open(...))` without
`encoding="utf-8"` will crash.

**Do not `source .env` / `set -a` in bash.** Some key values contain characters that break
shell sourcing (an IRCTC value gets interpreted as a command). Parse it in Python instead.

---

## 4. Verified provider facts

All probed live on 2026-07-25/26 with the real keys. Re-runnable via
`Backend/scripts/probe_providers.py`, `probe_capabilities.py`, `probe_travel.py`.

### 4.1 LLM routes — all working

| Role | Candidate | Route | Status |
|---|---|---|---|
| orchestrator p1 | `google/gemma-4-31b-it:free` | OpenRouter, upstream `google-ai-studio` | 200, **but frequently 429** |
| orchestrator p2 | `google/gemma-4-26b-a4b-it:free` | OpenRouter, upstream `darkbloom` | 200, tool calls verified |
| orchestrator p3 | `meta-llama/llama-4-scout-17b-16e-instruct` | Groq | text/vision fallback |
| synthesis p1 | `nvidia/nemotron-3-super-120b-a12b` | NVIDIA NIM direct | 200, `json_schema` verified |
| synthesis p2 | `nvidia/nemotron-3-ultra-550b-a55b:free` | OpenRouter | 200 |
| memory / field_extractor | `llama-3.1-8b-instant` | Groq | 200 |

**Corrections to the original build spec — it had these wrong:**

1. `google/gemma-4-26b-a4b:free` **does not exist**. Real id is
   `google/gemma-4-26b-a4b-it:free` (note the `-it`).
2. `google-ai-studio` and `darkbloom` are OpenRouter **upstream provider tags**, not
   separate vendors/base URLs. Pin them in the request body:
   `"provider": {"order": ["darkbloom"], "allow_fallbacks": false}`. Both slugs confirmed
   valid via `GET https://openrouter.ai/api/v1/providers`.
3. `nvidia/nemotron-3-super` → actual NIM id is `nvidia/nemotron-3-super-120b-a12b`.
4. **No Google AI Studio key is provisioned** and none is needed — Gemma is reached
   through OpenRouter's `google-ai-studio` upstream. The `google-ai-studio` ProviderSpec
   exists in `roles.py` for the day someone adds `GOOGLE_API_KEY`/`GEMINI_API_KEY`, but
   it is currently skipped for lack of a key (the router skips keyless candidates rather
   than failing).

**Gemma 4 accepts image AND video natively** (`input_modalities: [image, text, video]`,
262k ctx) — so the orchestrator's multimodal requirement is met by the primary route.

**The fallback chain is load-bearing, not decorative.** `gemma-4-31b-it:free` returned
persistent upstream 429s during verification. Expect the p2 candidate to serve a large
share of real traffic.

**Structured-output support is uneven — this shaped the design:**
- Groq `llama-3.1-8b-instant`: rejects `json_schema` (`400 invalid_request_error`),
  **accepts `json_object`**. Verified both ways.
- NIM `nemotron-3-super-120b-a12b`: full `json_schema` strict mode works.
- `nemotron-3-ultra-550b-a55b:free`: advertises neither `response_format` nor
  `structured_outputs`.
- Hence `ModelCandidate.supports_json_schema` / `supports_json_object` flags, and
  `structured.py` which requests the strongest native mode available and *also* injects
  the schema into the prompt as backstop, then parses defensively (fences, embedded
  objects). Capability downgrades are logged, never silent.

### 4.2 Travel APIs

| # | API | Env key | Status |
|---|---|---|---|
| 1 | OpenWeatherMap | `WEATHER_API_KEY` | ✅ **2.5 only** |
| 2 | Google Maps | `GOOGLE_MAPS_DEMO_API_KEY` | ⚠️ new APIs only |
| 3 | Foursquare | `RESTAURANT_API_KEY` | ✅ new host only |
| 4 | Duffel | `FLIGHT_API_KEY` | ✅ test mode |
| 5 | liteAPI | `HOTEL_API_KEY` | ✅ sandbox |
| 6 | Navitia | `TRAIN_DEMO_GLOBAL_API_TOKEN` | ❌ **intentionally disabled** |
| 7 | RapidAPI IRCTC | `TRAIN_INDIA_API_KEY` | ❌ **intentionally disabled** |
| 8 | aviationstack | `FLIGHT_DATA_API_KEY` | ✅ 100 calls/month |

**1. OpenWeatherMap** — `/data/2.5/weather?q=Kyoto&units=metric&appid=KEY` and
`/data/2.5/forecast` both 200. **One Call 3.0 → 401**, needs a separate subscription; do
not use it. Forecast is 5-day/3-hour (40 entries); anything beyond 5 days needs another
provider. Parse `main.temp`, `weather[0].description`, `wind.speed`, `list[].dt_txt`,
`list[].pop`.

**2. Google Maps** — legacy APIs are **denied** on this key:
- Geocoding `maps/api/geocode/json` → `REQUEST_DENIED` ("must enable Billing")
- legacy Directions / legacy Places Text Search → `REQUEST_DENIED` ("calling a legacy API")

What **does** work:
- Places API (New): `POST https://places.googleapis.com/v1/places:searchText`
  (and `:searchNearby`), headers `X-Goog-Api-Key` + **mandatory** `X-Goog-FieldMask`.
- Routes API: `POST https://routes.googleapis.com/directions/v2:computeRoutes`,
  same key header + FieldMask. **`DRIVE` works; `TRANSIT` returns 200 with an empty
  `routes` array** — transit routing unusable on this key.
- Geocoding workaround: use Places `searchText` to resolve a name → lat/lng.

**3. Foursquare** — legacy `api.foursquare.com/v3/places/search` → 401. Use:
```
GET https://places-api.foursquare.com/places/search?query=restaurant&near=Kyoto,Japan
Authorization: Bearer <key>
X-Places-Api-Version: 2025-06-17     # ONLY this value validates; others → 400
```
v3 passed its stated deprecation (2026-05-15). Parse `results[].name`, `.fsq_place_id`,
`.location.formatted_address`, `.categories[].name`, `.latitude/.longitude`, `.distance`.
No rating/price in the default field set — request `fields=` explicitly.
Rate limits: `X-RateLimit-Burst-Limit: 150`.

**4. Duffel** — `POST https://api.duffel.com/air/offer_requests?return_offers=true`,
headers `Authorization: Bearer <key>`, **`Duffel-Version: v2`** (v1/beta → `unsupported_version`),
`Accept: application/json`. Returned 201 with 24 offers for SFO→JFK.
- **Test mode** (`data.live_mode: false`); prices come back in **AUD**, the account default.
- **Offers expire ~1h** (`expires_at`) — cache TTL must stay under that.
- Parse `total_amount`/`total_currency`, `owner.name`, `slices[].duration` (ISO-8601
  `PT10H19M`), `slices[].segments[].{departing_at,arriving_at,origin.iata_code,...}`.
- Rate limit: `ratelimit-limit: 30`.

**5. liteAPI** — `X-API-Key: <key>` (not Bearer) on `https://api.liteapi.travel/v3.0`.
- `GET /data/hotels?countryCode=JP&cityName=Kyoto&limit=3` → 200
- `POST /hotels/rates` → 200 with
  `{"checkin","checkout","currency":"USD","guestNationality":"US","occupancies":[{"adults":2}],"cityName","countryCode","limit"}`
- **`x-ratelimit-limit: 5` per second — throttle.** `roomTypes` can be ~200 entries per
  hotel; truncate hard before sending to an LLM.

**6. Navitia — DEAD and intentionally disabled.** Token is a well-formed UUID but `401 "Token absent in the database"`.
Tried bare header, HTTP Basic, `?key=`. Also fails against Transitland, so it isn't
mislabeled. **Do not sign up or chase a replacement token; keep this provider disabled.**
`GET /v1/coverage/{region}/journeys?from=LON;LAT&to=LON;LAT&datetime=YYYYMMDDTHHMMSS`,
auth `Authorization: <token>` (bare, no Bearer).

**7. RapidAPI IRCTC — DEAD and intentionally disabled.** `403 "You are not subscribed to this API."` on
`irctc1.p.rapidapi.com`, `indian-railway-irctc.*`, `irctc-indian-railway-pnr-status.*`.
Key itself is valid (403, not 401) — **do not subscribe to a host; keep this provider disabled**.

**8. `FLIGHT_DATA_API_KEY` is aviationstack** (identified by probe; not flightapi.io, not
RapidAPI). `GET https://api.aviationstack.com/v1/flights?access_key=KEY` → 200.
`/routes` → 403 (paid only). **`x-quota-limit: 100` per MONTH** — this is a flight-status
lookup reserved for explicit user requests, cache-backed. It is *not* a viable
general-purpose fallback for Duffel search.

### 4.3 Consequences for the build

- Train lookups have **no working provider and will remain disabled**. `train_lookup()`
  returns a static unavailable result and must never call Navitia or RapidAPI IRCTC.
- Transit directions unavailable → intra-city legs use DRIVE routing or Foursquare
  `.distance`. Never present a transit duration we can't source.
- Geocoding goes through Places (New) `searchText`, not the Geocoding API.
- aviationstack's 100/month quota means flight *status* is a distinct, rare operation from
  flight *search* (Duffel). Don't conflate them.

---

## 5. Design decisions worth preserving

- **Deterministic tools contain zero LLM calls.** Once trip-state is known,
  `flight_lookup(SFO, JFK, date)` is a typed HTTP call. Routing it through a model adds
  latency, burns rate-limited quota, and invents a hallucination surface for nothing.
- **`synthesis` never fetches.** Backend does the lookups in plain code, then hands raw
  structured results + constraints to `synthesis` to rank/select/resolve conflicts. It
  returns a decision, not data.
- **Two breaker registries** (`get_llm_breakers()` / `get_api_breakers()`) with different
  cooldowns — a flaky hotel API shouldn't make us equally patient with a model quota.
  External APIs get 60s, model candidates 300s.
- **Keyless candidates are skipped, not attempted.** A partly provisioned `.env` degrades
  to fewer candidates instead of failing every call.
- **Breaker half-open admits exactly one probe** (`probe_in_flight`), so a recovering
  provider gets one test request, not a thundering herd.

## 6. Status

- [x] 1 — Config + settings + MODEL_ROLES + .gitignore + venv
- [x] 2 — Model router: role failover, circuit breaker, structured output, `health()`
- [x] 3 — Deterministic tool layer (provider-backed tools + `web_search`)
- [x] 4 — Orchestrator integration (tool schemas, multimodal, bounded tool loop)
- [x] 5 — Synthesis wiring
- [x] 6 — Memory / session state foundation (models, SQLite persistence, memory service)
- [x] 7 — RAG (ChromaDB + all-MiniLM-L6-v2, semantic chunking, hybrid BM25+embedding)
- [x] 8 — API surface foundation + error handling + existing tool caching
- [x] 9 — `/health/models` observability endpoint

## 8. Codex continuation notes (2026-07-26)

The previous Claude run timed out while starting the memory/session layer. The files it
successfully created were `Backend/app/memory/models.py` and
`Backend/app/storage/db.py`; the missing seam is now implemented in
`Backend/app/memory/service.py`.

The attached "AI Travel Planner — Backend Build Spec" was reviewed on this date. Treat it
as the original product baseline, not as the current provider truth: the live probes
corrected several model IDs/auth assumptions, and the newly added Serper/Tavily keys are
now available. The implementation also deliberately uses SQLite plus local Chroma for
the zero-service development path; PostgreSQL/pgvector remains the production migration
target and is not complete yet.

Memory service behavior:

- `extract_update()` calls the cheap `memory` role and asks for a partial `TripState`.
- `update_from_user_turn()` loads recent turns, merges conservatively, and persists the
  last known-good state. Model outages and semantically invalid JSON do not erase state.
- `build_context()` returns bounded recent turns, compact trip state, and summaries of a
  returning user's prior sessions; it never injects their full old transcripts.
- `maybe_summarize()` refreshes the rolling summary after `summarize_after_turns`.
- `Backend/tests/test_memory.py` covers conservative merge, deduplicated preferences,
  plan-item upsert, compact context, and plannability checks.

Current status: deterministic tools and the memory/session foundation are complete. The
core orchestrator loop is now implemented in `Backend/app/agent/orchestrator.py`: it
assembles memory context, calls the `orchestrator` role with
`tool_specs_for_orchestrator()`, dispatches independent tool calls concurrently, caps
tool rounds at four, and persists the assistant turn. FastAPI exposure is now complete;
the remaining backend seam is handing results to `synthesis`.

The orchestrator intentionally does not persist media bytes. Attachments are passed only
on the current user message, while SQLite keeps the text turn and media count. Tool
payloads returned to the model are capped at 30,000 characters to protect context from
large hotel-rate responses.

FastAPI exposure is now in `Backend/app/main.py` and `Backend/app/api/routes.py`:

- `POST /session` creates a session.
- `POST /session/{id}/message` accepts JSON text or multipart text plus image/video files.
- `GET /session/{id}/state` returns the structured trip state.
- `POST /session/{id}/plan` runs an orchestrator planning prompt; full synthesis is still
  pending.
- `GET /health` and `GET /health/models` provide liveness and role/breaker visibility.

Train policy is now hardcoded in `Backend/app/tools/trains.py`: `train_lookup()` makes
zero network calls and always returns `unavailable` with the message that train data is
not available right now. Navitia and RapidAPI IRCTC must not be re-enabled, subscribed
to, or used for future probes. Google Maps remains limited to the already-working
Places-New search and drive routing; do not add legacy geocoding/transit calls or change
billing.

The `.env` now also contains working `GOOGLE_STUDIO_API_KEY`, `WEB_SEARCH_API_KEY`
(Serper), and `WEB2_SEARCH_API_KEY` (Tavily). `config.py` and `roles.py` were updated so
direct Google AI Studio Gemma is orchestrator priority 1, with OpenRouter/Groq fallback,
and `web_search` is the eighth exposed semantic tool. The provider table above predates
this direct-key discovery; treat the newer `roles.py` and this note as current.

New map keys are present: `LocationIQ_API_KEY` and `openrouteservice_API_KEY`. They are
configured in `app/config.py` and now form the primary routing stack:
openrouteservice first, LocationIQ second, and the verified Google Routes path last as a
resilience fallback. `app/tools/maps.py` supports alternatives, turn-by-turn steps,
avoid-feature options, route metadata, and MapLibre-ready GeoJSON
`FeatureCollection` output. MapLibre GL JS is a frontend renderer, not a Python backend
dependency; its documented GeoJSON source and line-layer pattern is the intended
consumer of this response.

## 9. Frontend ↔ Backend connection (2026-07-27, Claude Code)

### What was done
- `Backend/app/main.py` — added `CORSMiddleware` allowing `http://localhost:5173` and `http://127.0.0.1:5173` (Vite dev server).
- `frountend/src/api/client.ts` — new typed API client with `createSession()` (POST /session) and `sendMessage()` (POST /session/{id}/message). Base URL from `VITE_API_URL` env var, falls back to `http://localhost:8000`.
- `frountend/src/components/loading/PlanningLoader.tsx` — now calls `createSession` + `sendMessage` in parallel with the step animation. Waits for API before calling `onDone(AgentResponse | null)`. Shows "Using demo data — backend offline" if the call fails.
- `frountend/src/App.tsx` — holds `AgentResponse | null` state, passes it to `Dashboard`.
- `frountend/src/components/landing/Hero.tsx` — prompt card is now an editable `<textarea>`; upload button moved to bottom-left; file accept includes `video/*`.
- `frountend/src/components/dashboard/Dashboard.tsx` — accepts `agentResult` prop; `WonderView` shows a "TripAI says" card with the AI message when the backend responded.

### How to run
```bash
# Terminal 1 — backend
cd Backend
.venv/Scripts/python.exe -m uvicorn app.main:app --reload

# Terminal 2 — frontend
cd frountend
npm run dev
```
Open http://localhost:5173. Type a trip prompt, click Plan My Trip. The loader calls the backend; the Wonder view shows the AI reply.

### Also done (2026-07-28, Claude Code continuation)
- `frountend/src/components/dashboard/ChatBar.tsx` — new fixed-bottom chat input bar. Sends follow-up messages to the same session via `sendMessage`, shows a spinner while waiting, updates the Wonder view reply on response.
- `frountend/src/App.tsx` — stores `sessionId` in `localStorage` under key `tripai_session_id` so a page refresh reconnects to the existing session. Passes `sessionId` and `onNewResult` down to Dashboard.
- `frountend/src/components/dashboard/Dashboard.tsx` — accepts `sessionId` + `onNewResult` props; owns `chatLoading` and `currentMessage` state; wires ChatBar; main content area has `pb-28` so content is never hidden behind the chat bar.

### Also done (2026-07-28, Claude Code — session 2)
- `frountend/src/components/dashboard/ChatBar.tsx` — fixed-bottom chat input, spinner while waiting, Enter to send.
- `frountend/src/App.tsx` — `sessionId` persisted to `localStorage` key `tripai_session_id`; passed to Dashboard with `onNewResult` callback.
- `frountend/src/components/dashboard/Dashboard.tsx` — owns `chatLoading` + `currentMessage` state; wires ChatBar; `pb-28` on main so content never hides behind bar.

### Current state (ready to run)
```bash
cd Backend && .venv/Scripts/python.exe -m uvicorn app.main:app --reload
cd frountend && npm run dev   # http://localhost:5173
```
Full flow works: type prompt → loader calls backend → Wonder view shows AI reply → ChatBar sends follow-ups to same session → session survives page refresh.

### Next priorities (historical snapshot; completed in section 10)
1. Wire real `trip_state` from `AgentResponse` into Weather / Flights / Hotels views — shapes in `src/data/mock.ts` already mirror backend payloads, it is a data-source swap.
2. Map view — replace illustrated SVG with MapLibre GL JS consuming GeoJSON from `GET /session/{id}/state` → `trip_state.route` (produced by `app/tools/maps.py`).
3. Backend synthesis wiring (step 5 of original spec — `app/agent/orchestrator.py` hands raw tool results to the `synthesis` role).
4. RAG (step 7 — ChromaDB + all-MiniLM-L6-v2, hybrid BM25+embedding retrieval).
5. Production path: PostgreSQL swap, auth, `VITE_API_URL` env var for deployed backend.

Frontend continuation (2026-07-27):

- The intentionally named `frountend/` app now has a working landing -> planning loader
  -> dashboard flow in `src/App.tsx`.
- `src/components/dashboard/Dashboard.tsx` implements the Wonder, Flights, Hotels,
  Restaurants, Weather, Map, and Trains views using existing mock data. The Map view is
  currently an illustrated hardcoded route; it does not call the backend yet.
- Trains is explicitly presented as "Coming soon" and contains no schedules or train API
  calls, preserving the backend train policy above.
- Hotel and restaurant pages use the local video assets in `public/videos/`; no new
  subscriptions, billing changes, or API keys were added.
- Vite now uses native ESM config in `vite.config.mjs` and the package scripts select it;
  this avoids the OneDrive Windows access failure from the TypeScript config loader.

Frontend validation: `npm.cmd run build` passes, and a local browser smoke test verified
the landing screen, planning loader, dashboard, and trains coming-soon state.

Frontend visual continuation (2026-07-27, Codex):

- Reworked `frountend/src/components/dashboard/Dashboard.tsx` to follow the supplied
  layout reference: rounded white navigation shell, muted blue-grey palette, Wonder
  moodboard, destination cards, and responsive mobile navigation.
- Flights now follows the full `flightdesign.md` composition: CloudFront hero video,
  premium two-line heading, centered CTA treatment, desktop navigation, mobile menu,
  and a hardcoded TripAI route summary. It remains demo-only and is not connected to
  FastAPI.
- Trains now follows the full `traindesign.md` composition: four crossfading CloudFront
  scenes, the supplied transparent PNG overlay with train-bob animation, liquid-glass
  navigation and email-style CTA, scene switcher, dark text mode for Deep Woods, and
  bottom stats. TripAI content says "Train planning is coming soon" and intentionally
  shows zero fake schedules; no train lookup is called.
- Hotels and Restaurants retain the local `public/videos/hotel.mp4` and
  `public/videos/restaurant.mp4` hero videos. Weather and Map remain hardcoded demo
  views, with Map using an illustrated route until the future MapLibre integration.
- No new subscriptions, billing changes, signups, API keys, or backend/frontend
  connections were introduced. The local Vite preview is available at
  `http://127.0.0.1:5173/` while the dev process is running.

Visual validation after the rebuild: `npm.cmd run build` passes; browser checks verified
landing -> planning -> Wonder, Flights content (`Go further. Feel closer.`), and Trains
content (`Train planning is coming soon`, `0 fake schedules`).

Validation note: the checked-in `Backend/.venv` currently points at the old base
interpreter path `C:\Users\Nakul\AppData\Local\Programs\Python\Python311\python.exe`,
which is absent in this environment. Its `python.exe` and `pip.exe` cannot launch.
Do not install this project's pins globally; recreate the project venv with an available
Python 3.11 interpreter before running pytest or uvicorn. Compile-only validation passes
with the bundled Python runtime. The test suite cannot run with the bundled Python 3.12
against the venv's Python 3.11 native `pydantic_core` extension; recreate/use a matching
3.11 venv first.

## 7. Open questions for the user

1. **Global trains are intentionally disabled** — no Navitia signup or replacement
   token.
2. **India trains are intentionally disabled** — no RapidAPI subscription; keep
   `train_lookup()` static and unavailable.
3. Duffel is **test mode with AUD pricing**. Fine for dev; needs a live key + currency
   handling before anything user-facing.
4. Google Maps key has **no billing enabled** → keep Places-New search and drive-only
   routing; no Geocoding API, transit routing, or billing changes.

## 10. Codex continuation notes (2026-07-29)

The Claude Code frontend/backend connection was preserved. This session completed the
next priorities in order:

- `frountend/src/components/dashboard/Dashboard.tsx` now has a tolerant `trip_state`
  adapter. Flights, Hotels, and Weather use live arrays/objects when present and fall
  back to the existing demo data when the backend has no result for that category.
  Ten hardcoded flight options are now available for the demo route explorer.
- `maplibre-gl` was installed locally in `frountend/node_modules`. The Map tab now uses
  MapLibre GL JS with the public demo style and a GeoJSON source/layer. It fetches
  `GET /session/{id}/state` when needed and shows an honest empty-route state until a
  route is available; no map subscription or billing change was made.
- `Backend/app/memory/models.py` now includes an optional `TripState.route` field,
  excluded from the compact LLM context. `Backend/app/agent/orchestrator.py` stores the
  latest successful `maps_route` GeoJSON FeatureCollection in that field so the frontend
  can render the same session route.
- `Backend/app/agent/orchestrator.py` now passes bounded deterministic tool results to
  the `synthesis` role after tool rounds. The synthesis schema returns a ranked message
  plus selected plan items; selected items and route GeoJSON are persisted. If synthesis
  fails or returns invalid output, the orchestrator response is retained as a safe
  fallback.
- `Backend/app/rag/corpus.py` adds a small local curated seed guide. `Backend/app/rag/retrieval.py`
  implements lazy persistent Chroma storage, all-MiniLM-L6-v2 embeddings, BM25 lexical
  scoring, destination filtering, and weighted hybrid ranking behind the existing
  `knowledge_lookup` tool. No external RAG service was added.

Validation for this session:

- `frountend/npm.cmd run build` passes after the MapLibre integration. Vite reports only
  the expected large-bundle warning from MapLibre.
- Backend source passes compile-only validation with the bundled Python 3.12 runtime.
- The checked-in `Backend/.venv` still points to the missing Python 3.11 installation,
  so backend pytest/uvicorn must use a recreated matching Python 3.11 venv before live
  API validation.
- Browser smoke test verified landing → loader → dashboard fallback, expanded Flights,
  MapLibre empty-route state, and the static Trains coming-soon tab.

## 11. Codex verification (2026-07-30)

The repository was checked against the requested continuation point. Step 7 (RAG) is
already implemented: `Backend/app/rag/retrieval.py` provides lazy persistent Chroma
storage, `sentence-transformers/all-MiniLM-L6-v2` embeddings, BM25 lexical scoring,
destination filtering, and weighted hybrid ranking; `knowledge_lookup` exposes it to
the orchestrator. The local seed corpus is in `Backend/app/rag/corpus.py` and the
dependencies are pinned in `Backend/requirements.txt`.

The earlier priorities are also present in the working tree: `Dashboard.tsx` adapts
live flight/hotel/weather state with demo fallback, MapLibre consumes session route
GeoJSON, and the orchestrator sends deterministic tool results through synthesis.
Trains remain disabled and no provider keys, billing, or legacy Google Maps APIs were
changed.

Validation completed this session:

- `frountend/npm.cmd run build` passes with the existing local dependencies; Vite emits
  only the expected large MapLibre bundle warning.
- Live backend pytest/uvicorn validation remains blocked by the checked-in
  `Backend/.venv`, whose Python launcher points to the removed Python 3.11 install.
  No global packages were installed or changed.

## 12. Python 3.13.7 environment update (2026-07-30)

The current environment supersedes the earlier stale Python 3.11 handoff note.
`Backend/.venv` was replaced with a fresh virtual environment created by
`C:\Users\Nakul\AppData\Local\Programs\Python\Python313\python.exe` (Python 3.13.7).
The pinned `Backend/requirements.txt` dependencies were installed into that project
venv only; no global packages were changed.

Validation after the update:

- Core imports for FastAPI, Pydantic, ChromaDB, sentence-transformers, and rank-bm25
  pass.
- `Backend/.venv/Scripts/python.exe -m pytest -q` passes: 5 tests passed.
- FastAPI imports successfully and reports `TripAI Backend`.
