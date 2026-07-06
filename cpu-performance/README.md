# CPU Performance Governor Scripts

This directory contains scripts for checking and forcing Linux CPU frequency policy to the `performance` governor on server hosts.

## Scripts

- `collect-cpupower-info.sh` collects CPU frequency, TuneD, cpupower, kernel, service, and related configuration details. Use it before and after a change, and again after reboot, to compare the effective governor and service state.
- `apply-performance-governor-no-reboot.sh` applies the performance-governor setup without rebooting. It backs up the current cpupower and TuneD state, disables `cpupower.service` as the boot-time policy owner, enables TuneD, switches to `throughput-performance`, and creates a local `server-performance` TuneD fallback profile if the governors are still not `performance`.

## Usage

Collect current state:

```bash
./collect-cpupower-info.sh | tee collected-before.txt
```

Apply the no-reboot performance governor change:

```bash
sudo ./apply-performance-governor-no-reboot.sh
```

Collect state again after reboot:

```bash
./collect-cpupower-info.sh | tee collected-after-reboot.txt
```

## Notes

- `apply-performance-governor-no-reboot.sh` must run as root.
- The apply script writes backups under `/root/cpupower-fix-backup/<timestamp>/`.
- The apply script expects a systemd-based host with TuneD and cpupower tooling available.
- The generated `collected-*.txt` files are evidence outputs and do not need to be committed.
