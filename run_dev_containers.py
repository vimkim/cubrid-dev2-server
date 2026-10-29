#!/usr/bin/env python3

import argparse
import hashlib
import ipaddress
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple, Union

import yaml

DEFAULT_IMAGE = "localhost/local/r8-systemd:250708-ubi-init"
SUDO_PODMAN = ("sudo", "-n", "--", "podman")
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
USER_PATTERN = re.compile(r"[a-z_][a-z0-9_-]*\Z")
PROVISION = """\
set -eu
user=$1
uid_gid=$2
getent group "$uid_gid" >/dev/null || groupadd -g "$uid_gid" "$user"
id -u "$user" >/dev/null 2>&1 || useradd -m -u "$uid_gid" -g "$uid_gid" -s /bin/bash "$user"
printf '%s:changeme\\n' "$user" | chpasswd
usermod -aG wheel "$user"
"""


@dataclass(frozen=True)
class Spec:
    name: str
    ip: str
    image: str
    hostname: str
    user: str
    declared_hash: str


@dataclass(frozen=True)
class Missing:
    pass


@dataclass(frozen=True)
class Existing:
    container_id: str
    running: bool
    declared_hash: Optional[str]


Observation = Union[Missing, Existing]


@dataclass(frozen=True)
class Command:
    argv: Tuple[str, ...]
    stdin: Optional[str] = None


@dataclass(frozen=True)
class Create:
    spec: Spec
    commands: Tuple[Command, ...]


@dataclass(frozen=True)
class Preserve:
    spec: Spec
    observed: Existing


Planned = Union[Create, Preserve]
Plan = Tuple[Planned, ...]


