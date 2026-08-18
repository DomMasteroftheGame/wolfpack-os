# Updating Wolfpack OS

Wolfpack OS updates in three layers. You almost never need to reflash.

## 1. The runtime (most updates) — `wolfpack-update`

Every installed peer carries `/usr/local/bin/wolfpack-update` (source:
`scripts/wolfpack-update.sh` in this repo). It pulls the latest runtime from
the public repo, swaps it in, restarts the Jarvis service, health-checks, and
rolls back automatically if anything fails.

```bash
sudo wolfpack-update            # latest stable release tag
sudo wolfpack-update main       # track the edge
sudo wolfpack-update v1.0.1     # a specific ref
```

- Only the runtime (`jarvis_os` + `requirements.txt`) is swapped — your local
  config, personas, skills, and data are never touched.
- A backup of the previous runtime is kept at `/opt/jarvis-os/.update-backup`.
- Logs: `/var/log/wolfpack-update.log`.

**On the 1.0.0 image** (which predates the script): fetch it once from the repo
and run it — from then on it updates itself along with everything else:

```bash
curl -fsSL https://raw.githubusercontent.com/DomMasteroftheGame/wolfpack-os/main/scripts/wolfpack-update.sh \
  | sudo install -m 0755 /dev/stdin /usr/local/bin/wolfpack-update
sudo wolfpack-update
```

## 2. Ubuntu system packages

Stock `unattended-upgrades` applies security updates automatically. Nothing to do.

## 3. The base image (major versions only)

New appliance payloads / major versions ship as a fresh ISO on the mirrors
(GitHub Release notes + Internet Archive + SourceForge). Reflash or netboot-
reinstall. Runtime updates never require this.

## Channels

- **Stable** — version tags (`v1.0.1`, …). Default for `sudo wolfpack-update`.
- **Edge** — `main`. For machines that should track development.
