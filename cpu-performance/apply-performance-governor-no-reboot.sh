#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root, for example: sudo $0" >&2
  exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  echo "Host: $(hostname)"
  echo "OS: ${PRETTY_NAME:-unknown}"
fi

ts="$(date +%F-%H%M%S)"
backup_dir="/root/cpupower-fix-backup/${ts}"
mkdir -p "${backup_dir}"

echo "Backing up current cpupower and tuned state to ${backup_dir}"
cp -a /etc/sysconfig/cpupower "${backup_dir}/cpupower.sysconfig" 2>/dev/null || true
cp -a /etc/systemd/system/cpupower.service.d "${backup_dir}/cpupower.service.d" 2>/dev/null || true
cp -a /etc/tuned/active_profile "${backup_dir}/tuned.active_profile" 2>/dev/null || true

if [[ -f /etc/sysconfig/cpupower ]]; then
  echo "Neutralizing cpupower stop action"
  if grep -q '^CPUPOWER_STOP_OPTS=' /etc/sysconfig/cpupower; then
    sed -i 's/^CPUPOWER_STOP_OPTS=.*/CPUPOWER_STOP_OPTS=""/' /etc/sysconfig/cpupower
  else
    printf '\nCPUPOWER_STOP_OPTS=""\n' >> /etc/sysconfig/cpupower
  fi
fi

echo "Disabling cpupower as a boot-time policy owner"
systemctl disable --now cpupower.service || true

if [[ -f /etc/systemd/system/cpupower.service.d/override.conf ]]; then
  echo "Removing cpupower override.conf"
  rm -f /etc/systemd/system/cpupower.service.d/override.conf
  rmdir /etc/systemd/system/cpupower.service.d 2>/dev/null || true
  systemctl daemon-reload
fi

echo "Switching TuneD to throughput-performance"
systemctl enable --now tuned.service
tuned-adm profile throughput-performance
systemctl restart tuned.service

read_governors() {
  cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null | sort -u | xargs echo
}

governors="$(read_governors)"
if [[ "${governors}" != "performance" ]]; then
  echo "throughput-performance left governors at: ${governors:-unknown}"
  echo "Creating local TuneD fallback profile server-performance"
  mkdir -p /etc/tuned/server-performance
  cat > /etc/tuned/server-performance/tuned.conf <<'EOF'
[main]
summary=Local server performance governor profile
include=throughput-performance

[cpu]
governor=performance
energy_perf_bias=performance
EOF
  tuned-adm profile server-performance
  systemctl restart tuned.service
fi

echo
echo "Verification:"
tuned-adm active
tuned-adm verify || true
cpupower frequency-info 2>&1 | egrep 'driver|available cpufreq governors|current policy|The governor' || true
echo "Unique governors: $(read_governors)"
echo "Service activity:"
systemctl is-active tuned.service cpupower.service || true
echo "Service enablement:"
systemctl is-enabled tuned.service cpupower.service || true

final_governors="$(read_governors)"
if [[ "${final_governors}" != "performance" ]]; then
  echo "ERROR: expected only performance governors, got: ${final_governors:-unknown}" >&2
  exit 1
fi

if ! systemctl is-active --quiet tuned.service; then
  echo "ERROR: tuned.service is not active" >&2
  exit 1
fi

if systemctl is-active --quiet cpupower.service; then
  echo "ERROR: cpupower.service is still active" >&2
  exit 1
fi

if [[ -x "${script_dir}/collect-cpupower-info.sh" ]]; then
  echo
  echo "Collecting post-change evidence without reboot"
  "${script_dir}/collect-cpupower-info.sh" | tee collected-after-nonreboot-fix.txt >/dev/null
  if [[ -n "${SUDO_UID:-}" && -n "${SUDO_GID:-}" ]]; then
    chown "${SUDO_UID}:${SUDO_GID}" collected-after-nonreboot-fix.txt
  fi
fi

echo
echo "Done. No reboot was performed."
