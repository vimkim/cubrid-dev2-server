#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# create_podman_ipvlan.sh – create (or reuse) an IPvlan-L2 network for Podman
#
# Env-vars you may override:
#   NET_NAME   – network name          (default: dev2-net)
#   DEV        – parent NIC            (auto‐detected)
#   SUBNET     – IPv4 subnet/CIDR      (auto‐detected)
#   GW         – gateway               (auto‐detected)
#   IP_RANGE   – container pool CIDR   (default: 192.168.4.100/25)
# ---------------------------------------------------------------------------
set -euo pipefail

#######################################
# helpers
#######################################
log() { printf '[%s] %s\n' "$(date +'%F %T')" "$*" >&2; }
die() {
    log "ERROR: $*"
    exit 1
}
need() { command -v "$1" >/dev/null || die "required command '$1' not found"; }

need ip
need podman

#######################################
# settings (env-overrideable)
#######################################
NET_NAME=${NET_NAME:-dev2-net}
DEV=${DEV:-$(ip route show default | awk 'NR==1 {print $5}')}
SUBNET=${SUBNET:-$(ip -4 addr show "$DEV" | awk '/inet /{print $2}' | head -1)}
GW=${GW:-$(ip route show default | awk 'NR==1 {print $3}')}
IP_RANGE=${IP_RANGE:-192.168.4.100/24}

#######################################
# sanity checks
#######################################
[[ -n "$DEV" ]] || die "could not determine default interface"
[[ -n "$SUBNET" ]] || die "could not determine IPv4 subnet for $DEV"
[[ -n "$GW" ]] || die "could not determine IPv4 gateway"

#######################################
# show effective configuration
#######################################
log "Network name : $NET_NAME"
log "Parent NIC   : $DEV"
log "Subnet       : $SUBNET"
log "Gateway      : $GW"
log "IP pool      : $IP_RANGE"

#######################################
# create or reuse the network
#######################################
if podman network exists "$NET_NAME" 2>/dev/null; then
    log "Podman network '$NET_NAME' already exists – skipping creation"
else
    log "Creating IPvlan L2 network '$NET_NAME' …"
    sudo podman network create \
        --driver ipvlan \
        --opt parent="$DEV" \
        --opt mode=l2 \
        --subnet "$SUBNET" \
        --gateway "$GW" \
        --ip-range "$IP_RANGE" \
        "$NET_NAME"
    log "Network '$NET_NAME' created successfully"
fi
