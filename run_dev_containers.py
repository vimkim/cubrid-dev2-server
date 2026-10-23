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
from resource_policy import Policy

NETWORK = "dev2-net"
SPEC_LABEL_KEY = "spec-hash"
DEFAULT_IMAGE = "localhost/local/r8-systemd:250708-ubi-init"


# ──────────────────────────── helper wrappers ──────────────────────────────
def sh(cmd, *, dry=False, capture=False):
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    if dry:
        print("$", shlex.join(cmd))
        return ""
    res = subprocess.run(cmd, check=True, capture_output=capture, text=True, timeout=120)
    return res.stdout.strip() if capture else ""


def spec_hash(spec: dict) -> str:
    raw = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def container_exists(name, *, dry=False) -> bool:
    try:
        sh(["sudo", "podman", "container", "exists", name], dry=dry)
        return True
    except subprocess.CalledProcessError as error:
        if error.returncode == 1:
            return False
        raise


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


def run_container(name, spec, policy, *, dry=False):
    user = spec.get("user", "dev")
    image = spec.get("image", DEFAULT_IMAGE)
    ip = spec["ip"]
    vol = f"vol-{name}"
    label = f"{SPEC_LABEL_KEY}={spec_hash(effective_spec(spec, policy))}"
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
            "--systemd",
            "always" if spec.get("systemd", True) else "false",
            "--privileged",
            "-v",
            f"{vol}:/home",
            *policy.options(name),
            image,
            *spec.get("command", []),
        ],
        dry=dry,
    )

    if spec.get("manage_user", True):
        ensure_user(name, user, ip, dry=dry)
    if not dry:
        print(f"▶ enter: podman exec -it --user {user} {name} bash")


# ────────────────────────────────── main ────────────────────────────────────
def effective_spec(spec, policy):
    return {**spec, "resource_policy": policy.identity(spec["name"])}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="containers.yaml")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resource-policy", default="resource-policy.json")
    ap.add_argument("--only", action="append", help="Select an exact container name, repeatable")
    ap.add_argument("--audit", action="store_true", help="Read-only inspect comparison; never create")
    ap.add_argument("--inspect-json", help="Use a saved Podman JSON array for an offline audit")
    args = ap.parse_args(argv)
    if args.audit and args.dry_run:
        ap.error("choose --audit or --dry-run")
    if args.inspect_json and not args.audit:
        ap.error("--inspect-json requires --audit")

    all_specs = yaml.safe_load(Path(args.config).read_text()).get("containers", [])
    specs = all_specs
    policy = Policy.load(args.resource_policy)
    names = [spec["name"] for spec in specs]
    if len(set(names)) != len(names):
        ap.error("container names must be unique")
    if args.only and set(args.only) - set(names):
        ap.error("--only names must exist in the configuration")
    specs = [s for s in specs if not args.only or s["name"] in args.only]
    for spec in specs:
        policy.limits(spec["name"])
        if not isinstance(spec.get("command", []), list) or any(
            not isinstance(part, str) for part in spec.get("command", [])
        ):
            ap.error("command must be a list of strings")
    if args.audit:
        if args.inspect_json:
            containers = json.loads(Path(args.inspect_json).read_text())
        else:
            ids = sh(["sudo", "-n", "podman", "ps", "-aq"], capture=True).split()
            containers = json.loads(sh(["sudo", "-n", "podman", "inspect", *ids], capture=True)) if ids else []
        rows = policy.audit(all_specs, containers)
        if args.only:
            rows = [row for row in rows if row["name"] in args.only]
        print(json.dumps(rows, indent=2))
        return
    if args.dry_run:
        print("Creation preview only. Existing containers and host preconditions are not inspected.")
        for spec in specs:
            run_container(spec["name"], spec, policy, dry=True)
        return
    # No Podman calls or host changes occur before the complete policy preflight.
    policy.preflight(specs)

    for spec in specs:
        name = spec["name"]
        desired_hash = spec_hash(effective_spec(spec, policy))

        if not container_exists(name, dry=args.dry_run):
            print(f"Creating new container {name} …")
            run_container(name, spec, policy)
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
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        sys.exit(f"Cannot reconcile containers: {e}")
