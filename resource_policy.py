"""Validate the reviewed resource budget and produce persistent Podman options."""

import argparse
import json
import math
import re
import stat
from pathlib import Path


LIMITS = {"cpus", "memory_high", "memory_max", "swap_max", "shm_size", "systemd_tmpfs_size"}


class Policy:
    def __init__(self, payload):
        self.payload = payload
        if payload.get("schema") != 1 or not isinstance(payload.get("approved"), bool):
            raise ValueError("policy requires schema 1 and a boolean approved field")
        self.pool = payload["pool"]
        if not re.fullmatch(r"[a-zA-Z0-9_]+\.slice", self.pool["slice"]):
            raise ValueError("pool slice must be a top-level systemd slice")
        self.tmp_root = Path(payload["tmp_root"])
        if not self.tmp_root.is_absolute() or any(c in str(self.tmp_root) for c in ",:\n"):
            raise ValueError("tmp_root must be an absolute Podman bind path without commas or colons")
        self._limits(self.pool, {"memory_high", "memory_max", "swap_max"})
        self._limits(payload["defaults"], LIMITS)
        reserve = payload["host_reserve"]
        if type(reserve) is not int or reserve <= 0:
            raise ValueError("host_reserve must be positive bytes")
        for name, overrides in payload.get("overrides", {}).items():
            if not isinstance(overrides, dict) or set(overrides) - LIMITS:
                raise ValueError(f"invalid limit overrides for {name}")
            self.limits(name)

    @classmethod
    def load(cls, path):
        try:
            return cls(json.loads(Path(path).read_text()))
        except (KeyError, TypeError) as error:
            raise ValueError(f"invalid policy structure: {error}") from error

    @staticmethod
    def _limits(values, required):
        if set(values) - (required | {"slice"}) or not required <= set(values):
            raise ValueError("policy contains missing or unknown limit fields")
        if "cpus" in required:
            cpus = values["cpus"]
            try:
                valid_cpu = type(cpus) in (int, float) and math.isfinite(cpus) and cpus >= 0.01
            except OverflowError:
                valid_cpu = False
            if not valid_cpu:
                raise ValueError("cpus must be a finite number of at least 0.01")
        for key in required - {"cpus"}:
            value = values[key]
            minimum = 0 if key == "swap_max" else 1
            if type(value) is not int or value < minimum:
                raise ValueError(f"{key} must be finite integer bytes")
        if values["memory_high"] >= values["memory_max"]:
            raise ValueError("memory_high must be below memory_max")
        for key in required & {"shm_size", "systemd_tmpfs_size"}:
            if values[key] >= values["memory_max"]:
                raise ValueError(f"{key} must be below memory_max")

    def limits(self, name):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", name):
            raise ValueError("invalid container name")
        limits = {**self.payload["defaults"], **self.payload.get("overrides", {}).get(name, {})}
        self._limits(limits, LIMITS)
        if limits["memory_max"] > self.pool["memory_max"] or limits["swap_max"] > self.pool["swap_max"]:
            raise ValueError("container limit exceeds pool limit")
        return limits

    def identity(self, name):
        return {"schema": 1, "limits": self.limits(name), "slice": self.pool["slice"],
                "tmp": str(self.tmp_root / name), "cgroupns": "private", "image_volume": "ignore"}

    def options(self, name):
        limits = self.limits(name)
        return ["--cgroup-parent", self.pool["slice"], "--cgroupns", "private",
                # The Rocky image declares /sys/fs/cgroup as an image volume.
                # Do not obscure Podman's private cgroup mount with an anonymous volume.
                "--image-volume", "ignore",
                "--cpus", str(limits["cpus"]),
                "--cgroup-conf", f"memory.high={limits['memory_high']}",
                "--memory", str(limits["memory_max"]),
                # Podman memory-swap is RAM + swap. systemd MemorySwapMax is swap alone.
                "--memory-swap", str(limits["memory_max"] + limits["swap_max"]),
                "--shm-size", str(limits["shm_size"]),
                "--shm-size-systemd", str(limits["systemd_tmpfs_size"]),
                "--mount", f"type=bind,src={self.tmp_root / name},dst=/tmp"]

    def slice_unit(self):
        return ("[Unit]\nDescription=Shared dev2 container resource pool\n\n[Slice]\n"
                "MemoryAccounting=yes\n"
                f"MemoryHigh={self.pool['memory_high']}\n"
                f"MemoryMax={self.pool['memory_max']}\n"
                f"MemorySwapMax={self.pool['swap_max']}\n")

    def preflight(self, specs, *, cgroup_root=Path("/sys/fs/cgroup"),
                  meminfo=Path("/proc/meminfo"), mountinfo=Path("/proc/self/mountinfo")):
        if not self.payload["approved"]:
            raise ValueError("resource policy is a proposal; review and approve it before deployment")
        total = next(int(line.split()[1]) * 1024 for line in meminfo.read_text().splitlines()
                     if line.startswith("MemTotal:"))
        if self.pool["memory_max"] + self.payload["host_reserve"] > total:
            raise ValueError("pool ceiling plus host reserve exceeds physical RAM")
        for field in ("memory.high", "memory.max", "memory.swap.max"):
            expected = self.pool[field.replace(".", "_").replace("memory_swap", "swap")]
            if (cgroup_root / self.pool["slice"] / field).read_text().strip() != str(expected):
                raise ValueError(f"active pool {field} differs from the reviewed policy")
        root_stat = self.tmp_root.stat()
        if root_stat.st_uid != 0 or root_stat.st_mode & 0o022:
            raise ValueError("tmp_root must be root-owned without group or other write access")
        for spec in specs:
            name = spec["name"]
            self.limits(name)
            path = self.tmp_root / name
            metadata = path.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0:
                raise ValueError(f"{name}: /tmp bind source must be a root-owned directory")
            if stat.S_IMODE(metadata.st_mode) != 0o1777:
                raise ValueError(f"{name}: /tmp bind source must have mode 1777")
            # Check the actual backing mount, not just the directory's name.
            canonical = path.resolve(strict=True)
            mounts = []
            for line in mountinfo.read_text().splitlines():
                before, separator, after = line.partition(" - ")
                if not separator:
                    continue
                mount = Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), before.split()[4]))
                if canonical == mount or mount in canonical.parents:
                    mounts.append((len(str(mount)), after.split()[0]))
            if not mounts or max(mounts)[1] not in {"xfs", "ext4", "btrfs"}:
                raise ValueError(f"{name}: /tmp source is not on an approved disk filesystem")

    def audit(self, specs, containers):
        by_name = {c["Name"].lstrip("/"): c for c in containers}
        expected = {s["name"] for s in specs}
        rows = []
        for name in sorted(expected | set(by_name)):
            if name not in expected:
                rows.append({"name": name, "status": "outside-roster"})
                continue
            if name not in by_name:
                rows.append({"name": name, "status": "missing"})
                continue
            actual = by_name[name]
            host = actual.get("HostConfig", {})
            limits = self.limits(name)
            drift = []
            fields = {"Memory": limits["memory_max"],
                      "MemorySwap": limits["memory_max"] + limits["swap_max"],
                      "ShmSize": limits["shm_size"], "CgroupParent": self.pool["slice"],
                      "CgroupnsMode": "private"}
            for key, wanted in fields.items():
                if host.get(key) != wanted:
                    drift.append(key)
            nano_cpus = host.get("NanoCpus") or 0
            period = host.get("CpuPeriod") or 0
            quota = host.get("CpuQuota") or 0
            if nano_cpus > 0:
                actual_cpus, precision = nano_cpus / 1_000_000_000, 1e-9
            elif period > 0 and quota > 0:
                actual_cpus, precision = quota / period, 1 / period
            else:
                actual_cpus, precision = 0, 1e-9
            if not math.isclose(actual_cpus, limits["cpus"], rel_tol=0, abs_tol=precision):
                drift.append("cpus")
            if str((host.get("CgroupConf") or {}).get("memory.high")) != str(limits["memory_high"]):
                drift.append("memory.high (inspect unavailable or differs; verify live cgroup)")
            mounts = actual.get("Mounts", [])
            if not any(m.get("Destination") == "/tmp" and m.get("Type") == "bind"
                       and m.get("Source") == str(self.tmp_root / name) for m in mounts):
                drift.append("disk-backed /tmp bind")
            if "/tmp" in (host.get("Tmpfs") or {}):
                drift.append("conflicting /tmp tmpfs")
            if any(m.get("Destination") == "/sys/fs/cgroup" for m in mounts):
                drift.append("explicit cgroup mount; review source and live namespace")
            # Actual mount capacity and memory.high must still be checked live.
            rows.append({"name": name, "status": "drift" if drift else "inspect-matches",
                         "differences": drift})
        return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--render-slice", action="store_true", required=True)
    args = parser.parse_args()
    try:
        print(Policy.load(args.policy).slice_unit(), end="")
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
