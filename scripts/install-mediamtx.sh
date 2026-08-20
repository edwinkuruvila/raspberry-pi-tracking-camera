#!/usr/bin/env sh
set -eu

MEDIAMTX_VERSION="1.19.2"
MEDIAMTX_ARCHIVE="mediamtx_v${MEDIAMTX_VERSION}_linux_arm64.tar.gz"
MEDIAMTX_SHA256="562f419912a8668c18216a9e8c95359ec82fbb754e4a44e2953ef62b98eec688"
MEDIAMTX_URL="https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/${MEDIAMTX_ARCHIVE}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi
if [ "$#" -ne 1 ]; then
  echo "Usage: sudo $0 AUTHORIZED_TAILSCALE_IPV4" >&2
  exit 2
fi

authorized_ip="$1"
root_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
tailscale_ip="$(tailscale ip -4 | head -n 1)"
magicdns_name="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"

python3 -c 'import ipaddress,sys; address=ipaddress.ip_address(sys.argv[1]); assert address.version == 4' "${authorized_ip}"
python3 -c 'import ipaddress,sys; address=ipaddress.ip_address(sys.argv[1]); assert address.version == 4' "${tailscale_ip}"

temporary_dir="$(mktemp -d)"
backup_dir="/var/backups/roomcam-mediamtx/$(date -u +%Y%m%dT%H%M%SZ)"
trap 'rm -rf "${temporary_dir}"' EXIT INT TERM
install -d -o root -g root -m 0700 "${backup_dir}"

backup_file() {
  source_path="$1"
  backup_name="$2"
  if [ -e "${source_path}" ]; then
    cp -a "${source_path}" "${backup_dir}/${backup_name}"
  fi
}

backup_file /usr/local/bin/mediamtx mediamtx
backup_file /usr/local/etc/mediamtx/mediamtx.yml mediamtx.yml
backup_file /etc/systemd/system/mediamtx.service mediamtx.service
backup_file /etc/systemd/system/mediamtx.service.d/20-network-allowlist.conf 20-network-allowlist.conf

restore_file() {
  backup_name="$1"
  target_path="$2"
  if [ -e "${backup_dir}/${backup_name}" ]; then
    cp -a "${backup_dir}/${backup_name}" "${target_path}"
  else
    rm -f "${target_path}"
  fi
}

rollback() {
  restore_file mediamtx /usr/local/bin/mediamtx
  restore_file mediamtx.yml /usr/local/etc/mediamtx/mediamtx.yml
  restore_file mediamtx.service /etc/systemd/system/mediamtx.service
  restore_file 20-network-allowlist.conf /etc/systemd/system/mediamtx.service.d/20-network-allowlist.conf
  systemctl daemon-reload
  systemctl restart mediamtx.service >/dev/null 2>&1 || true
}

curl --fail --location --silent --show-error "${MEDIAMTX_URL}" --output "${temporary_dir}/${MEDIAMTX_ARCHIVE}"
printf '%s  %s\n' "${MEDIAMTX_SHA256}" "${temporary_dir}/${MEDIAMTX_ARCHIVE}" | sha256sum --check --status
tar -xzf "${temporary_dir}/${MEDIAMTX_ARCHIVE}" -C "${temporary_dir}" mediamtx
"${temporary_dir}/mediamtx" --version

if ! getent group mediamtx >/dev/null; then
  groupadd --system mediamtx
fi
if ! id mediamtx >/dev/null 2>&1; then
  useradd --system --gid mediamtx --no-create-home --shell /usr/sbin/nologin mediamtx
fi
for device_group in video render; do
  if getent group "${device_group}" >/dev/null; then
    usermod --append --groups "${device_group}" mediamtx
  fi
done

sed \
  -e "s/__TAILSCALE_IP__/${tailscale_ip}/g" \
  -e "s/__MAGICDNS_NAME__/${magicdns_name}/g" \
  "${root_dir}/deploy/mediamtx.yml.template" >"${temporary_dir}/mediamtx.yml"
sed "s/YOUR_AUTHORIZED_TAILSCALE_IP/${authorized_ip}/g" \
  "${root_dir}/deploy/mediamtx-network-allowlist.conf.example" >"${temporary_dir}/network-allowlist.conf"

install -o root -g root -m 0755 "${temporary_dir}/mediamtx" /usr/local/bin/mediamtx
install -d -o root -g mediamtx -m 0750 /usr/local/etc/mediamtx
install -o root -g mediamtx -m 0640 "${temporary_dir}/mediamtx.yml" /usr/local/etc/mediamtx/mediamtx.yml
install -o root -g root -m 0644 "${root_dir}/deploy/mediamtx.service" /etc/systemd/system/mediamtx.service
install -d -o root -g root -m 0755 /etc/systemd/system/mediamtx.service.d
install -o root -g root -m 0644 "${temporary_dir}/network-allowlist.conf" \
  /etc/systemd/system/mediamtx.service.d/20-network-allowlist.conf

systemctl daemon-reload
systemctl enable mediamtx.service
if ! systemctl restart mediamtx.service; then
  rollback
  echo "MediaMTX failed to start and the previous installation was restored from ${backup_dir}." >&2
  exit 1
fi

echo "Installed MediaMTX v${MEDIAMTX_VERSION}; rollback files: ${backup_dir}"
