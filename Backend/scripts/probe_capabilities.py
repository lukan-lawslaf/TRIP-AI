"""Probe NIM/Groq chat + native JSON-schema structured output."""
import json, pathlib, urllib.request, urllib.error

root = pathlib.Path(__file__).resolve().parent.parent.parent
env = {}
for line in (root / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")


def post(url, payload, key, label):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            b = json.loads(r.read().decode("utf-8", "replace"))
            msg = ((b.get("choices") or [{}])[0].get("message") or {})
            print(f"[{label}] HTTP {r.status} model={b.get('model')} "
                  f"content={(msg.get('content') or '')[:120]!r} "
                  f"tool_calls={bool(msg.get('tool_calls'))}")
            return True
    except urllib.error.HTTPError as e:
        print(f"[{label}] HTTP {e.code} {e.read()[:400].decode('utf-8','replace')}")
    except Exception as e:
        print(f"[{label}] ERR {type(e).__name__}: {str(e)[:200]}")
    return False


NIM, GROQ, ORK = env.get("NVIDIA_NIM_API_KEY",""), env.get("GROQ_API_KEY",""), env.get("OPEN_ROUTER_API_KEY","")

# synthesis primary on NIM direct
post("https://integrate.api.nvidia.com/v1/chat/completions", {
    "model": "nvidia/nemotron-3-super-120b-a12b",
    "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
    "max_tokens": 4000,
}, NIM, "NIM nemotron-3-super")

SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}, "nights": {"type": "integer"}},
    "required": ["city", "nights"],
    "additionalProperties": False,
}

# native json_schema mode on groq (memory/field_extractor role)
post("https://api.groq.com/openai/v1/chat/completions", {
    "model": "llama-3.1-8b-instant",
    "messages": [{"role": "user", "content": "Trip: 3 nights in Kyoto. Extract fields."}],
    "max_tokens": 300,
    "response_format": {"type": "json_schema", "json_schema": {"name": "trip", "strict": True, "schema": SCHEMA}},
}, GROQ, "GROQ json_schema")

# tool calling through the orchestrator candidate
TOOL = [{"type": "function", "function": {
    "name": "flight_lookup", "description": "Search flights",
    "parameters": {"type": "object", "properties": {
        "origin": {"type": "string"}, "destination": {"type": "string"},
        "departure_date": {"type": "string"}}, "required": ["origin", "destination", "departure_date"]}}}]

post("https://openrouter.ai/api/v1/chat/completions", {
    "model": "google/gemma-4-31b-it:free",
    "messages": [{"role": "user", "content": "Find me a flight SFO to JFK on 2026-08-20. Use the tool."}],
    "max_tokens": 500, "tools": TOOL,
    "provider": {"order": ["google-ai-studio"], "allow_fallbacks": False},
}, ORK, "OR gemma-4-31b tool_call")

# json_schema on the NIM synthesis primary
post("https://integrate.api.nvidia.com/v1/chat/completions", {
    "model": "nvidia/nemotron-3-super-120b-a12b",
    "messages": [{"role": "user", "content": "Trip: 3 nights in Kyoto. Extract fields."}],
    "max_tokens": 4000,
    "response_format": {"type": "json_schema", "json_schema": {"name": "trip", "strict": True, "schema": SCHEMA}},
}, NIM, "NIM json_schema")
