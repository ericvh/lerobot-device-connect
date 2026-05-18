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

For local LeRobot development:

```bash
pip install -e "../lerobot"
pip install -e .
```

## Quick start

**Simulated (no hardware):**

```bash
lerobot-device-connect --sim --allow-insecure
```

**On-robot (LeKiwi host):**

```bash
# On the Pi — expose motors + cameras
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
| `teleop_step`                  | One teleop cycle (leader + keyboard) |


Events: `state_update` (~10 Hz), `emergency_stop`.

## Environment variables


| Variable                     | Default        | Meaning                        |
| ---------------------------- | -------------- | ------------------------------ |
| `LEROBOT_ROBOT_MODE`         | `local`        | `local`, `client`, or `sim`    |
| `LEROBOT_REMOTE_IP`          | —              | Robot IP for client mode       |
| `LEROBOT_ROBOT_PORT`         | `/dev/ttyACM0` | Feetech port (local mode)      |
| `LEROBOT_TELEOP_LEADER_PORT` | —              | Enable leader teleop           |
| `LEROBOT_TELEOP_KEYBOARD`    | —              | `1` / `true` for keyboard base |
| `DEVICE_ID`                  | `lekiwi-1`     | Device Connect device id       |
| `TENANT`                     | `default`      | Tenant                         |


## Tests

```bash
python tests/smoke_sim_runtime.py
pytest tests/
```

## License

Apache-2.0 — see [LICENSE.md](LICENSE.md).

## Security

Threat model, deployment guidance, and vulnerability reporting: [SECURITY.md](SECURITY.md).