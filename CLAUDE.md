# cubrid-dev2-server

Provisioning scripts for the **CUBRID dev2 team's** shared Linux host. Each developer
gets one or more long-lived **rootful podman** containers (Rocky 8 / Rocky 9 / Ubuntu 24)
that look and feel like real LAN machines: stable IPs, SSH, sudo, and a persistent
`/home` volume.

This repo is **not** CUBRID source — it is the infra recipe that lets each developer
build and test CUBRID inside an isolated, reproducible container.

---

## Mental model

```
host  ──┬── ipvlan L2 ──┬── vimkim1   192.168.4.151   (rocky8 + systemd + sshd)
        │  (dev2-net)   ├── vimkim2   192.168.4.152
        │               ├── hornetmj1 192.168.4.101
        │               └── ... (one per developer slot, see containers.yaml)
        │
        └── volumes: vol-<name> mounted at /home (survives container recreate)
```

- One container = one developer slot. IP and UID/GID are **derived from the YAML spec**, not from the host user.
- UID/GID scheme: `11000 + last_octet(ip)` — so `192.168.4.151` → UID/GID `11151`. Keeps file ownership stable across recreations and avoids host-UID collisions on shared mounts.
- `/home` is a named podman volume (`vol-<container>`), so destroying and recreating a container preserves the user's work.

---

## Core workflow

```bash
# 1. Create the shared L2 network (one-time, per host reboot if it was destroyed)
./podman-network.sh                 # creates ipvlan L2 network 'dev2-net'

# 2. Build the base image
just build                          # rocky8 + systemd  →  local/r8-systemd
# or
just build-ubuntu24                 # ubuntu24 (no systemd) →  localhost/cubrid-ubuntu24

# 3. Reconcile containers from declarative spec
just run-containers                 # = python run_dev_containers.py
# Pass --dry-run to preview.
```

`run_dev_containers.py` is **idempotent and conservative**:

| Container state                           | Action                                |
| ----------------------------------------- | ------------------------------------- |
| Missing                                   | Create + label with `spec-hash`       |
| Exists, hash matches YAML                 | Skip silently                         |
| Exists, hash differs (spec drift)         | **Warn only — never auto-recreate**   |

To apply a changed spec, the human must remove the container manually (preserves `/home` via the named volume).

---

## Why rootful `sudo podman` (the load-bearing decision)

- `--driver ipvlan --mode l2` requires the kernel `ipvlan` module and CAP_NET_ADMIN, which **rootless podman cannot give us**. So every `podman` call is `sudo podman`.
- The benefit is that each container gets a routable IP on the host's LAN — other dev2 hosts and CI can reach it like a normal machine. No port-forward gymnastics.
- Trade-off: containers run **privileged** (needed for systemd inside) and root inside the container is real root on shared resources. Treat the host as a trusted LAN-only box.

---

## File map

| Path                       | Purpose                                                                       |
| -------------------------- | ----------------------------------------------------------------------------- |
| `podman-network.sh`        | Creates the `dev2-net` ipvlan L2 network (idempotent; reads `DEV/SUBNET/GW`)  |
| `containers.yaml`          | Declarative roster: name → ip → user                                          |
| `run_dev_containers.py`    | Reconcile loop (create-or-skip, hash-labeled, warn-on-drift)                  |
| `justfile`                 | Thin task wrapper: `build`, `run-containers`, `build-ubuntu24`, `run-vk-ubun24` |
| `rocky8/Dockerfile`        | Rocky 8.10 + systemd + sshd + dev tools (`@Development Tools`, cmake, ninja, jdk8, systemtap, ncurses) |
| `rocky9/Dockerfile`        | Rocky 9.6 equivalent (uses `crb` repo where rocky8 used `powertools`)         |
| `ubuntu24/Dockerfile`      | **Non-systemd** Ubuntu 24 image — runs `sshd -D` via ENTRYPOINT; hardcodes user `vimkim` |
| `utils/podman-multiexec.sh`| Copy & run a shell script across containers matching a name filter            |
| `README.md`                | Human-facing setup notes + troubleshooting (IP-in-use, image-size FAQ)        |

---

## Image design conventions

- **Build cache over image size.** The Dockerfiles deliberately use many small `RUN` layers so that editing one package list doesn't reinstall the world. Final image ≈ 2 GB; that is intentional. Do not "optimize" with multi-stage / squashing unless you also retire the daily-rebuild workflow.
- **Default credentials are dev-only.** Rocky images: `root:changeme`. Ubuntu24: `vimkim:password` + NOPASSWD sudo, `PermitRootLogin no`. These are **safe only on a trusted LAN host** — never publish these images.
- **Rocky vs Ubuntu divergence is real.** Rocky containers boot `systemd` (and `sshd` is enabled via `systemctl`). Ubuntu24 container has no systemd and starts `sshd` directly. The `ensure_user()` flow in `run_dev_containers.py` assumes a running container you can `podman exec` into — both images satisfy that, but anything that calls `systemctl` inside the container will only work on Rocky.
- **`MAKEFLAGS="-j $(($(nproc)/2))"`** is set in the Rocky images so naive `make` invocations don't OOM the shared host. Keep this in mind before "fixing" it.

---

## Known sharp edges (verify before relying on them)

- `just run` invokes `./run-container.sh`, which was removed in commit `f8d4bfb`. The target is stale.
- `containers.yaml` has no per-entry `image:` field, so every container — including `pgsql*` / `mysql*` — currently defaults to `local/r8-systemd`. The "pgsql/mysql" naming is aspirational; the images are still Rocky 8.
- `podman-network.sh`'s header comment says the default `IP_RANGE` is `192.168.4.100/25`, but the code default is `/24`. Trust the code.
- `podman-multiexec.sh` redirects exec stderr to `/dev/null`, hiding *why* a remote script failed. Strip the `2>/dev/null` when debugging.
- Empty root-owned file `./oom` at the repo root is an accidental artifact (likely from a sudo'd OOM dump); safe to remove.

---

## Operational quick reference

```bash
# Enter a container as its dev user
sudo podman exec -it --user vimkim vimkim1 bash

# Run the same script in every container matching a name filter (dry-run by default)
./utils/podman-multiexec.sh -f vimkim -s setup.sh          # preview
./utils/podman-multiexec.sh -f vimkim -s setup.sh -x       # execute
# ⚠ ALWAYS include your username in -f. Never use '.*' with destructive scripts.

# Tear down + recreate a single container (preserves /home via vol-<name>)
sudo podman rm -f vimkim1
just run-containers

# Recover from "IP address already in use" after a network recreate
# (see README.md — involves stopping podman/conmon and flushing route + neigh caches)
```

---

## When working in this repo

- **Default to declarative changes.** If you need a new container, add it to `containers.yaml` and run `just run-containers` — don't `podman run` ad-hoc.
- **Treat `run_dev_containers.py`'s drift-warning as a feature.** If a spec change must be applied, document it, remove the affected container, and let reconcile re-create it. The named `/home` volume survives.
- **Never `git add` the `oom` file or any `*.tar` / `*.img` build outputs.** This repo is configuration, not artifacts.
- **Don't add multi-stage or distroless images** without retiring the layer-cache rebuild workflow first — see the README FAQ.
- **Commit style follows conventional-commits**: `feat(<scope>):`, `fix(<scope>):`, `docs(<scope>):`, `refactor(<scope>):`, `clean(<scope>):`. Match it.
