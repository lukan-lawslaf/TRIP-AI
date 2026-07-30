"""Probe live provider routes. Prints status only, never key material."""
import json, os, sys, pathlib, urllib.request, urllib.error

root = pathlib.Path(__file__).resolve().parent.parent.parent
env = {}
for line in (root / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    env[k.strip()] = v.strip().strip('"').strip("'")

print("env keys loaded:", len(env))
print("has GOOGLE/GEMINI key:", any(k in env for k in ("GOOGLE_API_KEY", "GEMINI_API_KEY")))


def post(url, payload, headers, label):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers}
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
            ch = (body.get("choices") or [{}])[0]
            msg = (ch.get("message") or {}).get("content", "")
            print(f"[{label}] HTTP {r.status} model={body.get('model')} "
                  f"provider={body.get('provider')} reply={(msg or '')[:60]!r}")
            return True
    except urllib.error.HTTPError as e:
        print(f"[{label}] HTTP {e.code} {e.read()[:300].decode('utf-8','replace')}")
    except Exception as e:
        print(f"[{label}] ERR {type(e).__name__}: {str(e)[:200]}")
    return False


ORK = env.get("OPEN_ROUTER_API_KEY", "")
orh = {"Authorization": f"Bearer {ORK}", "HTTP-Referer": "https://local/tripai", "X-Title": "TripAI"}

# 1. orchestrator primary: gemma 4 31b pinned to google-ai-studio upstream
post("https://openrouter.ai/api/v1/chat/completions", {
    "model": "google/gemma-4-31b-it:free",
    "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
    "max_tokens": 20,
    "provider": {"order": ["google-ai-studio"], "allow_fallbacks": False},
}, orh, "OR gemma-4-31b @google-ai-studio")

# 2. orchestrator fallback: gemma 4 26b a4b pinned to darkbloom
post("https://openrouter.ai/api/v1/chat/completions", {
    "model": "google/gemma-4-26b-a4b-it:free",
    "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
    "max_tokens": 20,
    "provider": {"order": ["darkbloom"], "allow_fallbacks": False},
}, orh, "OR gemma-4-26b @darkbloom")

# 3. synthesis fallback: nemotron 3 ultra free
post("https://openrouter.ai/api/v1/chat/completions", {
    "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
    "max_tokens": 20,
}, orh, "OR nemotron-3-ultra:free")

# 4. NVIDIA NIM direct
NIM = env.get("NVIDIA_NIM_API_KEY", "")
try:
    req = urllib.request.Request(
        "https://integrate.api.nvidia.com/v1/models", headers={"Authorization": f"Bearer {NIM}"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        ids = sorted(m["id"] for m in json.loads(r.read().decode("utf-8", "replace")).get("data", []))
    print(f"[NIM models] count={len(ids)}")
    for i in ids:
        if "nemotron" in i and ("super" in i or "ultra" in i or "3" in i):
            print("   ", i)
except Exception as e:
    print("[NIM models] ERR", type(e).__name__, str(e)[:200])
