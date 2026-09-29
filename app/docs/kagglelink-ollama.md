# KaggleLink + Ollama

This is an explicit, opt-in Pari backend for using an Ollama model on a
Kaggle GPU notebook through a private SSH tunnel. Pari keeps its existing
Qwen/MLX path and deterministic fallback unchanged unless the Ollama route is
enabled in the launching shell.

## Local bootstrap

From the production checkout:

```bash
cd /Users/tejas/Projects/Pari/app
./scripts/kagglelink_ollama.sh setup
```

The helper installs the official zrok `v1.1.11` client under:

```text
~/Library/Application Support/Open Local Phraser/KaggleLink/bin/zrok
```

It also creates a dedicated `~/.ssh/kaggle_rsa` key if one does not already
exist. The private key stays local; only the matching `.pub` file is hosted at
a URL that Kaggle can fetch. The helper never prints the private key or stores
a zrok token in the repository.

The Mac currently has another Ollama listener on `127.0.0.1:11434`, so the
helper forwards Kaggle's remote Ollama port `11434` to local port `11435` by
default. This preserves the existing local service.

## Kaggle-side setup

The original `bhdai/kagglelink` URL in the research note currently returns
404. The helper therefore prints a pinned community mirror setup cell from
`ai-jubied/KaggleLink-Setup` at commit
`cd18f302a6f44cf83e3ac08a3597bbebbc00abd7`. Review that repository before
running it in Kaggle; it is not a Pari dependency and is not executed by the
Mac helper.

In a Kaggle notebook:

1. Turn Internet on and select a GPU accelerator.
2. Add `KAGGLELINK_TOKEN` and `KAGGLELINK_KEYS_URL` as Kaggle Secrets. The
   latter must resolve to the raw public key file generated above.
3. Run the KaggleLink cell printed by `./scripts/kagglelink_ollama.sh
   print-kaggle-cell`.
4. Install Ollama, start it on loopback, pull the model you want, and verify
   `http://127.0.0.1:11434/api/tags`. The printed cell includes placeholders
   for these commands; replace `<ollama-model>` with a model present in the
   notebook's Ollama catalog.

The KaggleLink setup prints the reserved share name or private access token.
Do not paste that value into this repository.

## Local connection

Enable the pinned client once with your zrok account token. Enter it directly
in the terminal; do not put it in a shell history file or project document:

```bash
ZROK="$HOME/Library/Application Support/Open Local Phraser/KaggleLink/bin/zrok"
"$ZROK" enable <your-zrok-account-token>
```

Then keep this command running in a terminal for the lifetime of the Kaggle
session:

```bash
cd /Users/tejas/Projects/Pari/app
PARI_KAGGLELINK_SHARE=<reserved-name-or-private-token> \
  ./scripts/kagglelink_ollama.sh start
```

The command starts private zrok access on `127.0.0.1:9191`, authenticates to
the Kaggle SSH server with the dedicated key, and holds the SSH port forward:

```text
127.0.0.1:11435 -> Kaggle 127.0.0.1:11434 -> Ollama -> Kaggle GPU
```

In a second terminal, verify the remote model list:

```bash
./scripts/kagglelink_ollama.sh health
```

## Run Pari through the tunnel

Choose a model name from the `health` output, then build and launch the
explicit route:

```bash
export PARI_OLLAMA_MODEL='<model-from-health>'
npm run build:desktop
npm run run:ollama
```

The same route can be exercised without opening a visible window:

```bash
PARI_OLLAMA_MODEL='<model-from-health>' npm run qa:installed:ollama
```

The packaged app sends one remote candidate per generation and applies Pari's
existing protected-content, meaning, grammar, and flow checks. A failed
tunnel, missing model, timeout, or rejected draft falls back to the existing
`local-safe-engine`; the route does not become an implicit default.

## Useful commands

```bash
./scripts/kagglelink_ollama.sh status
./scripts/kagglelink_ollama.sh env
curl http://127.0.0.1:11435/v1/models
```

To use local port `11434` instead, stop the existing local Ollama listener and
set `PARI_OLLAMA_LOCAL_PORT=11434` consistently for `start`, `health`, and the
Pari launch. The default `11435` is safer because it does not alter that
existing service.

## Boundaries

- Implemented locally: zrok client bootstrap, dedicated key generation,
  private access/SSH port forwarding, packaged Ollama worker, and explicit Pari
  backend selection.
- Requires user action: zrok account token, public hosting of the public key,
  Kaggle notebook execution, Kaggle Secrets, and the remote model choice.
- Not used: public ngrok URLs, a public Ollama endpoint, automatic model
  promotion, or GitHub publication.

References: [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility),
[zrok v1.1.11 release](https://github.com/openziti/zrok/releases/tag/v1.1.11),
[KaggleLink mirror](https://github.com/ai-jubied/KaggleLink-Setup/tree/cd18f302a6f44cf83e3ac08a3597bbebbc00abd7).
