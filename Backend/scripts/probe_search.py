"""Probe the newly added keys. Prints status only, never key material."""
import json, pathlib, urllib.request, urllib.error

root = pathlib.Path(__file__).resolve().parent.parent.parent
env = {}
for line in (root / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")


def call(label, url, *, data=None, headers=None, show=None):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data else None,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
            print(f"[{label}] HTTP {r.status}")
            print("   keys:", list(body)[:10])
            if show:
                show(body)
            return body
    except urllib.error.HTTPError as e:
        print(f"[{label}] HTTP {e.code} {e.read()[:250].decode('utf-8','replace')}")
    except Exception as e:
        print(f"[{label}] ERR {type(e).__name__}: {str(e)[:180]}")


# --- Serper (google-like) ---
def show_serper(b):
    org = b.get("organic") or []
    print(f"   organic: {len(org)}")
    if org:
        print("   fields:", list(org[0]))
        print("   e.g.:", json.dumps(org[0], ensure_ascii=False)[:260])
    for extra in ("knowledgeGraph", "answerBox", "places", "topStories"):
        if b.get(extra):
            print(f"   has {extra}")


call(
    "SERPER search",
    "https://google.serper.dev/search",
    data={"q": "best time to visit Kyoto Japan", "num": 5},
    headers={"X-API-KEY": env.get("WEB_SEARCH_API_KEY", "")},
    show=show_serper,
)

call(
    "SERPER places",
    "https://google.serper.dev/places",
    data={"q": "ramen in Kyoto", "num": 3},
    headers={"X-API-KEY": env.get("WEB_SEARCH_API_KEY", "")},
    show=lambda b: print("   places:", len(b.get("places") or []),
                         json.dumps((b.get("places") or [{}])[0], ensure_ascii=False)[:220]),
)


# --- Tavily (summary type) ---
def show_tavily(b):
    res = b.get("results") or []
    print(f"   answer: {str(b.get('answer'))[:180]!r}")
    print(f"   results: {len(res)}")
    if res:
        print("   fields:", list(res[0]))
        print("   e.g.:", json.dumps({k: v for k, v in res[0].items() if k != 'raw_content'}, ensure_ascii=False)[:260])


call(
    "TAVILY search",
    "https://api.tavily.com/search",
    data={
        "query": "Kyoto travel tips temples etiquette",
        "max_results": 5,
        "include_answer": "advanced",
        "search_depth": "basic",
    },
    headers={"Authorization": f"Bearer {env.get('WEB2_SEARCH_API_KEY','')}"},
    show=show_tavily,
)

# --- Google AI Studio direct (new key) ---
gk = env.get("GOOGLE_STUDIO_API_KEY", "")
try:
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": gk},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        models = json.loads(r.read().decode("utf-8", "replace")).get("models", [])
    names = [m["name"].replace("models/", "") for m in models]
    print(f"[GOOGLE AI STUDIO] HTTP 200 models={len(names)}")
    for n in names:
        if "gemma" in n or "2.5-flash" in n or "3" in n:
            print("   ", n)
except urllib.error.HTTPError as e:
    print(f"[GOOGLE AI STUDIO] HTTP {e.code} {e.read()[:250].decode('utf-8','replace')}")
except Exception as e:
    print(f"[GOOGLE AI STUDIO] ERR {type(e).__name__}: {str(e)[:180]}")
