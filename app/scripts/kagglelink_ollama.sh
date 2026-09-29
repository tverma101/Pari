#!/usr/bin/env bash
set -euo pipefail

# Local half of the KaggleLink -> Ollama connection.  It deliberately keeps
# the existing local Ollama service on 11434 untouched and forwards the remote
# service to 11435 by default.

MODE="${1:-setup}"
ZROK_VERSION="v1.1.11"
ZROK_RELEASE_BASE="https://github.com/openziti/zrok/releases/download/${ZROK_VERSION}"
MIRROR_COMMIT="cd18f302a6f44cf83e3ac08a3597bbebbc00abd7"
APP_SUPPORT_DIR="${PARI_KAGGLELINK_HOME:-$HOME/Library/Application Support/Open Local Phraser/KaggleLink}"
BIN_DIR="$APP_SUPPORT_DIR/bin"
LOG_DIR="$APP_SUPPORT_DIR/logs"
ZROK_BIN="${PARI_KAGGLELINK_ZROK_BIN:-$BIN_DIR/zrok}"
IDENTITY_FILE="${PARI_KAGGLELINK_IDENTITY:-$HOME/.ssh/kaggle_rsa}"
SSH_LOCAL_PORT="${PARI_KAGGLELINK_SSH_PORT:-9191}"
OLLAMA_LOCAL_PORT="${PARI_OLLAMA_LOCAL_PORT:-11435}"
REMOTE_OLLAMA_PORT="${PARI_OLLAMA_REMOTE_PORT:-11434}"
SHARE_TOKEN="${PARI_KAGGLELINK_SHARE:-}"
ACCESS_PID=""

usage() {
  cat <<'EOF'
Usage: ./scripts/kagglelink_ollama.sh <mode>

Modes:
  setup          Install pinned zrok v1.1.11, create the dedicated SSH key,
                 and print the Kaggle-side setup cell (default).
  install-zrok   Install or verify the official zrok v1.1.11 client locally.
  generate-key   Create ~/.ssh/kaggle_rsa if it does not exist.
  print-kaggle-cell
                 Print the KaggleLink and Ollama cells with placeholders.
  start          Start private zrok access and the SSH Ollama port forward.
  access         Start only zrok access on 127.0.0.1:9191.
  forward        Start only the SSH port forward (zrok access must be open).
  health         Query the forwarded Ollama /api/tags endpoint.
  status         Show non-secret local tool, key, and listener state.
  env            Print the shell exports used to run Pari through the tunnel.

Environment overrides:
  PARI_KAGGLELINK_SHARE       Reserved name or private access token.
  PARI_KAGGLELINK_IDENTITY    SSH private key path.
  PARI_KAGGLELINK_SSH_PORT    Local zrok/SSH port (default 9191).
  PARI_OLLAMA_LOCAL_PORT      Local Ollama port (default 11435).
  PARI_OLLAMA_REMOTE_PORT     Remote Ollama port (default 11434).
EOF
}

die() {
  echo "kagglelink-ollama: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

ensure_macos() {
  [[ "$(uname -s)" == "Darwin" ]] || die "this local helper currently supports macOS only"
}

install_zrok() {
  ensure_macos
  require_command curl
  require_command shasum
  require_command tar
  require_command uname
  mkdir -p "$BIN_DIR"
  chmod 700 "$APP_SUPPORT_DIR" "$BIN_DIR"

  if [[ -x "$ZROK_BIN" ]] && "$ZROK_BIN" version 2>/dev/null | grep -q "v${ZROK_VERSION#v}"; then
    echo "zrok $ZROK_VERSION is ready at $ZROK_BIN"
    return
  fi

  local asset expected temp_dir archive extracted
  case "$(uname -m)" in
    arm64|aarch64)
      asset="zrok_${ZROK_VERSION#v}_darwin_arm64.tar.gz"
      expected="074ac05b235f22d88eff81168a7b5a11f1b79e975f00f98fd57fc2b81baba440"
      ;;
    x86_64|amd64)
      asset="zrok_${ZROK_VERSION#v}_darwin_amd64.tar.gz"
      expected="3bcfee63b4b7b654eb202d5090a3e0f6a3a681edcf1593137db43b094cd61b64"
      ;;
    *) die "unsupported macOS architecture: $(uname -m)" ;;
  esac

  temp_dir="$(mktemp -d -t pari-zrok-install)"
  cleanup_temp() {
    find "$temp_dir" -depth -delete 2>/dev/null || true
    trap - RETURN
  }
  trap cleanup_temp RETURN
  archive="$temp_dir/$asset"
  echo "Downloading official zrok $ZROK_VERSION for $(uname -m)..."
  curl -fsSL --max-time 120 -o "$archive" "$ZROK_RELEASE_BASE/$asset"
  printf '%s  %s\n' "$expected" "$archive" | shasum -a 256 -c -
  tar -xzf "$archive" -C "$temp_dir"
  extracted="$(find "$temp_dir" -type f -name zrok -perm -111 -print -quit)"
  [[ -n "$extracted" ]] || die "zrok binary was not found in the verified archive"
  install -m 0755 "$extracted" "$ZROK_BIN"
  "$ZROK_BIN" version 2>&1 | grep -m 1 -E '^v[0-9]' || true
  echo "Installed zrok at $ZROK_BIN"
}

