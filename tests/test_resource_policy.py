import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import resource_policy
import run_dev_containers as launcher


ROOT = Path(__file__).resolve().parents[1]


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads((ROOT / "resource-policy.example.json").read_text())
        self.policy = resource_policy.Policy(self.payload)

    def test_swap_interface_is_ram_plus_swap_and_other_mounts_are_bounded(self):
        options = self.policy.options("dev1")
        limit = self.policy.limits("dev1")
        self.assertEqual(int(options[options.index("--memory-swap") + 1]),
                         limit["memory_max"] + limit["swap_max"])
        self.assertEqual(options[options.index("--shm-size-systemd") + 1], "268435456")
        self.assertIn("type=bind,src=/home/podman/dev2-tmp/dev1,dst=/tmp", options)
        self.assertNotIn("/sys/fs/cgroup:/sys/fs/cgroup:rw", options)
        self.assertEqual(options[options.index("--image-volume") + 1], "ignore")
        self.assertIn("MemorySwapMax=17179869184", self.policy.slice_unit())

    def test_effective_hash_changes_with_resource_limits(self):
        spec = {"name": "dev1", "ip": "192.168.4.151"}
        first = launcher.spec_hash(launcher.effective_spec(spec, self.policy))
        payload = copy.deepcopy(self.payload)
        payload["defaults"]["memory_max"] += 1024
        second = launcher.spec_hash(launcher.effective_spec(spec, resource_policy.Policy(payload)))
        self.assertNotEqual(first, second)

    def test_rejects_unlimited_misspelled_boolean_and_inverted_limits(self):
        for key, value in (("memory_max", 0), ("memory_max", True),
                           ("memory_high", 2 ** 40), ("memry_max", 1024)):
            with self.subTest(key=key, value=value):
                payload = copy.deepcopy(self.payload)
                payload["defaults"][key] = value
                with self.assertRaises(ValueError):
                    resource_policy.Policy(payload)

    def test_rejects_mount_and_slice_option_injection(self):
        for key, value in (("tmp_root", "/home/tmp,ro"), ("tmp_root", "relative")):
            payload = copy.deepcopy(self.payload)
            payload[key] = value
            with self.assertRaises(ValueError):
                resource_policy.Policy(payload)
        with self.assertRaises(ValueError):
            self.policy.options("../../other")

    def test_proposal_cannot_pass_preflight(self):
        with self.assertRaisesRegex(ValueError, "proposal"):
            self.policy.preflight([])

    def test_approved_pool_cannot_consume_the_host_reserve(self):
        with tempfile.TemporaryDirectory() as temporary:
            payload = copy.deepcopy(self.payload)
            payload["approved"] = True
            meminfo = Path(temporary) / "meminfo"
            meminfo.write_text("MemTotal: 1024 kB\n")
            with self.assertRaisesRegex(ValueError, "host reserve"):
                resource_policy.Policy(payload).preflight([], meminfo=meminfo)

    def fixture_preflight(self, temporary):
        root = Path(temporary)
        payload = copy.deepcopy(self.payload)
        payload["approved"] = True
        payload["tmp_root"] = str(root / "tmp")
        directory = root / "tmp/dev1"
        directory.mkdir(parents=True)
        directory.chmod(0o1777)
        meminfo = root / "meminfo"
        meminfo.write_text("MemTotal: 263235384 kB\n")
        cgroups = root / "cgroups/dev2.slice"
        cgroups.mkdir(parents=True)
        for name, value in (("memory.high", payload["pool"]["memory_high"]),
                            ("memory.max", payload["pool"]["memory_max"]),
                            ("memory.swap.max", payload["pool"]["swap_max"])):
            (cgroups / name).write_text(str(value))
        mounts = root / "mountinfo"
        mounts.write_text("1 0 8:1 / / rw - xfs /dev/test rw\n")
        return resource_policy.Policy(payload), {
            "meminfo": meminfo, "cgroup_root": cgroups.parent, "mountinfo": mounts}

    def test_preflight_checks_disk_parent_and_host_reserve_without_mutations(self):
        with tempfile.TemporaryDirectory() as temporary:
            policy, paths = self.fixture_preflight(temporary)
            # Unit fixtures belong to the current test UID. Model root ownership only.
            real_stat = Path.stat
            real_lstat = Path.lstat
            def owned(method):
                def result(path, *args, **kwargs):
                    value = list(method(path, *args, **kwargs))
                    value[4] = 0
                    return type(method(path, *args, **kwargs))(value)
                return result
            with patch.object(Path, "stat", owned(real_stat)), patch.object(Path, "lstat", owned(real_lstat)):
                policy.preflight([{"name": "dev1"}], **paths)
                paths["mountinfo"].write_text("1 0 8:1 / / rw - xfs /dev/test rw\n"
                    f"2 1 0:1 / {policy.tmp_root / 'dev1'} rw - tmpfs tmpfs rw\n")
                with self.assertRaisesRegex(ValueError, "disk filesystem"):
                    policy.preflight([{"name": "dev1"}], **paths)
                paths["mountinfo"].write_text("1 0 0:1 / / rw - tmpfs tmpfs rw\n")
                with self.assertRaisesRegex(ValueError, "disk filesystem"):
                    policy.preflight([{"name": "dev1"}], **paths)
                paths["mountinfo"].write_text("1 0 8:1 / / rw - xfs /dev/test rw\n")
                (paths["cgroup_root"] / "dev2.slice/memory.max").write_text("max")
                with self.assertRaisesRegex(ValueError, "active pool"):
                    policy.preflight([{"name": "dev1"}], **paths)

    def test_audit_lists_drift_unmanaged_and_missing_containers(self):
        result = self.policy.audit([{"name": "dev1"}, {"name": "missing"}],
            [{"Name": "/dev1", "HostConfig": {"Memory": 0}, "Mounts": []},
             {"Name": "/unmanaged", "HostConfig": {}}])
        self.assertEqual([r["status"] for r in result], ["drift", "missing", "outside-roster"])
        self.assertIn("disk-backed /tmp bind", result[0]["differences"])


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.policy_file = ROOT / "resource-policy.example.json"
        self.args = ["--config", str(ROOT / "containers.yaml"),
                     "--resource-policy", str(self.policy_file), "--only", "vimkim1"]

    def test_dry_run_never_invokes_subprocess_or_inspects_containers(self):
        with patch.object(launcher.subprocess, "run", side_effect=AssertionError("unexpected process")), \
             redirect_stdout(io.StringIO()) as output:
            launcher.main(self.args + ["--dry-run"])
        preview = output.getvalue()
        self.assertIn("podman run", preview)
        self.assertIn("dst=/tmp", preview)
        self.assertNotIn("/sys/fs/cgroup:/sys/fs/cgroup:rw", preview)

    def test_unapproved_policy_fails_before_any_podman_call(self):
        with patch.object(launcher.subprocess, "run", side_effect=AssertionError("unexpected process")):
            with self.assertRaisesRegex(ValueError, "proposal"):
                launcher.main(self.args)

    def test_existing_container_is_not_recreated_or_updated(self):
        with patch.object(resource_policy.Policy, "preflight"), \
             patch.object(launcher, "container_exists", return_value=True), \
             patch.object(launcher, "current_hash", return_value="old"), \
             patch.object(launcher, "run_container", side_effect=AssertionError("recreated")), \
             redirect_stdout(io.StringIO()) as output:
            launcher.main(self.args)
        self.assertIn("No action taken", output.getvalue())

    def test_podman_access_error_is_not_treated_as_missing(self):
        error = launcher.subprocess.CalledProcessError(125, ["podman"])
        with patch.object(launcher, "sh", side_effect=error):
            with self.assertRaises(launcher.subprocess.CalledProcessError):
                launcher.container_exists("dev1")

    def test_offline_audit_never_invokes_subprocess(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "inspect.json"
            path.write_text('[{"Name":"/vimkim1","HostConfig":{}}]')
            with patch.object(launcher.subprocess, "run", side_effect=AssertionError("unexpected process")), \
                 redirect_stdout(io.StringIO()) as output:
                launcher.main(self.args + ["--audit", "--inspect-json", str(path)])
            self.assertEqual(json.loads(output.getvalue())[0]["status"], "drift")


if __name__ == "__main__":
    unittest.main()
