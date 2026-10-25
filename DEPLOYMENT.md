# Trip AI deployment

Public website: https://trip-ai-lyart-theta.vercel.app

## Hosting

- Frontend: Vercel Hobby, project `trip-ai`, ID `prj_SajK3BVmFEJWYm7G3bXo9rDK6gzq`.
- Vercel account scope: `nakulf2007-2371s-projects`.
- Frontend root: `frountend`; install `npm ci`; build `npm run build`; output `dist`.
- Backend: Render Free in Singapore, workspace `Trip AI` (`tea-dbf2vt4s728c73du5cj0`).
- Service: `trip-ai-api` (`srv-dbf343vb9u1s73bf06c0`).
- Backend origin: https://trip-ai-api.onrender.com
- Backend build: `pip install -r Backend/requirements-runtime.txt`.
- Backend start: `cd Backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`.
- Python: 3.13.7. Health path: `/health`.

## Temporary storage and runtime

The user selected temporary trip history. SQLite is created automatically in the
backend's ephemeral filesystem. Saved trips, chat history and caches can disappear
when Render sleeps, restarts, or redeploys. No local user database was exported.
No Supabase project was created or changed, and Birdy was left untouched.

Render uses `RAG_MODE=lexical` to search the bundled curated guides with BM25 rather
than loading Chroma and a local PyTorch embedding model on the 512 MB free instance.
Local development retains the default hybrid retrieval implementation.
The backend uses an in-process cache and one worker.

AI and travel-provider keys are held only in Render environment settings. Train
providers remain disabled. Local `.env` files must never be uploaded or committed.

## Routing and releases

The frontend uses relative `/api` requests. `frountend/vercel.json` strips `/api`
and proxies to Render before the SPA fallback. A health GET wakes the backend
before creating a session; only this GET is retried. The first request after sleep
may take about a minute before planning begins.

Messages are submitted once to `/session/{id}/message/start`, which returns a job
ID immediately. The frontend polls `/session/{id}/message/status/{job_id}` for up
to ten minutes. This avoids Vercel's external-target timeout for long itineraries.
Jobs are temporary, limited to 64 retained requests, and completed results expire
after 15 minutes when the next request prunes them. Backend restarts interrupt jobs.
The orchestrator also has an `openrouter/free` fallback for provider outages or
retired model IDs; it uses the existing OpenRouter credential.

Deployment source is branch `codex/deploy-trip-ai`; `main` was not changed.
Render is configured to deploy updates to this branch automatically.
Vercel Git integration is not connected; pushing does not update the frontend.
The frontend was uploaded using the Vercel CLI.

The local `.deployment-staging/` folder contains an upload copy with only the
tracked frontend sources, `frountend/vercel.json`, `.vercelignore`, and the verified
`.vercel/project.json` link. Upload from that folder so the remote `frountend` root
exists. This avoids an inaccessible OneDrive `.pytest_cache` folder in the checkout.
Refresh the upload copy before future frontend releases.

## Verification

- Eight backend tests pass, including guide retrieval, background planning,
  session isolation, single execution, and terminal failure reporting.
- Vercel production build completed successfully.
- Anonymous website, direct `/trip` SPA path, `/api/health`, and hero video return 200.
- Session creation and subsequent state retrieval work through the website's `/api` proxy.
- Final browser verification completed a two-day Kyoto itinerary through the
  background-job flow and displayed the AI reply in the dashboard. The free
  OpenRouter fallback succeeded after the primary Google provider failed.
- AI-provider outages and free-tier rate limits can delay or interrupt planning;
  successful hosting does not guarantee upstream provider availability.

## Background compatibility fix

The original hero MP4 uses HEVC Main 10 at 3840x2160, which failed in the user's
Firefox environment. The landing page now offers 1920x1080 VP9 WebM first and
8-bit H.264 MP4 second, both without audio. A matching JPEG sits behind the video
and is also its poster so the artwork remains available when playback is blocked.
The original source file is retained for future re-encoding.

The production build passed. An isolated Firefox 155 check confirmed that the
deployed WebM selected successfully, had nonzero video dimensions, advanced its
playback time, and was not paused. A screenshot verified the background visually.
The additional blocked-video automation did not complete; its result is unverified.
