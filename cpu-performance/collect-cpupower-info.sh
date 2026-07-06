#!/usr/bin/env bash
set -u

section() {
  printf '\n===== %s =====\n' "$1"
}

run() {
  local desc="$1"
  shift
  printf '\n$ %s\n' "$*"
  if command -v "$1" >/dev/null 2>&1 || [[ "$1" == /* || "$1" == ./* ]]; then
    "$@" 2>&1 || printf '[exit %s]\n' "$?"
  else
    printf '[missing command: %s]\n' "$1"
  fi
}

print_file() {
  local path="$1"
  printf '\n$ cat %s\n' "$path"
  if [[ -r "$path" ]]; then
    sed -e 's/[[:cntrl:]]//g' "$path" 2>&1 || printf '[exit %s]\n' "$?"
  else
    printf '[not readable or missing]\n'
  fi
}

print_glob_values() {
  local title="$1"
  local pattern="$2"
  local file
  local found=0
  section "$title"
  shopt -s nullglob
  for file in $pattern; do
    found=1
    printf '%s: ' "$file"
    cat "$file" 2>/dev/null || printf '[not readable]'
    printf '\n'
  done
  shopt -u nullglob
  if [[ "$found" -eq 0 ]]; then
    printf '[no matches: %s]\n' "$pattern"
  fi
}

section "Collector"
printf 'timestamp: %s\n' "$(date -Is 2>/dev/null || date)"
printf 'user: %s\n' "$(id 2>/dev/null || true)"
printf 'hostname: %s\n' "$(hostname -f 2>/dev/null || hostname 2>/dev/null || true)"
printf 'script: %s\n' "$0"

section "OS and Kernel"
print_file /etc/os-release
run "kernel" uname -a
print_file /proc/cmdline
run "cpu summary" lscpu

section "CPUfreq State"
run "cpupower frequency-info" cpupower frequency-info
run "cpupower info" cpupower info
print_glob_values "Governors by CPU" "/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"
print_glob_values "Available Governors by CPU" "/sys/devices/system/cpu/cpu*/cpufreq/scaling_available_governors"
print_glob_values "CPUfreq Drivers by CPU" "/sys/devices/system/cpu/cpu*/cpufreq/scaling_driver"
print_glob_values "Energy Performance Preference by CPU" "/sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference"
print_glob_values "Energy Performance Available Preferences by CPU" "/sys/devices/system/cpu/cpu*/cpufreq/energy_performance_available_preferences"

section "Intel P-State / AMD P-State"
print_file /sys/devices/system/cpu/intel_pstate/status
print_file /sys/devices/system/cpu/intel_pstate/no_turbo
print_file /sys/devices/system/cpu/intel_pstate/min_perf_pct
print_file /sys/devices/system/cpu/intel_pstate/max_perf_pct
print_file /sys/devices/system/cpu/amd_pstate/status
print_file /sys/devices/system/cpu/amd_pstate/cppc_dynamic_boost

section "Relevant Services"
run "service enabled states" systemctl is-enabled tuned.service cpupower.service power-profiles-daemon.service auto-cpufreq.service tlp.service
run "service active states" systemctl is-active tuned.service cpupower.service power-profiles-daemon.service auto-cpufreq.service tlp.service
run "tuned status" systemctl status tuned.service --no-pager
run "cpupower status" systemctl status cpupower.service --no-pager
run "power-profiles-daemon status" systemctl status power-profiles-daemon.service --no-pager
run "auto-cpufreq status" systemctl status auto-cpufreq.service --no-pager
run "tlp status" systemctl status tlp.service --no-pager

section "TuneD"
run "tuned active profile" tuned-adm active
run "tuned recommended profile" tuned-adm recommend
run "tuned list" tuned-adm list
run "tuned verify" tuned-adm verify
print_file /etc/tuned/active_profile
print_file /etc/tuned/profile_mode
print_file /etc/tuned/tuned-main.conf

section "Cpupower Configuration"
print_file /etc/sysconfig/cpupower
run "cpupower unit" systemctl cat cpupower.service
run "cpupower unit dependencies" systemctl list-dependencies cpupower.service --all --no-pager

section "Power Profiles Daemon"
run "powerprofilesctl" powerprofilesctl
run "power-profiles-daemon unit" systemctl cat power-profiles-daemon.service

section "Other Power Managers and Packages"
run "installed related packages" bash -lc "rpm -q tuned kernel-tools power-profiles-daemon auto-cpufreq tlp 2>/dev/null; rpm -qa 'kernel*' 2>/dev/null | sort"
run "matching services" bash -lc "systemctl list-unit-files --no-pager | grep -Ei 'tuned|cpupower|power-profiles|auto-cpufreq|tlp|thermald' || true"

section "Boot Ordering"
run "critical chain tuned" systemd-analyze critical-chain tuned.service
run "critical chain cpupower" systemd-analyze critical-chain cpupower.service
run "critical chain power-profiles-daemon" systemd-analyze critical-chain power-profiles-daemon.service

section "Current Boot Logs"
run "relevant unit logs" journalctl -b -u tuned.service -u cpupower.service -u power-profiles-daemon.service -u auto-cpufreq.service -u tlp.service --no-pager -n 300
run "kernel cpufreq logs" bash -lc "journalctl -b -k --no-pager | grep -Ei 'cpufreq|pstate|governor|schedutil|performance|powersave|tuned|cpupower|power profile' | tail -n 300 || true"

section "Config Files Mentioning Governor or Performance"
if command -v grep >/dev/null 2>&1; then
  grep -RInE 'governor|schedutil|performance|powersave|energy_performance|cpupower|tuned-adm|powerprofilesctl' \
    /etc/sysconfig /etc/systemd /etc/tuned /usr/lib/systemd/system 2>/dev/null \
    | sed -n '1,400p' || true
else
  printf '[missing command: grep]\n'
fi

section "Summary Hints"
printf 'Unique current governors: '
if compgen -G "/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor" >/dev/null; then
  cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null | sort -u | xargs echo
else
  printf '[no cpufreq scaling_governor files]\n'
fi

printf 'Done. Run this once immediately after setting performance and once again after reboot.\n'
