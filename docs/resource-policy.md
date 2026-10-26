# Container resource policy and disk-backed /tmp

Repository integration approved on 2026-10-26. No host change accompanies this patch.

The launcher applies runtime controls when it creates a container. Image settings alone cannot apply these controls.
Existing containers remain unchanged. The launcher reports spec drift and never recreates a container automatically.

## Proposed budget

The example policy is a proposal. Its `approved` field is `false`.
The launcher requires a reviewed `resource-policy.json` before it performs reconciliation.
There is no fallback to unlimited creation when that file is absent.

| Control | Proposed value | Purpose |
| --- | --- | --- |
| Host reserve used by preflight | 64 GiB | Reject a pool budget that consumes this reserve |
| Shared `dev2.slice` MemoryHigh | 160 GiB | Apply reclaim pressure before the pool ceiling |
| Shared `dev2.slice` MemoryMax | 176 GiB | Bound concurrent container RAM charges |
| Shared `dev2.slice` MemorySwapMax | 16 GiB | Bound aggregate container swap |
| Default container CPU quota | 8 CPU equivalents | Bound each container's CPU time |
| Default container memory.high / memory.max | 16 / 24 GiB | Bound each container within the pool |
| Default container swap maximum | 2 GiB | Limit each container's swap allocation |
| `lht1199-1` memory.high / memory.max | 24 / 32 GiB | Allow headroom above its observed 11.60 GiB anonymous allocation |
| `/dev/shm` capacity | 256 MiB | Bound the default IPC tmpfs |
| Each systemd tmpfs capacity | 256 MiB | Bound automatic `/run`, journal, and related tmpfs mounts |
| `/tmp` | A separate disk directory per container | Remove accidental RAM storage of database files |

The server reports 251.04 GiB RAM and approximately 36 GiB swap.
A 176 GiB pool leaves about 75.04 GiB physical capacity outside the pool.
This is a budget, not a kernel reservation for operational services.
Host workloads and containers outside `dev2.slice` can still consume that capacity.

These values need representative workload measurements before deployment approval.
A snapshot at 2026-10-23 18:04:01 KST records 35 container cgroups and approximately 47.76 GiB anonymous memory.
The same snapshot records 157.48 GiB file memory and 14.41 GiB swap.
File memory includes shmem. Do not add those overlapping values.
One container already has approximately 13.59 GiB swap, above the proposed 2 GiB limit.
Do not apply the new limit to that running container without workload coordination.

The sum of individual ceilings exceeds the pool ceiling. Concurrent containers share the pool.
Per-container ceilings provide no guaranteed allocation or equal share per developer.
Developers with several containers can consume more of the pool.
Per-developer slices remain a possible later policy decision.

The `cpus` field accepts finite counts of at least 0.01, including fractional values.
It maps to Podman's `--cpus` quota and participates in spec hashing and drift audits.
Each container can override its quota through the policy's `overrides` map.
CPU quotas can run across available processors. They do not establish dedicated processor allocations.
The example's 8-CPU quota remains a proposal and needs workload measurements before deployment approval.

## Preview and audit

The launcher needs PyYAML, as it did before this change. The tests use Python's standard-library test runner.
On dev2, `/usr/bin/python3` provides PyYAML. The current user-selected Python does not.
The `just` recipes default to `/usr/bin/python3`. Set `DEV2_PYTHON` to select another interpreter with PyYAML.

Preview one creation without sudo, Podman, host inspection, or host writes:

```bash
/usr/bin/python3 -B run_dev_containers.py \
  --resource-policy resource-policy.example.json --only vimkim1 --dry-run
```

This preview does not establish whether a container exists or whether preflight will pass.

Compare the policy with rootful Podman metadata without changing containers:

```bash
/usr/bin/python3 -B run_dev_containers.py \
  --resource-policy resource-policy.example.json --audit
```

The live audit uses noninteractive sudo. A password requirement causes an explicit failure.
For an offline audit, supply a private file that contains only a Podman inspect JSON array:

```bash
/usr/bin/python3 -B run_dev_containers.py \
  --resource-policy resource-policy.example.json --audit --inspect-json INSPECT.json
```

Keep inspect files in the investigation repository's private `evidence/` directory.
An inspect match does not prove the live memory.high value or mount capacity.
Check actual cgroups, namespaces, and mount types during canary acceptance.

Render the proposed persistent slice configuration without installing it:

```bash
/usr/bin/python3 -B resource_policy.py \
  --policy resource-policy.example.json --render-slice
```

## Storage enforcement

Each new container receives a bind mount from `/home/podman/dev2-tmp/NAME` to `/tmp`.
The launcher checks that the source directory belongs to root and has mode `1777`.
Its parent must belong to root and exclude group and other write access.
The launcher accepts XFS, ext4, or Btrfs as the backing filesystem.
It checks the longest matching mount in the host's mount table.
It rejects a missing directory, a symlink at the container directory, and tmpfs backing.

