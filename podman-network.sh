#!/usr/bin/env bash
set -euo pipefail

# Variables you can export or hard-code
DEV=${DEV:-$(ip route show default | awk 'NR == 1 {print $5}')}
SUBNET=${SUBNET:-$(ip -4 addr show "$DEV" |
    awk '/inet /{print $2}' |
    head -1)}
GW=${GW:-$(ip route show default | awk 'NR==1 {print $3}')}
IP_RANGE=${IP_RANGE:-172.30.1.36/29}

sudo podman network create --ignore \
    --driver ipvlan \
    --opt parent="$DEV" \
    --opt mode=l2 \
    --subnet "$SUBNET" \
    --gateway "$GW" \
    --ip-range "$IP_RANGE" \
    dev2-net
