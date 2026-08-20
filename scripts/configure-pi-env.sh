#!/usr/bin/env sh
set -eu

if ! command -v tailscale >/dev/null 2>&1; then
  echo "tailscale is required to configure private Pi access" >&2
  exit 1
fi

pi_address="$(tailscale ip -4 | head -n 1)"
pi_hostname="$(hostname -s)"
pi_dns_name="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
root_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
env_file="${root_dir}/.env"

if [ -z "$pi_address" ]; then
  echo "the Pi does not have an active Tailscale IPv4 address" >&2
  exit 1
fi

if [ -f "${env_file}" ] && grep -q '^ROOMCAM_AUTH_PASSWORD_HASH=' "${env_file}"; then
  auth_config="$(grep '^ROOMCAM_AUTH_PASSWORD_HASH=' "${env_file}" | tail -n 1)"
else
  echo "Authentication is not configured." >&2
  echo "Run: python3 scripts/configure-auth.py .env" >&2
  exit 1
fi

cat >"${env_file}" <<EOF
ROOMCAM_STREAM_HEALTH_URL=http://127.0.0.1:8889/roomcam/
ROOMCAM_PUBLIC_STREAM_URL=/stream/roomcam/
ROOMCAM_STREAM_UPSTREAM=http://127.0.0.1:8889
ROOMCAM_STREAM_PATH=/roomcam/
ROOMCAM_BIND_HOST=127.0.0.1
ROOMCAM_ALLOWED_HOSTS=localhost,127.0.0.1,${pi_hostname},${pi_dns_name}
ROOMCAM_DETECTION_ENABLED=true
ROOMCAM_DETECTION_SOURCE=rtsp://127.0.0.1:8554/roomcam-detection
ROOMCAM_DETECTION_MODEL=/app/models/ssd_mobilenet_v2_int8.tflite
ROOMCAM_DETECTION_CONFIDENCE=0.6
ROOMCAM_DETECTION_THREADS=1
EOF
printf '%s\n' "${auth_config}" >>"${env_file}"
chmod 600 "${env_file}"

sudo tailscale serve --bg --yes 8080 >/dev/null

echo "Configured .env for https://${pi_dns_name}/ (${pi_address})"