class WorkflowError(Exception):
    def __init__(self, code: str, message: str, command: Optional[Command] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.command = command


class InputError(WorkflowError):
    def __init__(self, message: str):
        super().__init__("input_error", message)


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InputError(message)


def load_specs(path: Path) -> Tuple[Spec, ...]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise InputError(f"Cannot read config {path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("containers"), list):
        raise InputError("Config must contain a containers list.")

    specs = []
    names = set()
    ips = set()
    for entry in raw["containers"]:
        if not isinstance(entry, dict):
            raise InputError("Each container entry must be a mapping.")
        name = entry.get("name")
        ip = entry.get("ip")
        image = entry.get("image", DEFAULT_IMAGE)
        hostname = entry.get("hostname", name)
        user = entry.get("user", "dev")
        if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
            raise InputError(f"Invalid container name: {name!r}.")
        if not isinstance(user, str) or not USER_PATTERN.fullmatch(user):
            raise InputError(f"Invalid user for {name}: {user!r}.")
        if not isinstance(hostname, str) or not NAME_PATTERN.fullmatch(hostname):
            raise InputError(f"Invalid hostname for {name}: {hostname!r}.")
        if (not isinstance(image, str) or not image or image.startswith("-")
                or any(c.isspace() or not c.isprintable() for c in image)):
            raise InputError(f"Invalid image for {name}: {image!r}.")
        try:
            if not isinstance(ip, str):
                raise ValueError("expected a string")
            address = ipaddress.IPv4Address(ip)
        except ValueError as exc:
            raise InputError(f"Invalid IPv4 address for {name}: {ip!r}.") from exc
        if name in names:
            raise InputError(f"Duplicate container name: {name}.")
        if address in ips:
            raise InputError(f"Duplicate IPv4 address: {ip}.")
        try:
            encoded = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()
        except (TypeError, ValueError, UnicodeError) as exc:
            raise InputError(f"Container {name} cannot be serialized for hashing: {exc}") from exc
        names.add(name)
        ips.add(address)
        specs.append(Spec(name, ip, image, hostname, user, hashlib.sha256(encoded).hexdigest()))
    return tuple(sorted(specs, key=lambda spec: spec.name))


def select_specs(specs: Tuple[Spec, ...], names: Sequence[str], all_names: bool, operation: str) -> Tuple[Spec, ...]:
    if names and all_names:
        raise InputError("Choose names or --all, not both.")
    if len(names) != len(set(names)):
        raise InputError("Container names must not be repeated.")
    by_name = {spec.name: spec for spec in specs}
    unknown = sorted(set(names) - by_name.keys())
    if unknown:
        raise InputError("Unknown container names: " + ", ".join(unknown))
    if operation == "apply" and not names and not all_names:
        raise InputError("Apply requires container names or --all.")
    return tuple(by_name[name] for name in sorted(names)) if names else specs


def run_command(command: Command, action: str) -> str:
    try:
        result = subprocess.run(command.argv, input=command.stdin, text=True, capture_output=True, check=False)
    except (OSError, UnicodeError) as exc:
        detail = str(exc)
    else:
        if result.returncode == 0:
            return result.stdout
        detail = result.stderr.strip() or f"exit status {result.returncode}"
    if action == "observation":
        message = ("Rootful Podman inspection failed. Configure noninteractive sudo access or obtain "
                   "an authenticated sudo session in your terminal, then retry.")
    else:
        message = "Rootful Podman command failed. Check noninteractive sudo access and Podman output."
    raise WorkflowError(action + "_error", f"{message} {detail}", command)


def read_json(text: str, description: str, command: Optional[Command] = None):
    try:
        return json.loads(text)
    except (ValueError, TypeError) as exc:
        if command is None:
            raise InputError(f"Invalid {description}: {exc}") from exc
        raise WorkflowError("observation_error", f"Invalid {description}: {exc}", command) from exc


def observe(specs: Tuple[Spec, ...]) -> Mapping[str, Observation]:
    inventory_cmd = Command(SUDO_PODMAN + ("ps", "--all", "--no-trunc", "--format", "json"))
    inventory = read_json(run_command(inventory_cmd, "observation"), "Podman inventory JSON", inventory_cmd)
    if not isinstance(inventory, list):
        raise WorkflowError("observation_error", "Podman inventory must be a JSON array.", inventory_cmd)
    by_name: Dict[str, str] = {}
    for item in inventory:
        if not isinstance(item, dict):
            raise WorkflowError("observation_error", "Podman inventory contains an invalid row.", inventory_cmd)
        container_id, names = item.get("Id"), item.get("Names")
        if (not isinstance(container_id, str) or not container_id or not isinstance(names, list)
                or not names or any(not isinstance(name, str) or not name for name in names)):
            raise WorkflowError("observation_error", "Podman inventory contains an invalid ID or names.", inventory_cmd)
        for name in names:
            if name in by_name:
                raise WorkflowError("observation_error", f"Podman inventory repeats name {name}.", inventory_cmd)
            by_name[name] = container_id
    result: Dict[str, Observation] = {}
    for spec in specs:
        if spec.name not in by_name:
            result[spec.name] = Missing()
            continue
        container_id = by_name[spec.name]
        inspect_cmd = Command(SUDO_PODMAN + ("inspect", "--type", "container", container_id))
        data = read_json(run_command(inspect_cmd, "observation"), "Podman inspect JSON", inspect_cmd)
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise WorkflowError("observation_error", f"Invalid Podman inspection for {spec.name}.", inspect_cmd)
        item = data[0]
        state, config = item.get("State"), item.get("Config")
        if (item.get("Id") != container_id or not isinstance(state, dict)
                or not isinstance(state.get("Running"), bool) or not isinstance(config, dict)):
            raise WorkflowError("observation_error", f"Invalid Podman inspection for {spec.name}.", inspect_cmd)
        if "Labels" not in config:
            raise WorkflowError("observation_error", f"Missing labels field for {spec.name}.", inspect_cmd)
        labels = config["Labels"]
        if labels is not None and not isinstance(labels, dict):
            raise WorkflowError("observation_error", f"Invalid labels for {spec.name}.", inspect_cmd)
        stored_hash = (labels or {}).get("spec-hash")
        if stored_hash is not None and not isinstance(stored_hash, str):
            raise WorkflowError("observation_error", f"Invalid spec-hash for {spec.name}.", inspect_cmd)
        result[spec.name] = Existing(container_id, state["Running"], stored_hash)
    return result


def read_fixture(path: Path, specs: Tuple[Spec, ...]) -> Mapping[str, Observation]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise InputError(f"Cannot read offline fixture {path}: {exc}") from exc
    fixture = read_json(text, "offline fixture JSON")
    if not isinstance(fixture, dict) or type(fixture.get("schema_version")) is not int or fixture["schema_version"] != 1 or not isinstance(fixture.get("containers"), list):
        raise InputError("Offline fixture must have schema_version 1 and a containers list.")
    result: Dict[str, Observation] = {}
    for row in fixture["containers"]:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not NAME_PATTERN.fullmatch(row["name"]):
            raise InputError("Offline fixture contains an invalid name or row.")
        name = row["name"]
        if name in result:
            raise InputError(f"Offline fixture repeats name {name}.")
        state, container_id, stored_hash = row.get("state"), row.get("container_id"), row.get("stored_hash")
        if "container_id" not in row or "stored_hash" not in row:
            raise InputError(f"Offline fixture needs container_id and stored_hash for {name}.")
        if state == "missing" and container_id is None and stored_hash is None:
            result[name] = Missing()
        elif (state in ("running", "stopped") and isinstance(container_id, str) and container_id
              and (stored_hash is None or isinstance(stored_hash, str))):
            result[name] = Existing(container_id, state == "running", stored_hash)
        else:
            raise InputError(f"Invalid offline observation for {name}.")
    missing = [spec.name for spec in specs if spec.name not in result]
    if missing:
        raise InputError("Offline fixture omits selected names: " + ", ".join(missing))
    return result


def plan(specs: Tuple[Spec, ...], observed: Mapping[str, Observation]) -> Plan:
    proposal = []
    for spec in specs:
        observation = observed[spec.name]
        if isinstance(observation, Existing):
            proposal.append(Preserve(spec, observation))
            continue
        uid = str(11000 + ipaddress.IPv4Address(spec.ip).packed[-1])
        run = Command(SUDO_PODMAN + (
            "run", "-d", "--name", spec.name, "--label", f"spec-hash={spec.declared_hash}",
            "--network", "dev2-net", "--ip", spec.ip, "--hostname", spec.hostname,
            "--systemd", "always", "--privileged", "-v", f"vol-{spec.name}:/home",
            "-v", "/sys/fs/cgroup:/sys/fs/cgroup:rw", spec.image,
        ))
        provision = Command(SUDO_PODMAN + ("exec", "-i", spec.name, "bash", "-s", "--", spec.user, uid), PROVISION)
        proposal.append(Create(spec, (run, provision)))
    return tuple(proposal)


def command_data(command: Command) -> dict:
    return {"argv": list(command.argv), "stdin": command.stdin}


def row_data(item: Planned, include_plan: bool) -> dict:
    spec = item.spec
    existing = item.observed if isinstance(item, Preserve) else None
    row = {
        "name": spec.name,
        "state": "missing" if existing is None else "running" if existing.running else "stopped",
        "container_id": existing.container_id if existing else None,
        "desired_hash": spec.declared_hash,
        "stored_hash": existing.declared_hash if existing else None,
        "declaration": ("match" if existing.declared_hash == spec.declared_hash else "drift") if existing else None,
    }
    if include_plan:
        row["action"] = "preserve" if existing else "create"
        row["commands"] = [] if existing else [command_data(command) for command in item.commands]
    return row


def apply(proposal: Plan) -> Tuple[list, Optional[dict], Optional[WorkflowError]]:
    completed = []
    for item in proposal:
        row = row_data(item, True)
        row.update(outcome="preserved", created_id=None, completed_commands=[])
        if isinstance(item, Preserve):
            completed.append(row)
            continue
        created_id = None
        created = False
        for index, command in enumerate(item.commands):
            try:
                output = run_command(command, "mutation")
                if index == 0:
                    created = True
                    row["completed_commands"].append(command_data(command))
                    output_id = output.strip()
                    if not output_id or any(c.isspace() for c in output_id):
                        raise WorkflowError("mutation_error", "Podman created the container but returned an invalid ID.", command)
                    created_id = output_id
                else:
                    row["completed_commands"].append(command_data(command))
            except WorkflowError as exc:
                if not created:
                    exc.message += " Podman may have created the container; inspect its state before retrying."
                partial = {"name": item.spec.name, "creation": "created" if created else "unknown",
                           "created_id": created_id or None, "completed_commands": row["completed_commands"],
                           "failed_command": command_data(command)}
                return completed, partial, exc
        row.update(outcome="created", created_id=created_id)
        completed.append(row)
    return completed, None, None


def print_result(document: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(document, sort_keys=True, ensure_ascii=False))
        return
    if document["source"] == "offline":
        print("OFFLINE fixture: observations are not live container state.")
    for row in document.get("containers", document.get("completed", [])):
        details = f"{row['name']}: {row['state']}"
        if row["declaration"]:
            details += f", declaration {row['declaration']}"
        if "action" in row:
            details += f", {row.get('outcome', row['action'])}"
        print(details)
        if document["operation"] == "plan":
            for command in row["commands"]:
                print("  $ " + shlex.join(command["argv"]))
                if command["stdin"] is not None:
                    print("  stdin:\n" + command["stdin"], end="")
    if document.get("partial"):
        partial = document["partial"]
        if partial["creation"] == "unknown":
            print(f"Creation attempt: {partial['name']} (status unknown). Inspect its state before retrying.")
        else:
            print(f"Partially created: {partial['name']} (ID: {partial['created_id'] or 'unknown'}). Inspect and repair manually.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = Parser(description="Inspect, plan, or apply the container roster.")
    parser.add_argument("operation", nargs="?", choices=("status", "plan", "apply"))
    parser.add_argument("names", nargs="*", help="Exact container names")
    parser.add_argument("--all", action="store_true", help="Select all configured containers")
    parser.add_argument("-c", "--config", default="containers.yaml", help="Roster YAML path")
    parser.add_argument("--offline", metavar="FILE", help="Read explicit observations from a fixture")
    parser.add_argument("--json", action="store_true", help="Print one JSON document")
    arguments = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in arguments
    operation = None
    source = "offline" if "--offline" in arguments or any(a.startswith("--offline=") for a in arguments) else "live"
    document = {"schema_version": 1, "operation": operation, "source": source}
    try:
        args = parser.parse_intermixed_args(arguments)
        if args.operation is None:
            parser.print_help()
            return 0
        operation = args.operation
        document["operation"] = operation
        document["source"] = "offline" if args.offline is not None else "live"
        if operation == "apply" and args.offline is not None:
            raise InputError("Apply cannot use offline observations.")
        specs = select_specs(load_specs(Path(args.config)), args.names, args.all, operation)
        observed = read_fixture(Path(args.offline), specs) if args.offline is not None else observe(specs)
        proposal = plan(specs, observed)
        if operation == "apply":
            completed, partial, error = apply(proposal)
            if error:
                document["completed"] = completed
                if partial is not None:
                    document["partial"] = partial
                raise error
            document["containers"] = completed
        else:
            document["containers"] = [row_data(item, operation == "plan") for item in proposal]
        print_result(document, as_json)
        return 0
    except WorkflowError as exc:
        document["error"] = {"code": exc.code, "message": exc.message,
                             "command": list(exc.command.argv) if exc.command else None}
        if as_json:
            print_result(document, True)
        else:
            print_result(document, False)
        print(exc.message, file=sys.stderr)
        if exc.command:
            print("Command: " + shlex.join(exc.command.argv), file=sys.stderr)
        return 2 if exc.code == "input_error" else 1


if __name__ == "__main__":
    sys.exit(main())
