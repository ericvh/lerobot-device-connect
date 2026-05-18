# lerobot-device-connect

Self-hosted [Device Connect](https://github.com/arm-university/device-connect) edge driver for [Hugging Face LeRobot](https://github.com/huggingface/lerobot) robots. The first supported robot is **LeKiwi**, modeled on the teleop loop in `lerobot/examples/lekiwi/teleoperate.py`.

This package mirrors the architecture of [reachy-mini-driver](https://github.com/ericvh/reachy-mini-driver): a `device_connect_edge.DeviceDriver` with RPCs, events, and a CLI that runs `DeviceRuntime` against NATS/Zenoh (portal or local).

## Architecture

```
┌─────────────────────┐     RPC / events      ┌──────────────────────────┐
│ Device Connect      │ ◄──────────────────► │ LeRobotDeviceDriver       │
│ (portal / local)    │                      │  ├─ RobotBridge (LeKiwi)  │
└─────────────────────┘                      │  └─ TeleopComposer (opt) │
                                               └──────────────────────────┘
```

**Robot modes** (`--robot-mode` / `LEROBOT_ROBOT_MODE`):


| Mode     | Bridge                           | Where to run                                                                       |
| -------- | -------------------------------- | ---------------------------------------------------------------------------------- |
| `local`  | `LeKiwi` (Feetech bus + cameras) | On the robot (Raspberry Pi)                                                        |
| `client` | `LeKiwiClient` (ZMQ)             | Teleop laptop; requires `python -m lerobot.robots.lekiwi.lekiwi_host` on the robot |
| `sim`    | In-process stub                  | CI / smoke tests                                                                   |


**Optional teleop** (same composition as `teleoperate.py`):

- `--leader-port /dev/tty.usbmodem…` — SO100 leader arm → `arm_`* action keys
- `--keyboard-teleop` — keyboard → base velocities (LeKiwi **client** mode only)

Use RPC `teleop_step` for one observe → compose → send cycle, or call `get_observation` / `send_action` directly from agents.

## Install

```bash
cd ~/src/lerobot-device-connect
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

For local LeRobot development (includes Feetech motor SDK for on-robot mode):

```bash
pip install -e "../lerobot[lekiwi]"
pip install -e .
```

**Calibration** on the robot is read from `~/{{hostname}}.json` when that file exists (e.g. `~/dum-e.json` on host `dum-e`). Otherwise LeRobot uses `~/.cache/huggingface/lerobot/calibration/robots/lekiwi/{{robot-id}}.json`. Override with `--robot-id` / `--calibration-dir` or `LEROBOT_ROBOT_ID` / `LEROBOT_CALIBRATION_DIR`.

## Quick start

**Simulated (no hardware):**

```bash
lerobot-device-connect --sim --allow-insecure
```

**On-robot (LeKiwi host):**

```bash
# On the Pi — expose motors + cameras (uses ~/dum-e.json when hostname is dum-e)
lerobot-device-connect \
  --robot-mode local \
  --robot-port /dev/ttyACM0 \
  --device-id my-lekiwi \
  --allow-insecure
```

**Teleop laptop (ZMQ client + leader + keyboard):**

```bash
# On the robot first:
# python -m lerobot.robots.lekiwi.lekiwi_host --robot.id=my_lekiwi

lerobot-device-connect \
  --robot-mode client \
  --remote-ip 192.168.1.42 \
  --leader-port /dev/tty.usbmodem585A0077581 \
  --keyboard-teleop \
  --allow-insecure
```

**Portal (Device Connect cloud):**

```bash
lerobot-device-connect --portal --portal-credentials ~/Downloads/your-creds.json
```

## RPC surface


| RPC                            | Description                          |
| ------------------------------ | ------------------------------------ |
| `get_features`                 | Observation/action feature schemas   |
| `get_status`                   | Connection + last scalar state       |
| `get_observation`              | Scalar joints/velocities only        |
| `get_observation_with_cameras` | Scalars + JPEG camera frames         |
| `send_action`                  | Motor-space action dict              |
| `stop_base`                    | Zero omniwheel velocities            |
| `get_arm_config`               | Arm joint names and position keys    |
| `get_arm_positions`            | Current arm joint positions          |
| `set_arm_positions`            | Goal positions for one or more joints |
| `set_arm_joint`                | Goal position for a single joint     |
| `nudge_arm_joint`              | Relative move from present position  |
| `get_base_teleop_config`       | Base drive directions and speed tiers |
| `set_base_speed_level`         | Set speed tier (0=slow … 2=fast)     |
| `base_speed_up` / `base_speed_down` | Adjust speed tier               |
| `set_base_velocity`            | Direct `x.vel` / `y.vel` / `theta.vel` |
| `drive_base`                   | One teleop direction (`forward`, etc.) |
| `drive_base_keys`              | Multiple directions (e.g. forward+left) |
| `list_cameras`                 | Camera names, V4L2 paths, ALSA devices |
| `get_camera_video`             | JPEG frame from `front` or `wrist`   |
| `get_cameras_video`            | JPEG frames from all cameras         |
| `get_camera_audio`             | Short WAV clip from camera mic       |
| `get_cameras_audio`            | WAV clips from all camera mics       |
| `teleop_step`                  | One teleop cycle (leader + keyboard) |


Events: `state_update` (on scalar change; polled at `LEROBOT_STATE_HZ`), `emergency_stop`.

## Environment variables


| Variable                     | Default        | Meaning                        |
| ---------------------------- | -------------- | ------------------------------ |
| `LEROBOT_ROBOT_MODE`         | `local`        | `local`, `client`, or `sim`    |
| `LEROBOT_ROBOT_ID`           | hostname       | Calibration file stem (`dum-e` → `~/dum-e.json`) |
| `LEROBOT_CALIBRATION_DIR`    | `~` if `~/{{id}}.json` exists | Directory for `{id}.json` |
| `LEROBOT_REMOTE_IP`          | —              | Robot IP for client mode       |
| `LEROBOT_ROBOT_PORT`         | `/dev/ttyACM0` | Feetech port (local mode)      |
| `LEROBOT_TELEOP_LEADER_PORT` | —              | Enable leader teleop           |
| `LEROBOT_TELEOP_KEYBOARD`    | —              | `1` / `true` for keyboard base |
| `LEROBOT_CAMERA_AUDIO_ALSA`  | —              | JSON map, e.g. `{"front":"hw:2,0","wrist":"hw:3,0"}` |
| `DEVICE_ID`                  | `lekiwi-1`     | Device Connect device id       |
| `TENANT`                     | `default`      | Tenant                         |


## Web teleop (test UI)

Browser UI with live camera streams (MJPEG), WASD base drive, and arm sliders.
By default it controls a robot over **Device Connect** (same RPCs as
`lerobot-device-connect` on the mesh). Use `--direct` only for local/in-process
testing without a broker.

**1. Start the robot driver on the Pi (or sim):**

```bash
lerobot-device-connect --robot-mode local --device-id my-lekiwi --allow-insecure
# or portal:
lerobot-device-connect --portal --portal-credentials ~/Downloads/your-creds.json
```

**2. Run the web UI (laptop or Pi) against that device id:**

```bash
pip install -e ".[web]"
lerobot-web-teleop \
  --portal \
  --portal-credentials ~/Downloads/your-creds.json \
  --target-device-id my-lekiwi \
  --host 0.0.0.0 --port 8080
```

`--target-device-id` must match the robot's `lerobot-device-connect --device-id`.
Your portal credentials are for **mesh access**; the target id is the **robot**.

Environment alternatives: `LEROBOT_TARGET_DEVICE_ID`, `NATS_CREDENTIALS_FILE`,
`TENANT`, `MESSAGING_URLS` (same as the main driver).

**Direct / in-process mode** (no Device Connect broker):

```bash
lerobot-web-teleop --direct --sim
lerobot-web-teleop --direct --robot-mode local --robot-port /dev/ttyACM0
```

Open `http://<host>:8080/`. The HTTP server has **no authentication** — lab /
trusted network only.

## Tests

```bash
pip install -e ".[dev,web]"
python tests/smoke_sim_runtime.py
pytest tests/
```

## License

Apache-2.0 — see [LICENSE.md](LICENSE.md).

## Security

Threat model, deployment guidance, and vulnerability reporting: [SECURITY.md](SECURITY.md).