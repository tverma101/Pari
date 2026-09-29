# Pari Paraphrase API

A minimal, dependency-free HTTP shim that makes the local **FreeLLMAPI** router
(`/Applications/FreeLLMAPI.app`, OpenAI-compatible, `127.0.0.1:31415`) directly
usable for **cloud paraphrasing** — pure LLM in/out, model selectable per
request. No Pari engine code, no local model, no gates.

## Run

```bash
# 1. FreeLLMAPI app running in the background (menu-bar app)
open --background /Applications/FreeLLMAPI.app

# 2. Start the API (router key from the FreeLLMAPI dashboard/db, never committed)
PARI_FREELLM_API_KEY=<key> npm run paraphrase:api
```

Optional env: `PARI_FREELLM_BASE_URL` (default `http://127.0.0.1:31415/v1`),
`PARI_PARAPHRASE_MODEL` (default `llama-3.3-70b-fp8-fast`),
`PARI_PARAPHRASE_PORT` (default `31416`),
`PARI_PARAPHRASE_TIMEOUT_MS` (default `120000`),
`PARI_PARAPHRASE_TOKEN` (when set, all requests need `Authorization: Bearer <token>`).

## Endpoints

- `GET /health` — service + router reachability + default model.
- `GET /models` — live model catalog from the router (pick ids from here).
- `POST /paraphrase`:

```bash
curl -s http://127.0.0.1:31416/paraphrase \
  -H 'Content-Type: application/json' \
  -d '{"text":"Its important to note that the plan changed due to the fact that the deadline was moved.",
       "model":"llama-3.3-70b-fp8-fast","strength":"balanced"}'
```

```json
{ "ok": true, "text": "...", "model": "llama-3.3-70b-fp8-fast",
  "served_model": "...", "usage": {...}, "duration_ms": 612 }
```

Body fields: `text` (required, ≤20k chars), `model?`, `strength?`
(`light|balanced|strong`, default `balanced`), `instructions?` (extra editor
guidance, ≤2000 chars), `max_tokens?` (96–1024, default 512).

## Exposing to ChatGPT

The API binds to `127.0.0.1` only. To let ChatGPT reach it, use the same
cloudflared quick-tunnel pattern as the other local services:

```bash
cloudflared tunnel --url http://127.0.0.1:31416
```

Then set `PARI_PARAPHRASE_TOKEN` and share that token out-of-band — never
tunnel an unauthenticated instance.

## Errors

Router down → `502 {"error":"router_unreachable"}`; router slow → `504
router_timeout`; upstream error → `502 router_error` (status + first 500
chars); bad input → `400 invalid_request`. No response is ever invented
locally.
