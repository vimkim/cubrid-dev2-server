import fcntl
import hashlib
import json
import os
import pty
import select
import subprocess
import sys
import tempfile
import termios
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "run_dev_containers.py"
FAKE = r'''#!/usr/bin/env python3
import json
import os
import subprocess
import sys

program = os.path.basename(sys.argv[0])
args = sys.argv[1:]
path = os.environ["FAKE_STATE"]
log = os.environ["FAKE_LOG"]
with open(log, "a", encoding="utf-8") as stream:
    stream.write(json.dumps({"program": program, "args": args}) + "\n")
with open(path, encoding="utf-8") as stream:
    state = json.load(stream)

def save():
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(state, stream)

def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)

failure = os.environ.get("FAKE_FAIL", "")
if program == "sudo":
    if failure == "sudo":
        fail("sudo: a password is required")
    if args[:3] == ["-n", "--", "podman"]:
        command = args[3:]
    elif args[:2] == ["--", "podman"]:
        command = args[2:]
    else:
        fail("expected rootful Podman through sudo")
    if os.environ.get("FAKE_AUTH_NEEDED"):
        if "-n" in args:
            fail("sudo: a password is required")
        terminal = os.open("/dev/tty", os.O_RDWR)
        os.write(terminal, b"[sudo] password: ")
        password = os.read(terminal, 1024)
        os.close(terminal)
        if password != b"test-password\n":
            fail("sudo: authentication failed")
    os.execvp("podman", ["podman"] + command)

containers = state["containers"]
if program == "podman":
    if args[0] == "ps":
        if failure == "inventory":
            fail("podman inventory failed")
        if failure == "inventory_json":
            print("not json")
        elif failure == "inventory_shape":
            print(json.dumps([{"Id": "broken"}]))
        else:
            print(json.dumps([{"Id": item["id"], "Names": [name]} for name, item in sorted(containers.items())]))
    elif args[0] == "inspect":
        if failure == "inspect":
            fail("podman inspect failed")
        if failure == "inspect_json":
            print("invalid")
        else:
            item = next((value for value in containers.values() if value["id"] == args[-1]), None)
            if item is None:
                fail("unknown container ID")
            container_id = "changed-id" if failure == "inspect_id" else item["id"]
            config = {} if failure == "inspect_labels_missing" else {"Labels": {"spec-hash": item["hash"]} if item["hash"] is not None else None}
            print(json.dumps([{"Id": container_id, "State": {"Running": item["running"]}, "Config": config}]))
    elif args[0] == "run":
        if failure == "run":
            fail("creation failed")
        name = args[args.index("--name") + 1]
        if name in containers:
            fail("name is already in use")
        label = args[args.index("--label") + 1]
        containers[name] = {"id": "created-" + name, "running": True, "hash": label.split("=", 1)[1]}
        save()
        if failure == "run_after_create":
            containers[name]["running"] = False
            save()
            fail("start failed after creation")
        print("bad ID" if failure == "run_bad_id" else "created-" + name)
    elif args[0] == "exec":
        if failure == "provision":
            fail("account setup failed")
        name = args[2]
        if name not in containers:
            fail("container missing")
        script = sys.stdin.read()
        result = subprocess.run(["/bin/bash", "-s", "--"] + args[6:], input=script, text=True)
        sys.exit(result.returncode)
    else:
        fail("unexpected podman command")
    sys.exit(0)

if program == "getent":
    sys.exit(0 if args[1] in state["groups"] else 1)
if program == "id":
    sys.exit(0 if args[1] in state["users"] else 1)
if program == "groupadd":
    state["groups"][args[1]] = args[2]
elif program == "useradd":
    state["users"][args[-1]] = {"uid": args[args.index("-u") + 1], "gid": args[args.index("-g") + 1],
                                "shell": args[args.index("-s") + 1]}
elif program == "chpasswd":
    user, password = sys.stdin.read().strip().split(":", 1)
    state["users"][user]["password"] = password
elif program == "usermod":
    state["users"][args[-1]]["wheel"] = True
else:
    fail("unexpected account command")
save()
'''


class ContainerCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="container workflow ")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bin = self.directory / "fake bin"
        self.bin.mkdir()
        fake = self.bin / "fake"
        fake.write_text(FAKE, encoding="utf-8")
        fake.chmod(0o755)
        for name in ("sudo", "podman", "getent", "id", "groupadd", "useradd", "chpasswd", "usermod"):
            (self.bin / name).symlink_to(fake)
        self.state_path = self.directory / "state.json"
        self.log_path = self.directory / "calls.jsonl"
        self.write_state({"containers": {}, "groups": {}, "users": {}})
        self.entries = [
            {"name": "alpha", "ip": "192.168.4.101", "user": "alice"},
            {"name": "bravo", "ip": "192.168.4.102", "user": "bob"},
            {"name": "charlie", "ip": "192.168.4.103", "user": "carol"},
            {"name": "delta", "ip": "192.168.4.104", "user": "dave"},
        ]
        self.config = self.directory / "roster with spaces.yaml"
        self.write_config(self.entries)
        self.env = os.environ.copy()
        self.env.update(PATH=str(self.bin) + os.pathsep + self.env["PATH"],
                        FAKE_STATE=str(self.state_path), FAKE_LOG=str(self.log_path))

    def write_state(self, state):
        self.state_path.write_text(json.dumps(state), encoding="utf-8")

    def state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def write_config(self, entries):
        self.config.write_text(json.dumps({"containers": entries}), encoding="utf-8")

    def calls(self):
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]

    def cli(self, operation, *args, failure=None):
        env = dict(self.env)
        if failure:
            env["FAKE_FAIL"] = failure
        return subprocess.run([sys.executable, str(CLI), operation, "--config", str(self.config), "--json", *args],
                              cwd=ROOT, env=env, text=True, capture_output=True)

    def recipe(self, operation, *args, failure=None):
        env = dict(self.env)
        if failure:
            env["FAKE_FAIL"] = failure
        return subprocess.run(["just", operation, "--config", str(self.config), "--json", *args],
                              cwd=ROOT, env=env, text=True, capture_output=True)

    def mutations(self):
        return [call for call in self.calls() if call["program"] == "podman" and call["args"][0] in ("run", "exec")]

    def assert_success(self, process):
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def mixed_state(self):
        desired = hashlib.sha256(json.dumps(self.entries[1], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.write_state({"containers": {
            "bravo": {"id": "stable-bravo", "running": True, "hash": desired},
            "charlie": {"id": "stable-charlie", "running": False, "hash": "old"},
            "delta": {"id": "stable-delta", "running": True, "hash": None},
        }, "groups": {}, "users": {}})

    def test_status_and_plan_report_mixed_state_without_mutation(self):
        self.mixed_state()
        status = self.assert_success(self.cli("status"))
        self.assertEqual((status["schema_version"], status["source"], status["operation"]), (1, "live", "status"))
        self.assertEqual([(row["name"], row["state"], row["declaration"]) for row in status["containers"]], [
            ("alpha", "missing", None), ("bravo", "running", "match"),
            ("charlie", "stopped", "drift"), ("delta", "running", "drift")])
        plan = self.assert_success(self.cli("plan"))
        self.assertEqual([row["action"] for row in plan["containers"]], ["create", "preserve", "preserve", "preserve"])
        self.assertEqual([row["commands"] for row in plan["containers"][1:]], [[], [], []])
        self.assertEqual(self.mutations(), [])
        inspected = [call["args"][-1] for call in self.calls() if call["program"] == "podman" and call["args"][0] == "inspect"]
        self.assertEqual(inspected, ["stable-bravo", "stable-charlie", "stable-delta"] * 2)

    def test_terminal_prompts_for_sudo_and_preserves_provisioning_input(self):
        for operation, prompts in (("status", 1), ("plan", 1), ("apply", 3)):
            with self.subTest(operation=operation):
                master, terminal = pty.openpty()
                self.addCleanup(os.close, master)
                self.addCleanup(os.close, terminal)
                settings = termios.tcgetattr(terminal)
                settings[3] &= ~termios.ECHO
                termios.tcsetattr(terminal, termios.TCSANOW, settings)

                def attach_terminal():
                    os.setsid()
                    fcntl.ioctl(0, termios.TIOCSCTTY, 0)

                process = subprocess.Popen(
                    ["just", operation, "alpha", "--config", str(self.config), "--json"],
                    cwd=ROOT, env=dict(self.env, FAKE_AUTH_NEEDED="1"), stdin=terminal,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    preexec_fn=attach_terminal)
                self.addCleanup(process.kill)
                os.write(master, b"test-password\n" * prompts)
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertEqual(json.loads(stdout)["operation"], operation)
                self.assertTrue(select.select([master], [], [], 1)[0], "Missing sudo prompt")
                self.assertEqual(os.read(master, 4096).count(b"[sudo] password: "), prompts)
                if operation != "apply":
                    self.assertEqual(self.mutations(), [])
                else:
                    self.assertEqual(self.state()["users"]["alice"]["password"], "changeme")

    def test_without_terminal_sudo_fails_without_prompting_or_mutation(self):
        self.env["FAKE_AUTH_NEEDED"] = "1"
        result = self.cli("plan", "alpha")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error"]["code"], "observation_error")
        self.assertIn("sudo: a password is required", result.stderr)
        self.assertNotIn("containers", payload)
        self.assertEqual(self.mutations(), [])

    def test_apply_creates_only_selected_then_preserves_existing(self):
        self.mixed_state()
        before = self.state()["containers"].copy()
        preview = self.assert_success(self.cli("plan", "charlie", "alpha"))
        result = self.assert_success(self.cli("apply", "charlie", "alpha"))
        self.assertEqual([(row["name"], row["outcome"]) for row in result["containers"]],
                         [("alpha", "created"), ("charlie", "preserved")])
        planned = preview["containers"][0]["commands"]
        actual = self.mutations()
        self.assertEqual([call["args"] for call in actual], [command["argv"][4:] for command in planned])
        run = actual[0]["args"]
        self.assertEqual(run, ["run", "-d", "--name", "alpha", "--label", "spec-hash=" + preview["containers"][0]["desired_hash"],
                               "--network", "dev2-net", "--ip", "192.168.4.101", "--hostname", "alpha", "--systemd", "always",
                               "--privileged", "-v", "vol-alpha:/home", "-v", "/sys/fs/cgroup:/sys/fs/cgroup:rw",
                               "localhost/local/r8-systemd:250708-ubi-init"])
        state = self.state()
        for name, item in before.items():
            self.assertEqual(state["containers"][name], item)
        self.assertEqual(state["users"]["alice"], {"uid": "11101", "gid": "11101", "shell": "/bin/bash",
                                                   "password": "changeme", "wheel": True})
        self.assertEqual(state["groups"]["11101"], "alice")
        count = len(self.mutations())
        repeated = self.assert_success(self.cli("apply", "--all"))
        self.assertEqual([(row["name"], row["outcome"]) for row in repeated["containers"]],
                         [(name, "preserved") for name in ("alpha", "bravo", "charlie", "delta")])
        self.assertEqual(len(self.mutations()), count)

    def test_existing_numeric_group_is_reused(self):
        state = self.state()
        state["groups"]["11101"] = "shared"
        self.write_state(state)
        self.assert_success(self.cli("apply", "alpha"))
        self.assertEqual(self.state()["groups"]["11101"], "shared")
        self.assertEqual(self.state()["users"]["alice"]["gid"], "11101")
        self.assertNotIn("groupadd", [call["program"] for call in self.calls()])

    def test_scope_errors_precede_subprocesses(self):
        for arguments in ((), ("--all", "alpha"), ("alpha", "alpha"), ("nobody",)):
            with self.subTest(arguments=arguments):
                result = self.cli("apply", *arguments)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(json.loads(result.stdout)["error"]["code"], "input_error")
        self.assertEqual(self.calls(), [])

    def test_offline_requires_every_selected_observation_and_is_deterministic(self):
        fixture = self.directory / "snapshot.json"
        fixture.write_text(json.dumps({"schema_version": 1, "containers": [
            {"name": "alpha", "state": "missing", "container_id": None, "stored_hash": None},
            {"name": "bravo", "state": "stopped", "container_id": "fixture-id", "stored_hash": None},
        ]}), encoding="utf-8")
        first = self.cli("plan", "bravo", "alpha", "--offline", str(fixture))
        second = self.cli("plan", "alpha", "bravo", "--offline", str(fixture))
        self.assertEqual(first.stdout, second.stdout)
        payload = self.assert_success(first)
        self.assertEqual(payload["source"], "offline")
        self.assertEqual([(row["name"], row["state"]) for row in payload["containers"]],
                         [("alpha", "missing"), ("bravo", "stopped")])
        omitted = self.cli("status", "--offline", str(fixture))
        self.assertEqual(omitted.returncode, 2)
        self.assertNotIn("containers", json.loads(omitted.stdout))
        rejected = self.cli("apply", "alpha", "--offline", str(fixture))
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(self.cli("status", "alpha", "--offline", "").returncode, 2)
        self.assertEqual(self.cli("apply", "alpha", "--offline", "").returncode, 2)
        self.assertEqual(self.cli("apply", "alpha", "--offline=").returncode, 2)
        self.assertEqual(self.calls(), [])
        plain = subprocess.run([sys.executable, str(CLI), "status", "alpha", "--config", str(self.config),
                                "--offline", str(fixture)], env=self.env, cwd=ROOT, text=True, capture_output=True)
        self.assertTrue(plain.stdout.startswith("OFFLINE fixture:"))

    def test_backend_errors_never_become_missing_and_preflight_all_selected(self):
        self.mixed_state()
        for failure in ("sudo", "inventory", "inventory_json", "inventory_shape", "inspect", "inspect_json", "inspect_id", "inspect_labels_missing"):
            with self.subTest(failure=failure):
                result = self.cli("apply", "alpha", "bravo", failure=failure)
                self.assertEqual(result.returncode, 1, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["error"]["code"], "observation_error")
                self.assertNotIn("containers", payload)
                self.assertEqual(self.mutations(), [])
                self.assertTrue(result.stderr.strip())
        self.assertIn("noninteractive sudo", self.cli("status", failure="sudo").stderr)

    def test_partial_provisioning_failure_reports_created_container_and_retry_preserves(self):
        result = self.cli("apply", "alpha", "bravo", failure="provision")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error"]["code"], "mutation_error")
        self.assertEqual(payload["completed"], [])
        self.assertEqual(payload["partial"]["name"], "alpha")
        self.assertEqual(payload["partial"]["creation"], "created")
        self.assertEqual(payload["partial"]["created_id"], "created-alpha")
        self.assertEqual(len(payload["partial"]["completed_commands"]), 1)
        self.assertEqual(payload["partial"]["failed_command"]["argv"][4], "exec")
        self.assertNotIn("bravo", self.state()["containers"])
        self.assertNotIn("alice", self.state()["users"])
        count = len(self.mutations())
        retry = self.assert_success(self.cli("apply", "alpha"))
        self.assertEqual(retry["containers"][0]["outcome"], "preserved")
        self.assertEqual(len(self.mutations()), count)

    def test_failed_run_may_leave_a_container_and_retry_preserves_it(self):
        result = self.cli("apply", "alpha", failure="run_after_create")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["partial"]["creation"], "unknown")
        self.assertIsNone(payload["partial"]["created_id"])
        self.assertEqual(payload["partial"]["completed_commands"], [])
        self.assertIn("inspect", result.stderr.lower())
        self.assertFalse(self.state()["containers"]["alpha"]["running"])
        count = len(self.mutations())
        retry = self.assert_success(self.cli("apply", "alpha"))
        self.assertEqual(retry["containers"][0]["outcome"], "preserved")
        self.assertEqual(retry["containers"][0]["state"], "stopped")
        self.assertEqual(len(self.mutations()), count)

        self.write_state({"containers": {}, "groups": {}, "users": {}})
        env = dict(self.env, FAKE_FAIL="run_after_create")
        text_result = subprocess.run([sys.executable, str(CLI), "apply", "alpha", "--config", str(self.config)],
                                     cwd=ROOT, env=env, text=True, capture_output=True)
        self.assertEqual(text_result.returncode, 1)
        self.assertIn("status unknown", text_result.stdout)
        self.assertNotIn("Partially created", text_result.stdout)

    def test_bad_creation_output_reports_that_creation_completed(self):
        result = self.cli("apply", "alpha", failure="run_bad_id")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["partial"]["creation"], "created")
        self.assertIsNone(payload["partial"]["created_id"])
        self.assertEqual(len(payload["partial"]["completed_commands"]), 1)
        self.assertNotIn("alice", self.state()["users"])

    def test_partial_report_includes_prior_results(self):
        self.mixed_state()
        state = self.state()
        del state["containers"]["delta"]
        self.write_state(state)
        result = self.cli("apply", "bravo", "delta", failure="provision")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual([(row["name"], row["outcome"]) for row in payload["completed"]],
                         [("bravo", "preserved")])
        self.assertEqual(payload["partial"]["name"], "delta")

    def test_invalid_config_and_offline_rows_are_rejected(self):
        for value in ("not a mapping", "{}", '{"containers": [null]}',
                      '{"containers": [{"name": "-bad", "ip": "192.168.4.1"}]}',
                      '{"containers": [{"name": "ok", "ip": "not-ip"}]}',
                      '{"containers": [{"name": "a", "ip": "192.168.4.1"}, {"name": "a", "ip": "192.168.4.2"}]}',
                      '{"containers": [{"name": "a", "ip": "192.168.4.1"}, {"name": "b", "ip": "192.168.4.1"}]}',
                      '{"containers": [{"name": "a", "ip": "192.168.4.1", "user": "bad;id"}]}',
                      '{"containers": [{"name": "a", "ip": "192.168.4.1", "image": "bad\\u0000image"}]}'):
            with self.subTest(value=value):
                self.config.write_text(value, encoding="utf-8")
                result = self.cli("status")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn("containers", json.loads(result.stdout))
        self.write_config(self.entries)
        fixture = self.directory / "bad.json"
        for row in ({"name": "alpha", "state": "missing"},
                    {"name": "alpha", "state": "unknown", "container_id": None, "stored_hash": None},
                    {"name": "alpha", "state": "missing", "container_id": "wrong", "stored_hash": None}):
            fixture.write_text(json.dumps({"schema_version": 1, "containers": [row]}), encoding="utf-8")
            self.assertEqual(self.cli("plan", "alpha", "--offline", str(fixture)).returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_hash_uses_complete_raw_entry_before_defaults(self):
        entry = {"name": "alpha", "ip": "192.168.4.101", "custom": "kept in hash"}
        self.write_config([entry])
        fixture = self.directory / "one.json"
        fixture.write_text(json.dumps({"schema_version": 1, "containers": [
            {"name": "alpha", "state": "missing", "container_id": None, "stored_hash": None}]}), encoding="utf-8")
        first = self.assert_success(self.cli("plan", "--offline", str(fixture)))["containers"][0]
        self.assertEqual(first["desired_hash"], hashlib.sha256(json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        entry["image"] = "localhost/local/r8-systemd:250708-ubi-init"
        self.write_config([entry])
        second = self.assert_success(self.cli("plan", "--offline", str(fixture)))["containers"][0]
        self.assertNotEqual(first["desired_hash"], second["desired_hash"])
        self.assertEqual(first["commands"][0]["argv"][-1], second["commands"][0]["argv"][-1])

    def test_disabled_entries_remain_visible_but_bulk_operations_skip_them(self):
        self.entries[1]["enabled"] = False
        self.entries[2]["enabled"] = True
        self.entries[3]["enabled"] = False
        self.write_config(self.entries)
        existing = {"id": "disabled-bravo", "running": True, "hash": "old"}
        self.write_state({"containers": {"bravo": existing}, "groups": {}, "users": {}})

        status = self.assert_success(self.cli("status"))["containers"]
        self.assertEqual([(row["name"], row["enabled"]) for row in status],
                         [("alpha", True), ("bravo", False), ("charlie", True), ("delta", False)])
        self.assertEqual(status[1]["state"], "running")
        planned = self.assert_success(self.cli("plan", "--all"))["containers"]
        self.assertEqual([row["name"] for row in planned], ["alpha", "charlie"])
        self.assertEqual(self.mutations(), [])

        applied = self.assert_success(self.cli("apply", "--all"))["containers"]
        self.assertEqual([(row["name"], row["outcome"]) for row in applied],
                         [("alpha", "created"), ("charlie", "created")])
        self.assertEqual(self.state()["containers"]["bravo"], existing)
        self.assertNotIn("delta", self.state()["containers"])
        self.assertNotIn("bob", self.state()["users"])
        self.assertNotIn("dave", self.state()["users"])
        plain = subprocess.run([sys.executable, str(CLI), "status", "bravo", "--config", str(self.config)],
                               cwd=ROOT, env=self.env, text=True, capture_output=True)
        self.assertEqual(plain.returncode, 0, plain.stderr)
        self.assertIn("disabled", plain.stdout)

    def test_explicit_disabled_names_fail_before_podman(self):
        self.entries[1]["enabled"] = False
        self.write_config(self.entries)
        for operation in ("plan", "apply"):
            for names in (("bravo",), ("alpha", "bravo")):
                with self.subTest(operation=operation, names=names):
                    result = self.cli(operation, *names)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    error = json.loads(result.stdout)["error"]
                    self.assertEqual(error["code"], "input_error")
                    self.assertIn("bravo", error["message"])
        self.assertEqual(self.calls(), [])

    def test_disabled_only_bulk_operations_do_not_need_podman(self):
        self.write_config([dict(entry, enabled=False) for entry in self.entries])
        for operation in ("plan", "apply"):
            payload = self.assert_success(self.cli(operation, "--all", failure="sudo"))
            self.assertEqual(payload["containers"], [])
        self.assertEqual(self.calls(), [])

    def test_enabled_requires_a_boolean_and_disabled_entries_are_validated(self):
        for value in (None, 0, 1, "false", "true", [], {}):
            with self.subTest(enabled=value):
                self.write_config([dict(self.entries[0], enabled=value)])
                result = self.cli("apply", "--all")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("enabled", json.loads(result.stdout)["error"]["message"])
        self.write_config([dict(self.entries[0], enable=False)])
        self.assertEqual(self.cli("apply", "--all").returncode, 2)
        self.write_config([dict(self.entries[0], enabled=False, ip="invalid")])
        self.assertEqual(self.cli("apply", "--all").returncode, 2)
        self.write_config([self.entries[0], dict(self.entries[1], enabled=False, ip=self.entries[0]["ip"])])
        self.assertEqual(self.cli("apply", "--all").returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_just_recipes_forward_exact_arguments_and_apply_alias(self):
        injection_target = self.directory / "must not exist"
        injection = "$(touch '" + str(injection_target) + "')"
        result = self.recipe("plan", injection)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(injection_target.exists())
        self.assertEqual(self.calls(), [])
        self.assert_success(self.recipe("plan", "alpha"))
        self.assertEqual(self.mutations(), [])
        self.assert_success(self.recipe("run-containers", "alpha"))
        self.assertEqual([call["args"][0] for call in self.mutations()], ["run", "exec"])
        self.assertNotIn("bravo", self.state()["containers"])
        self.assertEqual(self.recipe("apply").returncode, 2)
        self.assertEqual(self.assert_success(self.recipe("status", "alpha"))["containers"][0]["state"], "running")
        self.assertEqual(self.assert_success(self.recipe("apply", "bravo"))["containers"][0]["outcome"], "created")

    def test_default_commands_list_help_without_observation(self):
        direct = subprocess.run([sys.executable, str(CLI)], cwd=ROOT, env=self.env, text=True, capture_output=True)
        recipes = subprocess.run(["just"], cwd=ROOT, env=self.env, text=True, capture_output=True)
        self.assertEqual(direct.returncode, 0, direct.stderr)
        self.assertIn("{status,plan,apply}", direct.stdout)
        self.assertEqual(recipes.returncode, 0, recipes.stderr)
        self.assertIn("status *args", recipes.stdout)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
