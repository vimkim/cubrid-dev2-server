#!/usr/bin/env python3
"""
Rocky-8 dev-container launcher (idempotent, non-destructive).

Behaviour
---------
• If <name> does *not* exist  → create and label it.
• If <name> exists:
      – spec unchanged       → do nothing (still ensure the user exists).
      – spec changed         → print a warning, leave container untouched.
"""

import argparse, subprocess, sys, yaml, json, hashlib, shlex, ipaddress
from pathlib import Path

NETWORK = "dev2-net"
CGROUP_MOUNT = "/sys/fs/cgroup:/sys/fs/cgroup:ro"
SPEC_LABEL_KEY = "spec-hash"


# ──────────────────────────── helper wrappers ──────────────────────────────
def sh(cmd, *, dry=False, capture=False):
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    if dry:
        print("$", *cmd)
        return ""
    res = subprocess.run(cmd, check=True, capture_output=capture, text=True)
    return res.stdout.strip() if capture else ""


def spec_hash(spec: dict) -> str:
    raw = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def container_exists(name, *, dry=False) -> bool:
    try:
        sh(["sudo", "podman", "container", "exists", name], dry=dry)
        return True
    except subprocess.CalledProcessError:
        return False


def current_hash(name) -> str:
    try:
        fmt = f'{{{{ index .Config.Labels "{SPEC_LABEL_KEY}" }}}}'
        return sh(["sudo", "podman", "inspect", "-f", fmt, name], capture=True)
    except subprocess.CalledProcessError:
        return ""


# def ensure_user(cname, user, ip, *, dry=False):
#     uid_gid = f"1{ip.split('.')[-1]}:1{ip.split('.')[-1]}"
#
#     shell = (
#         f"id -u {user} >/dev/null 2>&1 || "
#         f"(useradd -m -s /bin/Bash {user} "
#         f"&& echo '{user}:changeme' | chpasswd "
#         f"&& usermod -aG wheel {user})"
#     )
#     sh(["sudo", "podman", "exec", cname, "bash", "-c", shell], dry=dry)


def ensure_user(
    cname,
    user,
    ip,
    *,
    uid_gid=None,  # override auto-derived ID
    password="changeme",  # initial passwd; set None to skip
    wheel=True,  # add to wheel group?
    dry=False,
):
    """
    Ensure `user` exists inside running container `cname`, using a UID/GID that
    maps deterministically from its IPv4 address (or a supplied uid_gid).

    UID/GID scheme (default):
        last_octet = <ip>.split('.')[-1]
        uid_gid    = 11000 + last_octet       # 11001-11255 for a /24 subnet
    """

    # ── 1. Work out the numeric UID/GID ────────────────────────────────────────
    if uid_gid is None:
        try:
            last_octet = int(ipaddress.IPv4Address(ip).packed[-1])
        except ipaddress.AddressValueError as exc:
            raise ValueError(f"Invalid IPv4 address: {ip}") from exc
        uid_gid = 11000 + last_octet

    # ── 2. Build the bash snippet that runs *inside* the container ─────────────
    uq = shlex.quote(user)
    pwq = shlex.quote(password) if password is not None else ""

    # Indentless HEREDOC for clarity
    script = f"""\
set -eu

# Create matching group if it does not exist
getent group {uid_gid} >/dev/null || groupadd -g {uid_gid} {uq}

# Create user if missing, with chosen UID/GID
id -u {uq} >/dev/null 2>&1 || \\
    useradd -m -u {uid_gid} -g {uid_gid} -s /bin/bash {uq}

# (Re)-set password, if requested
{"echo " + uq + ":" + pwq + " | chpasswd" if password else ""}

# Optional sudo access
{"usermod -aG wheel " + uq if wheel else ""}
"""

    cmd = ["sudo", "podman", "exec", cname, "bash", "-c", script]

    # ── 3. Execute or dry-run ──────────────────────────────────────────────────
    if dry:
        print("DRY-RUN CMD:", " ".join(shlex.quote(c) for c in cmd))
        print("----- begin script -----\n" + script + "------ end script ------")
        return

    sh(cmd)


def run_container(name, spec, *, dry=False):
    user = spec.get("user", "dev")
    image = spec.get("image", "localhost/local/r8-systemd")
    ip = spec["ip"]
    vol = f"vol-{name}"
    label = f"{SPEC_LABEL_KEY}={spec_hash(spec)}"
    hostname = spec.get("hostname", name)

    sh(
        [
            "sudo",
            "podman",
            "run",
            "-d",
            "--name",
            name,
            "--label",
            label,
            "--network",
            NETWORK,
            "--ip",
            ip,
            "--hostname",
            hostname,
            "--privileged",
            "-v",
            f"{vol}:/home",
            "-v",
            CGROUP_MOUNT,
            image,
        ],
        dry=dry,
    )

    ensure_user(name, user, ip, dry=dry)
    if not dry:
        print(f"▶ enter: podman exec -it --user {user} {name} bash")


# ────────────────────────────────── main ────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="containers.yaml")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    specs = yaml.safe_load(Path(args.config).read_text()).get("containers", [])

    for spec in specs:
        name = spec["name"]
        desired_hash = spec_hash(spec)

        if not container_exists(name, dry=args.dry_run):
            print(f"Creating new container {name} …")
            run_container(name, spec, dry=args.dry_run)
            continue

        # container exists – compare hashes
        cur_hash = current_hash(name)
        if cur_hash == desired_hash:
            print(f"{name}: up-to-date; skipping")
            # ensure_user(name, spec.get("user", "dev"), spec["ip"], dry=args.dry_run)
        else:
            print(
                f"⚠ {name}: spec in YAML differs from running container "
                f"(wanted={desired_hash[:8]}…, current={cur_hash[:8]}…).\n"
                f"  → No action taken. Recreate manually if desired."
            )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
