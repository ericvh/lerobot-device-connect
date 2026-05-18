# Security

Threat model and deployment guidance for **lerobot-device-connect**. This document
covers this package and how it sits in the Device Connect + LeRobot stack. Broker
ACLs, portal credential issuance, MCP client policy, and LeRobot core safety live
in upstream components unless noted here.

This driver is **not** a safety-certified robot controller. It forwards observation
and motor commands to LeRobot robot implementations (LeKiwi first) and mirrors
state for agents over Device Connect.

## Reporting vulnerabilities

Do **not** open a public issue for exploitable security bugs.

1. Prefer [GitHub private vulnerability reporting](https://github.com/NEW_ORG/lerobot-device-connect/security/advisories/new) once a remote is configured.
2. For issues in **dependencies**, also report to the upstream project when appropriate:
   - [device-connect](https://github.com/arm/device-connect) / `device-connect-edge`
   - [lerobot](https://github.com/huggingface/lerobot)
   - [Hugging Face security](mailto:security@huggingface.co) for LeRobot-specific concerns

Include: description, reproduction steps, affected version/commit, impact, and
suggested mitigation if you have one.

## Scope and deployment shapes

| Shape | Driver runs on | Robot path | Main exposure |
|-------|----------------|------------|---------------|
| **Sim / CI** | Laptop or CI | `SimLeKiwiBridge` (no hardware) | Mesh registration if broker connected; operator confusion with real `device_id` |
| **On-robot (`local`)** | Raspberry Pi on LeKiwi | `LeKiwi` → Feetech bus + USB cameras | Serial bus control, camera/mic data, LAN reachability |
| **Teleop laptop (`client`)** | Operator PC | `LeKiwiClient` → ZMQ to `lekiwi_host` | Open ZMQ on robot LAN, leader arm USB, keyboard capture |
| **Portal / remote** | Robot or edge host | Any mode + `nats://portal.deviceconnect.dev` | Anyone with mesh credentials can invoke RPCs |

### Components in scope

| Component | In this repo? | Notes |
|-----------|---------------|-------|
| `LeRobotDeviceDriver` RPC/event surface | Yes | Primary attack surface for mesh callers |
| `RobotBridge` (local / client / sim) | Yes | Translates RPCs to LeRobot I/O |
| `TeleopComposer` (leader + keyboard) | Yes | Local USB + input devices; `teleop_step` RPC |
| `device_connect_edge.DeviceRuntime` | Dependency | Messaging, credentials, `allow_insecure` |
| `lerobot.robots.lekiwi.lekiwi_host` | Dependency | ZMQ cmd/obs on robot; watchdog stops base |
| Feetech motors / omni base / cameras | Hardware + LeRobot | Physical safety boundary |

## Trust boundaries

```text
  [Human supervisor]          [LLM agent host]
         |                              |
         | supervises                   | MCP / IDE (device-connect-agent-tools)
         v                              v
                    Device Connect broker (NATS / Zenoh)
                    portal.deviceconnect.dev  OR  local lab broker
                              |
                              | invoke_device / RPC
                              v
                 lerobot-device-connect (this package)
                              |
            +-----------------+------------------+
            |                                    |
     local: Feetech /dev/tty*              client: ZMQ tcp://robot:5555/5556
     + USB cameras                         (requires lekiwi_host on robot)
            |                                    |
            v                                    v
              LeKiwi hardware (arm + omni base)
```

**Optional teleop path (client mode typical):**

```text
  [Leader arm USB]     [Keyboard on teleop PC]
         |                      |
         v                      v
    SO100Leader            KeyboardTeleop
         \                    /
          `--> TeleopComposer.compose_action() --> send_action --> ZMQ --> robot
```

## Assets

| Asset | Why it matters |
|-------|----------------|
| **Physical robot** | Arm motion and mobile base velocity can injure people or damage property |
| **USB cameras** | `get_observation_with_cameras` exposes JPEG frames over the mesh |
| **Portal / NATS credentials** | Grant Device Connect membership; invoke RPCs on registered `device_id` |
| **ZMQ cmd socket (5555)** | Unauthenticated JSON actions on robot when `lekiwi_host` binds `tcp://*:5555` |
| **Feetech serial bus** | Direct motor commands in `local` mode |
| **Leader arm calibration** | Wrong teleop mapping can cause unexpected follower motion |
| **Environment / CLI config** | `DEVICE_ID`, `LEROBOT_REMOTE_IP`, credential file paths |

## Threat actors (representative)

1. **Compromised or mis-prompted agent** — repeated `send_action`, `teleop_step`, or camera RPCs (motion spam, exfiltration).
2. **Mesh participant with valid NATS credentials** — same RPC surface as MCP without IDE supervision.
3. **LAN attacker on robot Wi‑Fi** — connects to ZMQ ports, scans for open broker, reaches Pi services.
4. **LAN attacker on teleop LAN** — targets operator laptop running client mode + teleop.
5. **Credential thief** — reads portal `.json` / `.creds` from disk, backups, or shared Downloads folder.
6. **Malicious teleop operator** — legitimate USB/keyboard access; social/physical access model.

## RPC and data flows (attack surface)

| RPC / event | Data / effect | Primary risks |
|-------------|---------------|---------------|
| `send_action` | Full motor-space dict to robot | Unbounded commands; no driver-side kinematic clamps |
| `teleop_step` | Leader + keyboard → composed action | Requires teleop connected; merges untrusted local input with mesh-triggered cycles |
| `get_observation` | Scalar joints / velocities | Information disclosure of robot state |
| `get_observation_with_cameras` | Scalars + base64 JPEG | Privacy; large payloads (broker DoS) |
| `stop_base` | Zero base velocities | Safety-relevant; should not be the only guard |
| `state_update` (event) | Scalar stream on change (polled at `LEROBOT_STATE_HZ`) | Disclosure to mesh subscribers when joints/base move |
| `get_features` / `get_status` | Schema and connectivity | Reconnaissance |

Unlike reachy-mini-driver, this package **does not** implement numeric clamps on
`send_action` keys. LeRobot / LeKiwi apply `max_relative_target` and host watchdog
behavior upstream.

## Controls in this package

| Control | What it does | Limitation |
|---------|----------------|------------|
| **Scalar-only default observation** | `get_observation` omits numpy camera arrays | Cameras still available via `get_observation_with_cameras` |
| **JPEG encoding for cameras** | Configurable quality; structured JSON | Any mesh invoker with rights can request frames |
| **`teleop_step` gating** | Returns error if teleop not configured/connected | `send_action` still accepts arbitrary dicts |
| **Sim mode isolation** | No hardware I/O | Sim device can still join a real broker if misconfigured |
| **Portal credential discovery** | Glob under `~/Downloads` when `--portal` | Convenience for lab; risky on shared machines |
| **`allow_insecure` default false** | Passed to `DeviceRuntime` | README examples use `--allow-insecure` for local dev |
| **Dependency on LeKiwi host watchdog** | Stops base after cmd timeout (client path) | Does not stop arm; watchdog is on robot host process |

## Inherited and external controls

Rely on these outside this repository:

| Layer | Control |
|-------|---------|
| **Device Connect portal** | Credential issuance, tenant/device binding, TLS when not insecure |
| **NATS / Zenoh ACLs** | Limit who can publish/subscribe to device subjects |
| **MCP / agent policy** | Tool allowlists, human approval, rate limits |
| **Network segmentation** | Firewall ZMQ `5555`/`5556`, block robot ports from guest Wi‑Fi |
| **LeRobot `max_relative_target`** | Limits relative joint deltas on LeKiwi |
| **`lekiwi_host` watchdog** | Stops omni base when commands stop (client topology) |
| **Physical e-stop / supervision** | Required for any real-robot deployment |

## STRIDE summary

| Category | Example threat | Mitigation today | Residual risk |
|----------|----------------|------------------|---------------|
| **Spoofing** | Caller invokes RPCs as another tenant/device | Broker credentials bind `device_id`; no per-RPC caller identity | Stolen creds = full device impersonation |
| **Tampering** | LAN client sends ZMQ JSON to `5555` | No auth on ZMQ; trust LAN | Isolate robot network; VPN for remote teleop |
| **Repudiation** | Agent denies ordering motion | stderr logging only | Add centralized audit if required |
| **Information disclosure** | `get_observation_with_cameras` over mesh | JPEG vs raw; scalars in events | Any authorized invoker can pull camera frames |
| **Denial of service** | Large camera payloads or tight `teleop_step` loops | JPEG size bounded by resolution; broker limits in edge | CPU load on Pi; serial bus saturation |
| **Elevation** | Upload portal creds, join mesh, control robot | File must exist on host already; portal issuance upstream | Compromised teleop laptop = creds + leader arm |

## Mode-specific notes

### `local` (on-robot)

- Driver holds **Feetech bus** and **camera devices** (`/dev/ttyACM0`, `/dev/video*`).
- No ZMQ exposure from this package, but robot may still run `lekiwi_host` separately.
- Run driver as a dedicated user; restrict access to serial and video nodes.

### `client` (teleop laptop)

- Requires **`lekiwi_host` on robot** binding ZMQ on all interfaces by default (`tcp://*:5555`).
- Treat robot IP network as **trusted** or tunnel ZMQ over VPN/SSH.
- **Leader arm** and **keyboard** are local to the driver process; `teleop_step` from the mesh
  triggers local input sampling — understand who can call that RPC.

### `sim`

- Safe for hardware, but use a distinct `device_id` (e.g. `lekiwi-sim`) on shared brokers.

## Deliberate tradeoffs

1. **Agent-first RPC surface** — Full `send_action` dict for flexibility; no driver-side
   workspace fences. Narrow broker ACLs and MCP tool lists in production.
2. **Unauthenticated ZMQ (LeKiwi stack)** — Matches upstream `lekiwi_host` design for
   low-latency teleop. Security is network-position dependent.
3. **Optional teleop over mesh** — `teleop_step` lets remote agents drive cycles that read
   local USB/keyboard; useful for demos, risky without physical supervision.
4. **`DEVICE_CONNECT_ALLOW_INSECURE`** — Documented for local smoke tests. Disable for
   portal or any shared broker.
5. **Portal credential auto-discovery** — Same pattern as reachy-mini-driver lab workflows;
   prefer explicit `--portal-credentials` on shared machines.

## Recommended deployments

| Goal | Suggestion |
|------|------------|
| **Production portal** | `allow_insecure=false`, explicit credentials path, unique `device_id`, reviewed NATS ACLs |
| **On-robot** | `local` mode, dedicated service user, firewall except required ports, no guest Wi‑Fi |
| **Teleop** | VPN to robot; bind ZMQ to localhost on robot if you patch host config; supervise `teleop_step` |
| **Privacy** | Avoid exposing `get_observation_with_cameras` to broad mesh principals; use scalar RPCs only |
| **Dev laptop** | `sim` + local broker + `allow_insecure` on loopback only |
| **Multi-agent** | External orchestrator; do not assume RPC ordering serializes concurrent `send_action` |

## Out of scope (today)

- Authentication or TLS for LeKiwi ZMQ
- Driver-side clamping or validation of `send_action` beyond LeRobot
- Motion leases / command ownership (not implemented)
- Encrypted storage for portal credentials
- Safety-rated emergency stop wiring through Device Connect
- Automated credential rotation

## Dependency security

| Dependency | Security relevance |
|------------|-------------------|
| `device-connect-edge` | Messaging, credential loading, insecure transport flag |
| `lerobot` | Robot drivers, teleoperators, hub model loading (see [lerobot/SECURITY.md](https://github.com/huggingface/lerobot/blob/main/SECURITY.md)) |
| `opencv-python-headless` | Image encode/decode; native code attack surface |
| `pyzmq` (via lerobot client) | Network parser exposure on client deployments |

Keep dependencies pinned in production images and monitor advisories for this package
and LeRobot.

## Security-related tests

- `tests/smoke_sim_runtime.py` — validates RPC/event schema registration (no fuzzing).
- `tests/test_observation_codec.py` — ensures camera arrays are stripped from scalar path.

Run before release:

```bash
python tests/smoke_sim_runtime.py
pytest tests/
```

For upstream mesh hardening, see [device-connect](https://github.com/arm/device-connect)
and `device-connect-agent-tools`. For robot operation, follow Hugging Face LeRobot and
LeKiwi hardware documentation for your specific build.