generate_key() {
  require_command ssh-keygen
  mkdir -p "$(dirname "$IDENTITY_FILE")"
  chmod 700 "$(dirname "$IDENTITY_FILE")"
  if [[ ! -e "$IDENTITY_FILE" ]]; then
    echo "Generating dedicated KaggleLink SSH key at $IDENTITY_FILE"
    ssh-keygen -t ed25519 -C "pari-kagglelink" -f "$IDENTITY_FILE" -N "" >/dev/null
  elif [[ ! -f "$IDENTITY_FILE" ]]; then
    die "identity path exists but is not a regular file: $IDENTITY_FILE"
  else
    echo "Keeping existing SSH key at $IDENTITY_FILE"
  fi
  [[ -f "$IDENTITY_FILE.pub" ]] || die "matching public key is missing: $IDENTITY_FILE.pub"
  chmod 600 "$IDENTITY_FILE"
  chmod 644 "$IDENTITY_FILE.pub"
  echo "Public key file to host for Kaggle: $IDENTITY_FILE.pub"
}

print_kaggle_cell() {
  cat <<EOF
# Kaggle notebook prerequisites: enable Internet and select a GPU accelerator.
# Use Kaggle Secrets for KAGGLELINK_TOKEN and optionally KAGGLELINK_KEYS_URL.

from kaggle_secrets import UserSecretsClient
secrets = UserSecretsClient()
KAGGLELINK_TOKEN = secrets.get_secret("KAGGLELINK_TOKEN")
KAGGLELINK_KEYS_URL = secrets.get_secret("KAGGLELINK_KEYS_URL")

!curl -fsSL https://raw.githubusercontent.com/ai-jubied/KaggleLink-Setup/${MIRROR_COMMIT}/setup.sh \\
  | bash -s -- -k "\$KAGGLELINK_KEYS_URL" -t "\$KAGGLELINK_TOKEN"

# After KaggleLink reports that the private share is up, install and start
# Ollama on the Kaggle VM. Replace <ollama-model> with the model you choose.
!curl -fsSL https://ollama.com/install.sh | sh
import os
os.environ["OLLAMA_HOST"] = "127.0.0.1:11434"
!nohup ollama serve >/kaggle/working/ollama.log 2>&1 &
!sleep 5
!ollama pull <ollama-model>
!curl -fsS http://127.0.0.1:11434/api/tags

# The setup output prints the share name/token. On this Mac, use:
#   PARI_KAGGLELINK_SHARE=<printed-share> ./scripts/kagglelink_ollama.sh start
EOF
}

zrok_status_is_enabled() {
  local output
  output="$("$ZROK_BIN" status 2>&1 || true)"
  ! printf '%s\n' "$output" | grep -q "To create a local environment"
}

ensure_zrok_enabled() {
  [[ -x "$ZROK_BIN" ]] || die "zrok is not installed; run '$0 install-zrok'"
  if ! zrok_status_is_enabled; then
    die "zrok is not enabled; run '$ZROK_BIN enable <your-zrok-account-token>' once"
  fi
}

resolve_share_token() {
  if [[ -n "$SHARE_TOKEN" ]]; then return; fi
  [[ -r /dev/tty ]] || die "set PARI_KAGGLELINK_SHARE to the reserved name or private access token"
  printf 'KaggleLink share name/token: ' >/dev/tty
  IFS= read -r -s SHARE_TOKEN </dev/tty
  printf '\n' >/dev/tty
  [[ -n "$SHARE_TOKEN" ]] || die "share name/token cannot be empty"
}

port_is_listening() {
  require_command lsof
  lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR > 1 { found = 1 } END { exit found ? 0 : 1 }'
}

wait_for_port() {
  require_command nc
  local port="$1"
  for _ in $(seq 1 30); do
    if nc -z 127.0.0.1 "$port" >/dev/null 2>&1; then return; fi
    sleep 1
  done
  die "zrok did not open 127.0.0.1:$port; inspect $LOG_DIR/zrok-access.log"
}

