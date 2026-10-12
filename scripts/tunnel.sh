#!/usr/bin/env bash
# PreReads Cloudflare Tunnel: https://prereads.vitbhatti.com -> http://127.0.0.1:${PREREADS_PORT:-8000}
#
#   Tab 1:  python3 scripts/setup.py start
#   Tab 2:  bash scripts/tunnel.sh            run the named tunnel (Ctrl+C to stop)
#           bash scripts/tunnel.sh setup      one-time: create tunnel + DNS record
#           bash scripts/tunnel.sh status     show tunnel connections
#           bash scripts/tunnel.sh quick      no-account quick tunnel, random trycloudflare.com URL
#
# Uses its own tunnel ("prereads"), so it can run alongside other tunnels.
# Only the app port is exposed; Ollama is not.

set -e

TUNNEL_NAME="${PREREADS_TUNNEL:-prereads}"
HOSTNAME="${PREREADS_HOSTNAME:-prereads.vitbhatti.com}"
APP_PORT="${PREREADS_PORT:-8000}"
CF_DIR="$HOME/.cloudflared"

CMD="${1:-run}"
case "$CMD" in
    -h|--help|help)
        sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
esac

if ! command -v cloudflared &> /dev/null; then
    echo "  [FAIL] cloudflared not found. Install: brew install cloudflare/cloudflare/cloudflared"
    exit 1
fi

# ~/.cloudflared/config.yml may pin another tunnel; an empty config stops it overriding ours.
EMPTY_CONFIG="$(mktemp -t pr-empty.XXXXXX.yml)"
RUN_CONFIG="$(mktemp -t pr-tunnel.XXXXXX.yml)"
trap 'rm -f "$EMPTY_CONFIG" "$RUN_CONFIG"' EXIT
echo "{}" > "$EMPTY_CONFIG"
cf() { cloudflared --config "$EMPTY_CONFIG" "$@" 2> >(grep -v "WRN Your version" >&2); }

tunnel_id() {
    cf tunnel list --output json 2>/dev/null \
        | python3 -c "import sys,json;print(next((t['id'] for t in json.load(sys.stdin) if t['name']=='$TUNNEL_NAME'),''))"
}

check_app() {
    if ! curl -s -m 3 "http://127.0.0.1:$APP_PORT/api/health" > /dev/null; then
        echo "  [WARN] Nothing answering on http://127.0.0.1:$APP_PORT/api/health yet — start it: python3 scripts/setup.py start"
    fi
}

case "$CMD" in
    setup)
        [[ -f "$CF_DIR/cert.pem" ]] || cloudflared tunnel login
        ID="$(tunnel_id)"
        if [[ -z "$ID" ]]; then
            cf tunnel create "$TUNNEL_NAME"
            ID="$(tunnel_id)"
        fi
        cf tunnel route dns --overwrite-dns "$ID" "$HOSTNAME"
        echo "  [ OK ] $HOSTNAME -> tunnel $TUNNEL_NAME ($ID)"
        ;;
    status)
        cf tunnel info "$TUNNEL_NAME"
        ;;
    run)
        ID="$(tunnel_id)"
        if [[ -z "$ID" || ! -f "$CF_DIR/$ID.json" ]]; then
            echo "  [FAIL] Tunnel '$TUNNEL_NAME' not set up. Run: bash scripts/tunnel.sh setup"
            echo "         or use a throwaway URL now: bash scripts/tunnel.sh quick"
            exit 1
        fi
        check_app
        cat > "$RUN_CONFIG" <<EOF
tunnel: $ID
credentials-file: $CF_DIR/$ID.json
protocol: ${TUNNEL_PROTOCOL:-auto}
ingress:
  - hostname: $HOSTNAME
    service: http://127.0.0.1:$APP_PORT
  - service: http_status:404
EOF
        echo ""
        echo "  =========================================="
        echo "   PreReads  https://$HOSTNAME"
        echo "   -> http://127.0.0.1:$APP_PORT   (Ctrl+C to stop)"
        echo "  =========================================="
        echo ""
        cloudflared --config "$RUN_CONFIG" tunnel run "$ID"
        ;;
    quick)
        check_app
        echo ""
        echo "  =========================================="
        echo "   PreReads quick tunnel (no account)"
        echo "   Look for the https://<random>.trycloudflare.com URL below"
        echo "   -> http://127.0.0.1:$APP_PORT   (Ctrl+C to stop)"
        echo "  =========================================="
        echo ""
        cloudflared --config "$EMPTY_CONFIG" tunnel --url "http://127.0.0.1:$APP_PORT"
        ;;
    *)
        echo "  [FAIL] Unknown command: $CMD (use: run | setup | status | quick | help)"
        exit 1
        ;;
esac
