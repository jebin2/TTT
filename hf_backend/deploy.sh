#!/usr/bin/env bash
set -euo pipefail

APP_NAME="ttt-backend"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 7861, NOT 7860. 7860 is the Hugging Face default, which this app and
# youtube-downloader both inherited — see the port list below.
PORT="${PORT:-7861}"
DOMAIN="${DOMAIN:-ttt.voidall.com}"
PYENV_ENV="${PYENV_ENV:-TTT_env}"
PYTHON="$HOME/.pyenv/versions/$PYENV_ENV/bin/python"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; exit 1; }
step()  { echo -e "\n${BLUE}──${NC} $*"; }

echo ""
echo "  TTT Runner backend — VPS deploy (FastAPI, single origin, Cloudflare Tunnel)"
echo "  ─────────────────────────────────────────────────────────────────────────────"

# ── Port and route safety ─────────────────────────────────────────────────────
# Ports on this VPS. Keep this list in step across all three deploy scripts —
# every one of them refuses to start on a port another app already holds.
#
#   3000  FundsFlee          (fundsflee.voidall.com)
#   7860  youtube-downloader (yt.voidall.com)
#   7861  TTT hf_backend     (ttt.voidall.com)   ← this one

port_holder() {
  ss -ltnp 2>/dev/null | awk -v p=":$1\$" '$4 ~ p {print $NF; exit}'
}

