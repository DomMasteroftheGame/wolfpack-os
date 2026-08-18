# car-seat — Wolfpack on Android Auto

The BuildYourWolfpack ops board on the car head unit: pending approvals (with
Approve / Deny), mesh-hub health, wolf activity, and Dom's personal queue.

> **Two homes:** this copy (`wolfpack-hub/car-seat/`) is the phone-seat ops
> instance. The product copy lives at `operation-system/appliance/car-seat/` —
> it rides the wolfpackOS USB builder into every imaged peer
> (`/opt/jarvis-src/appliance/car-seat/`), and `appliance/install-car-seat.sh`
> there builds + installs it (prebuilt APK when the image shipped one).
> Port fixes to both.

Thin client only. All data comes from the **phone seat dashboard**
(`wolfpack/dashboard/server.mjs`, `http://127.0.0.1:8787`), which injects the
mesh token server-side — **no credentials in this app, ever**. Cleartext HTTP
is permitted to `127.0.0.1`/`localhost` only (see `network_security_config.xml`).

## How it works

- `androidx.car.app` (Car App Library), category `IOT` — the closest allowed
  category for an ops/status app. **Sideload-only**: not Play-distributable.
- `PollScreen` re-fetches every 15 s while a screen is visible.
- Driving-state template limits are respected: ≤6 list rows, ≤2 pane actions.
- Decisions are whole-approval (`POST /api/approvals/<id>/decision`,
  note `via car-seat`). Line-item approvals still work; the decision applies
  to the whole approval.
- Prerequisite: the phone seat must be running
  (`proot-distro login alpine -- /root/wolfpack/start-all.sh`, normally started
  by Termux:Boot) and the Android Tailscale app must be Connected, or the
  leader hub is unreachable and every screen shows "Leader unreachable".

## Build (on the mac hub)

Needs JDK 17+ and the Android SDK (platform 34 + build-tools). With Android
Studio installed, the SDK is already at `~/Library/Android/sdk`.

```sh
cd car-seat
echo "sdk.dir=$HOME/Library/Android/sdk" > local.properties   # if ANDROID_HOME unset
gradle wrapper --gradle-version 8.9                          # one-time, needs a gradle
./gradlew assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
```

## Install (phone plugged into the mac, USB debugging on)

```sh
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Then on the phone: **Android Auto app → Settings → Version** (tap ~10× to unlock
developer settings) → **Developer settings → Unknown sources = ON**. Plug into
the car; "Wolfpack Seat" appears in the head-unit launcher.

## Tweaks

- Poll cadence: `periodMs` default in `PollScreen` (15 s).
- Parked-only decisions: wrap the Approve/Deny listeners in
  `ParkedOnlyOnClickListener.create(...)` in `ApprovalDetailScreen`.
- Wake controls (`/api/wake`) are deliberately left on the phone dashboard —
  reviving hubs from the car is a parked-at-home job.