The deployment must create and check these directories before reconciliation.
The bind source is separate from `vol-NAME:/home` and survives container recreation.
Temporary data therefore persists until a later explicit cleanup.
Disk capacity and inode monitoring are required. This change does not impose a disk quota.
Linux can cache disk-backed files in RAM. This cache remains subject to the cgroup RAM ceiling.

The launcher removes the explicit writable host `/sys/fs/cgroup` bind mount.
It requests a private cgroup namespace and lets Podman provide the systemd cgroup mount.
The Rocky image declares `/sys/fs/cgroup` as an image volume.
The policy ignores image-declared anonymous volumes so they cannot obscure that mount.
The explicit `/home` volume and `/tmp` bind remain in the creation command.
Review other image-declared storage before using a custom image.
Check systemd, SSH, builds, and native test runners in a disposable canary before migration.

The user permits intentional tmpfs creation. The policy does not prohibit it.
Privileged container administrators can remount filesystems or interfere with controls.
These controls assume trusted administrators. They do not provide containment against hostile container root.
Avoid claiming that database path environment variables enforce placement for all applications.

## Migration and rollback

The main roster lists 29 names. The 18:04 KST snapshot matches 28 active cgroups to that roster.
`mysql2` has no observed active cgroup. Seven observed containers fall outside the main roster:

- `vimkim-cubrid-test-shell`
- `vimkim0`
- `chijun0`, which has a separate example configuration
- `chijun5`
- `hornetmj0`
- `cubrid-node-a`
- `cubrid-node-b`

These names use an earlier inspect mapping from the same boot. Check current names and owners before rollout.
The HA pair has a separate Compose source in the `cubrid-ha` checkout.
Its source needs its own reviewed controls or an explicitly separate budget.
Four remaining omitted names have no located maintained creation definition.
An omitted container does not enter the new pool automatically.
The aggregate protection is incomplete until every intended workload enters the pool or receives a separate approved budget.

The confirmed recreation requirement preserves `/home` through its existing named volume.
The user does not require a separate `/home` backup or persistence of the writable image layer.
Preserve any additional data that the owner identifies for this migration before removing it.

For each existing container:

1. Agree the interruption with its owner.
2. Inspect current mounts, writable-layer changes, image, command, identity, network, and lifecycle configuration.
3. Preserve its inspect metadata and define the new spec in the appropriate roster.
4. Inventory databases, transaction logs, and other valuable data outside `/home`.
5. Stop database writes with the owner's agreed procedure.
6. Copy valuable `/tmp` data to verified disk storage before stopping the container.
7. Check copied sizes, ownership, modes, and checksums where appropriate.
8. Reuse the existing `/home` volume. Preserve additional owner-selected data without imposing a separate home-backup requirement.
9. Retain the old stopped container for rollback when practical. Preserve its IP and volume metadata.
10. Create the replacement with the same name, IP, and `/home` volume through the reviewed launcher.
11. Check the live cgroup parent, CPU and memory limits, `/tmp` filesystem, sticky permissions, service health, and retained data.
12. Check a container restart and a recreation before migrating another owner.

Do not remove an old container or copy a live database as an assumed consistent backup.
Check how the installed Podman releases the old IP before reuse. Renaming alone must not be assumed to release it.
Do not start old and new containers together with the same IP or writable database volume.
A rollback stops the replacement and restores the retained container's original name and lifecycle configuration.
Reconcile volume changes before starting it. Restoring the launcher does not reverse runtime changes.

## Deployment acceptance

The deployment requires a separate host-change request. Repository merge approval is insufficient.
After budget approval, create a reviewed `resource-policy.json` with `approved: true`.
Install the rendered `dev2.slice` unit through the approved host procedure.
Check the live pool values before any container creation.
Prepare disk directories with adequate capacity and mode `1777`.
Use an exact `--only NAME` selection for the canary and each migration.

The launcher verifies policy approval, physical RAM headroom, live pool values, and disk backing before Podman calls.
It includes resource controls in each desired spec hash.
Matching hashes remain unchanged on repeat runs. Drift produces a warning without host mutation.
All maintained `just` recipes for container creation use this path, including Ubuntu and CentOS examples.
Direct Podman commands remain an administrative bypass.

Check container recreation with the same policy and persistent directories.
Check service and pool restoration after a host restart in a disposable equivalent environment.
Inspect the existing container restart mechanism before choosing lifecycle changes.
Host-reboot restart behavior remains a user choice and can use a separate script.
This patch does not enable a new host-wide container restart policy.

## Verification and references

```bash
/usr/bin/python3 -B -m unittest discover -s tests -v
git diff --check
```

The isolated tests check CPU quotas, policy validation, swap translation, backing filesystems, parent limits, dry-run isolation,
offline audits, access errors, spec drift, and preservation of existing containers.
They do not start containers or prove restart persistence on a real host.

- [Podman 5.6 run options](https://docs.podman.io/en/v5.6.0/markdown/podman-run.1.html)
- [systemd 252 resource controls](https://www.freedesktop.org/software/systemd/man/252/systemd.resource-control.html)
- [Kernel cgroup v2 accounting and hierarchy](https://docs.kernel.org/admin-guide/cgroup-v2.html)