# Refuse to take a port that belongs to something else. pm2 delete + pm2 start
# would otherwise "succeed" and leave this app crash-looping on EADDRINUSE.
assert_port_available() {
  local port="$1" me="$2" holder mypid other
  holder=$(port_holder "$port")
  [ -z "$holder" ] && { info "Port $port is free"; return 0; }

  mypid=$(pm2 pid "$me" 2>/dev/null || true)
  if [ -n "$mypid" ] && printf '%s' "$holder" | grep -q "pid=$mypid"; then
    info "Port $port held by this app's current process — it will be replaced"
    return 0
  fi

  other=$(pm2 jlist 2>/dev/null | python3 -c "
import json, sys
try: procs = json.load(sys.stdin)
except Exception: procs = []
print(' '.join(p['name'] for p in procs if p.get('name') != '$me'
                and p.get('pm2_env', {}).get('status') == 'online'))
" 2>/dev/null || true)

  error "Port $port is already in use by: $holder
  Starting '$me' here would crash-loop on EADDRINUSE, so this stops now.
  Other PM2 apps online: ${other:-none}
  Free the port, or pick another:  PORT=<free-port> bash deploy.sh"
}

# The tunnel rule must say exactly what we think it says. A bare
# `grep -q "$DOMAIN"` passes even when the hostname points at a DIFFERENT port,
# which is the silent failure: the deploy reports success and the tunnel keeps
# serving whatever used to own that port.
check_tunnel_route() {
  python3 - "$1" "$2" "$3" <<'PYEOF'
import re, sys
config, domain, port = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(config).read()
rules = re.findall(r"-\s*hostname:\s*(\S+)\s*\n\s*service:\s*(\S+)", text)
ours = [svc for host, svc in rules if host == domain]
theirs = [host for host, svc in rules if host != domain and svc.endswith(f":{port}")]
if theirs:
    print(f"CLASH {' '.join(theirs)}")
elif not ours:
    print("MISSING")
elif any(svc.endswith(f":{port}") for svc in ours):
    print("OK")
else:
    print(f"WRONGPORT {ours[0]}")
PYEOF
}

step "Port"
command -v ss >/dev/null 2>&1 || warn "'ss' not found (install iproute2) — cannot verify the port is free."
command -v pm2 >/dev/null 2>&1 && assert_port_available "$PORT" "$APP_NAME" || true

# ── 1. PM2 ────────────────────────────────────────────────────────────────────
step "PM2"
if ! command -v pm2 &>/dev/null; then
  warn "PM2 not found — installing..."
  npm install -g pm2 2>/dev/null || sudo npm install -g pm2
  assert_port_available "$PORT" "$APP_NAME"
fi
info "PM2 $(pm2 --version 2>/dev/null)"

# ── 2. Python environment (pyenv-virtualenv) ──────────────────────────────────
step "Python env ($PYENV_ENV)"
if [ ! -x "$PYTHON" ]; then
  error "pyenv env '$PYENV_ENV' not found at $PYTHON.\n\n  Create it once, e.g.:\n    pyenv install 3.12.8   # if needed\n    pyenv virtualenv 3.12.8 $PYENV_ENV\n\n  Then re-run this script."
fi
info "Python $("$PYTHON" --version 2>&1 | awk '{print $2}')"

# ── 3. Environment validation ─────────────────────────────────────────────────
# app/core/config.py loads env through jebin_lib.load_env, which reads
# ~/.env, ~/.envs/.env, ~/.envs/.<project>_env and then <project>/.env — so the
# key may legitimately live in any of them. Same search order here.
step "Environment"
envget() {
  local v="" f line
  for f in "$HOME/.env" "$HOME/.envs/.env" "$HOME/.envs/.$(basename "$APP_DIR")_env" \
           "$APP_DIR/.env" "$APP_DIR/.env.local"; do
    [ -f "$f" ] || continue
    line=$(grep -E "^$1=" "$f" | tail -1 || true)
    [ -n "$line" ] && v=$(printf '%s' "${line#*=}" | sed -E 's/^["'\'']//; s/["'\'']$//')
  done
  printf '%s' "$v"
}

API_KEY="${TTT_API_KEY:-$(envget TTT_API_KEY)}"
if [ -z "$API_KEY" ]; then
  # main.py raises on startup without it, so PM2 would restart-loop forever.
  error "TTT_API_KEY is not set — the app refuses to start without it.\n
  Generate one and put it in ~/.env (or $APP_DIR/.env):
      echo \"TTT_API_KEY=ttt_\$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')\" >> ~/.env
  Every /api/* request must send it in the X-API-Key header.
  FundsFlee reads the same value from its own ttt_api_key setting — they must match."
fi
info "TTT_API_KEY found (${#API_KEY} chars)"
info "Deploying $DOMAIN → localhost:$PORT"

# ── 4. Dependencies ───────────────────────────────────────────────────────────
# Editable: the app runs from this directory (its DB and upload paths are
# relative to the CWD), so the checkout is the source of truth. The install is
# what pulls the git dependencies — custom_logger, jebin_lib, ttt-runner.
step "Dependencies"
"$PYTHON" -m pip install --quiet --upgrade pip
"$PYTHON" -m pip install --quiet --upgrade -e "$APP_DIR"
mkdir -p "$APP_DIR/uploads" "$APP_DIR/temp_dir"
info "Dependencies installed"

# ── 5. Start / restart with PM2 ───────────────────────────────────────────────
# 127.0.0.1, not run.py's 0.0.0.0: behind the tunnel there is no reason to
# accept connections from anywhere but this host.
# ONE worker — the task worker and its SQLite queue are in-process.
step "PM2 process"
pm2 delete "$APP_NAME" 2>/dev/null || true
info "Starting '$APP_NAME' (uvicorn) on 127.0.0.1:$PORT..."
PORT="$PORT" pm2 start "$PYTHON" \
  --name "$APP_NAME" \
  --cwd "$APP_DIR" \
  --interpreter none \
  --time \
  -- -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --workers 1 --no-access-log
pm2 save

STARTUP_CMD=$(pm2 startup 2>&1 | grep "sudo" || true)
if [ -n "$STARTUP_CMD" ]; then
  eval "$STARTUP_CMD" && info "PM2 registered for auto-start on reboot" \
    || warn "Could not register PM2 startup — run manually: $STARTUP_CMD"
fi

# ── 6. Cloudflare Tunnel ──────────────────────────────────────────────────────
step "Cloudflare Tunnel"
CF_CONFIG=""
for candidate in /etc/cloudflared/config.yml /root/.cloudflared/config.yml "$HOME/.cloudflared/config.yml"; do
  [ -f "$candidate" ] && { CF_CONFIG="$candidate"; break; }
done

if [ -z "$CF_CONFIG" ]; then
  warn "cloudflared config not found. Ensure this ingress rule exists:"
  echo "    - hostname: $DOMAIN"
  echo "      service: http://localhost:$PORT"
else
  ROUTE=$(check_tunnel_route "$CF_CONFIG" "$DOMAIN" "$PORT")
  case "$ROUTE" in
    OK)
      info "$DOMAIN → localhost:$PORT already routed — no change needed" ;;
    CLASH*)
      error "Port $PORT is already routed to ${ROUTE#CLASH } in $CF_CONFIG.
  Adding $DOMAIN on the same port would give two hostnames one app.
  Pick a free port:  PORT=<free-port> bash deploy.sh" ;;
    WRONGPORT*)
      error "$DOMAIN is routed to ${ROUTE#WRONGPORT } in $CF_CONFIG, not port $PORT.
  This deploy would look successful while the tunnel kept serving the old app.
  Fix the rule by hand, or deploy on that port:  PORT=<that-port> bash deploy.sh" ;;
    MISSING)
      sudo cp "$CF_CONFIG" "${CF_CONFIG}.bak"
      sudo python3 - "$CF_CONFIG" "$DOMAIN" "$PORT" <<'PYEOF'
import sys, re
config_path, domain, port = sys.argv[1], sys.argv[2], sys.argv[3]
new_rule = f"  - hostname: {domain}\n    service: http://localhost:{port}\n"
content = open(config_path).read()
m = re.search(r'^(\s*- service:\s*http_status:\d+\s*)$', content, re.MULTILINE)
content = (content[:m.start()] + new_rule + content[m.start():]) if m else (content.rstrip() + "\n" + new_rule)
open(config_path, 'w').write(content)
print("Config updated.")
PYEOF
      info "Added $DOMAIN → localhost:$PORT (existing rules untouched; backup at ${CF_CONFIG}.bak)"
      systemctl is-active --quiet cloudflared 2>/dev/null && sudo systemctl restart cloudflared && info "cloudflared restarted" \
        || warn "Restart cloudflared manually: sudo systemctl restart cloudflared"
      warn "Ensure DNS for $DOMAIN points at this tunnel:"
      echo "    cloudflared tunnel route dns <TUNNEL_NAME> $DOMAIN" ;;
  esac
fi

# ── 7. Verify it actually came up ─────────────────────────────────────────────
step "Health"
sleep 2
if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; then
  info "Responding on 127.0.0.1:$PORT"
else
  warn "No response yet on 127.0.0.1:$PORT — check: pm2 logs $APP_NAME --lines 50"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "  ─────────────────────────────────────────"
info "Done!"
echo ""
echo "  FastAPI on 127.0.0.1:$PORT"
echo "  Tunnel:  https://$DOMAIN"
echo ""
echo "  Useful commands:"
echo "    pm2 logs $APP_NAME        — live logs"
echo "    pm2 restart $APP_NAME     — restart"
echo "    pm2 status                — process status"
echo ""
echo "  To update: git pull && bash deploy.sh"
echo ""
