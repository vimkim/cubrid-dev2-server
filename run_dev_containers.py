#!/usr/bin/env python3
"""
Create Rocky-8 dev containers and (optionally) add a non-root user inside
*without* rebuilding the image each time.
"""

import argparse, subprocess, sys, yaml
from pathlib import Path

IMAGE = "localhost/local/r8-systemd"
NETWORK = "dev2-net"
CGROUP_MOUNT = "/sys/fs/cgroup:/sys/fs/cgroup:ro"


def sh(cmd, *, dry=False):
    print("$", *cmd)
    if not dry:
        subprocess.run(cmd, check=True)


def ensure_user(cname, user, *, dry=False):
    """If <user> does not exist in <cname>, create it (plus wheel access)."""
    shell = (
        f"id -u {user} >/dev/null 2>&1 || "
        f"(useradd -m -s /bin/bash {user} "
        f"&& echo '{user}:changeme' | chpasswd "
        f"&& usermod -aG wheel {user})"
    )
    sh(["sudo", "podman", "exec", cname, "bash", "-c", shell], dry=dry)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-c", "--config", default="containers.yaml")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text()).get("containers", [])
    for spec in cfg:
        name, ip = spec["name"], spec["ip"]
        user = spec.get("user", "dev")  # default fallback
        volume = f"vol-{name}"

        # 1. start container
        sh(
            [
                "sudo",
                "podman",
                "run",
                "-d",
                "--name",
                name,
                "--network",
                NETWORK,
                "--ip",
                ip,
                "--privileged",
                "-v",
                f"{volume}:/home",
                "-v",
                CGROUP_MOUNT,
                IMAGE,
            ],
            dry=args.dry_run,
        )

        # 2. add user (skipped in dry-run)
        ensure_user(name, user, dry=args.dry_run)

        # 3. convenience hint
        if not args.dry_run:
            print(f"▶ enter: sudo podman exec -it --user {user} {name} bash\n")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