start_forward() {
  require_command ssh
  [[ -f "$IDENTITY_FILE" ]] || die "SSH identity missing; run '$0 generate-key'"
  port_is_listening "$SSH_LOCAL_PORT" || die "zrok access is not listening on 127.0.0.1:$SSH_LOCAL_PORT"
  echo "Forwarding Ollama 127.0.0.1:$OLLAMA_LOCAL_PORT -> Kaggle 127.0.0.1:$REMOTE_OLLAMA_PORT"
  local -a ssh_options=(
    -o UserKnownHostsFile=/dev/null
    -o StrictHostKeyChecking=no
    -o ExitOnForwardFailure=yes
    -o ServerAliveInterval=60
    -o ServerAliveCountMax=3
    -i "$IDENTITY_FILE"
    -p "$SSH_LOCAL_PORT"
  )
  ssh "${ssh_options[@]}" -N \
    -L "127.0.0.1:${OLLAMA_LOCAL_PORT}:127.0.0.1:${REMOTE_OLLAMA_PORT}" \
    root@127.0.0.1
}

start_all() {
  require_command mkdir
  ensure_zrok_enabled
  generate_key
  resolve_share_token
  if port_is_listening "$SSH_LOCAL_PORT"; then
    die "127.0.0.1:$SSH_LOCAL_PORT is already in use; stop that listener or choose PARI_KAGGLELINK_SSH_PORT"
  fi
  mkdir -p "$LOG_DIR"
  chmod 700 "$LOG_DIR"
  umask 077
  "$ZROK_BIN" access private "$SHARE_TOKEN" \
    --bind "127.0.0.1:${SSH_LOCAL_PORT}" \
    --headless >"$LOG_DIR/zrok-access.log" 2>&1 &
  ACCESS_PID=$!
  cleanup_access() {
    if [[ -n "$ACCESS_PID" ]] && kill -0 "$ACCESS_PID" 2>/dev/null; then
      kill "$ACCESS_PID" 2>/dev/null || true
      wait "$ACCESS_PID" 2>/dev/null || true
    fi
  }
  trap cleanup_access EXIT INT TERM
  wait_for_port "$SSH_LOCAL_PORT"
  start_forward
}

start_access() {
  ensure_zrok_enabled
  resolve_share_token
  mkdir -p "$LOG_DIR"
  chmod 700 "$LOG_DIR"
  umask 077
  exec "$ZROK_BIN" access private "$SHARE_TOKEN" \
    --bind "127.0.0.1:${SSH_LOCAL_PORT}" \
    --headless
}

health() {
  require_command curl
  echo "Ollama through local port $OLLAMA_LOCAL_PORT:"
  curl -fsS --max-time 10 "http://127.0.0.1:${OLLAMA_LOCAL_PORT}/api/tags"
  printf '\n'
}

status() {
  printf 'zrok client: '
  if [[ -x "$ZROK_BIN" ]]; then
    "$ZROK_BIN" version 2>&1 | grep -m 1 -E '^v[0-9]' || echo "installed (version unavailable)"
  else
    echo "not installed"
  fi
  printf 'zrok environment: '
  if [[ -x "$ZROK_BIN" ]] && zrok_status_is_enabled; then echo "enabled"; else echo "not enabled"; fi
  printf 'SSH identity: '
  if [[ -f "$IDENTITY_FILE" && -f "$IDENTITY_FILE.pub" ]]; then echo "$IDENTITY_FILE"; else echo "missing"; fi
  printf 'SSH access listener: '
  if port_is_listening "$SSH_LOCAL_PORT"; then echo "127.0.0.1:$SSH_LOCAL_PORT"; else echo "not listening"; fi
  printf 'Ollama listener: '
  if port_is_listening "$OLLAMA_LOCAL_PORT"; then echo "127.0.0.1:$OLLAMA_LOCAL_PORT"; else echo "not listening"; fi
}

print_env() {
  cat <<EOF
export PARI_GENERATION_BACKEND=ollama
export PARI_OLLAMA_BASE_URL=http://127.0.0.1:${OLLAMA_LOCAL_PORT}/v1
export PARI_OLLAMA_MODEL='<model listed by ./scripts/kagglelink_ollama.sh health>'
EOF
}

case "$MODE" in
  setup)
    install_zrok
    generate_key
    print_kaggle_cell
    ;;
  install-zrok) install_zrok ;;
  generate-key) generate_key ;;
  print-kaggle-cell) print_kaggle_cell ;;
  start) start_all ;;
  access) start_access ;;
  forward) start_forward ;;
  health) health ;;
  status) status ;;
  env) print_env ;;
  -h|--help|help) usage ;;
  *) usage; exit 2 ;;
esac
