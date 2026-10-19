# Game protocol notes

What `lapwatch` relies on, learned by observing the traffic between a dedicated server and its clients. Field
names and meanings are inferred from that traffic alone. Everything here may change with a
game update.

## Transport

Server and clients share one port (default 9600) over TCP and UDP.

### TCP frames

```
[u16 LE length] [u16 LE type = 2] [u8 name length] [message name, ASCII] [protobuf body]
```

`length` covers everything after itself. The name is the protobuf message name, sometimes qualified
(`CommandFromUI.TeleportToPit`). `google.protobuf.Any` payloads are decoded recursively from their `type_url`.
`lapwatch/schema.json` holds the subset of the schema that lapwatch decodes.

### UDP telemetry (client → server)

Packets of 63 bytes whose first byte is `0x01`. Little-endian:

| Offset | Type | Meaning |
|---|---|---|
| 0 | u8 | packet kind (`1`) |
| 2–4 | | sequence / timing |
| 9, 13, 17 | f32 ×3 | position x, y (altitude), z in metres |
| 33, 37, 41 | f32 ×3 | velocity x, y, z in m/s |
| 45–48 | u8 ×4 | per-wheel value that tracks wheel speed (not used) |
| 50 | u8 | steering input, 128 = centre, higher = right |
| 51 | u16 | engine rpm |
| 53 | u8 | gear: `0` reverse, `1` neutral, `2` first, `3` second… |
| 54 | u8 | throttle, 0–255 |
| 55 | u8 | brake, 0–255 |
| 58–61 | u8 ×4 | surface under each wheel (`0` asphalt, higher on kerbs and grass) |
| 62 | u8 | unknown, centred on 127 (not steering) |

The world is left-handed (x right, z forward, y up): the map mirrors x to draw tracks the right way round.

## Messages used

| Message | Direction | Use |
|---|---|---|
| `SplitFromRemoteMessage` | server → every client | splits and finish line: `split_id`, `split_time`, `is_valid`, `is_finish_line`, `is_start_line`, `laps_count`, `laptime`, `n_pos` |
| `PlatformRaceLeaderboard_LineUpdateEvent` | server → client | authoritative lap: `last_lap.laptime_ms`, `splits`, `flags`, `lap_snowflake_id` |
| `RaceTimingCut` | client → server | track-limit report; `remove_current_lap` invalidates the running lap |
| `PlatformRaceGameCarTimelineMessage` | both | `on_pitlane` |
| `UpdateGameCarState` | client → server | oneof: `electronics_values`, `assists_values`, `instrumentation_values`, `pit_state`, `pit_stop_values`, `car_location`, `bop_data` |
| `UpdateTyreStatus` | client → server | `tyre_dmg_and_wear` and `tyre_dirt_and_wetness`, packed `fixed64` |
| `UpdateDirtStatus` | client → server | `dirt_values`, packed `fixed64` (bodywork dirt) |
| `UpdateVisualDamages` | both | 5 floats, percent 0–100, in zone order front, rear, left, right, centre |
| `CarCollisionEventData` | client → server | `relative_impact_velocity`, `normal`, `optional_other_car_pguid` |
| `CommandFromUI.TeleportToPit` | client → server | the driver asked to go back to the pits |
| `TeleportCarCommand` | server → client | the car was moved (also happens when a car spawns) |

Car ids (`PGUID`) are two 64-bit integers, rendered as `xxxxxxxxxxxxxxxx-xxxxxxxxxxxxxxxx`.

## Session state

`BroadcastStateMessage` (server → client) carries one field of the game-mode state as a `google.protobuf.Any`:
`descriptor_name` is `TimeAttack.State.Game` (practice, qualifying, hotlap) or `InstantRace.State.Game` (race),
`field_number` tells which field changed.

- `SessionPhaseData`: the phase list with end times in game-mode milliseconds and the current phase. Practice and
  qualifying go `Waiting_For_Start → Session → Waiting_Last_Lap → Ended → Request_Quit`; a race goes
  `Waiting_For_Players → Start_Spawn_On_Position → Start_Countdown_Lights_On → Start_Countdown_Lights_Off → Session →
  Overtime_Waiting_For_Leader → Overtime_Waiting_For_Others → Ended` (rolling starts use `RollingStart_*`). The time
  left is `end_timestamp − current_gamemode_time`. `start_gamemode_time` is not always present; the end time of the
  first phase identifies a session.
- `PlatformRaceLeaderboard`: lines in official order (`type` `…_Race` in a race), laps, last and best lap, flags.
  It is sent when a client joins and at phase changes; during a race the per-car updates come as
  `PlatformRaceLeaderboard_LineUpdateEvent` with `position`.
- `PlatformRacePenaltyCollection`: pending and served penalties per car, with the investigation that caused them.
- `TrackStatus.pitexit_semaphore`, `MandatoryPistops`, `ReadyToStartMap`, `CrossedSafetCarLine`.

The state is only re-sent when someone joins or a phase changes: an observer started mid-session must persist it.

`UINotification` (server → client) is what the game shows to drivers: `SessionPenalty`, `RaceControl`, `Session`,
`Weather`… with values such as `{PENALTY_ADDED_KEY}`, `InvestigationType_…`, `PenaltyType_…`.
`PlatformPenaltyScoredMessage` travels client → server.

## Lap validity

- `last_lap.flags`: bit `2` = valid, bit `1` = invalid. A lap is valid when `flags & 2` and not `flags & 1`.
- A split with `is_start_line`, `split_id = 0` and `split_time = 0` marks the start of a timed lap. On tracks
  where the pit exit is the start line, time spent in the pit lane is not part of the lap. The marker carries no
  validity information.
- `RaceTimingCut` messages sent before the first finish line or while in the pit lane do not invalidate
  anything: some clients send them for the pit lane too.

## Packed per-wheel bytes

`fixed64` values pack one byte per wheel, little-endian, in the order FL, FR, RL, RR:

- `tyre_dmg_and_wear`: bytes 0–3 wear index, bytes 4–7 damage index.
- `tyre_dirt_and_wetness`: bytes 0–3 dirt, bytes 4–7 wetness (0–255).
- `dirt_values`: 8 bytes of bodywork dirt (0–255). Dirt builds up over the session and is not cleaned in the pits.

A missing field means all zeros.

## Flags

Local yellow flags are decided by each game client (a slow or stopped car nearby) and are not sent over the network:
`UpdateGameCarState` has no flag field. The website reproduces them from positions and speeds, comparing each car
with the reference lap at the same point of the track.

## Not available on the server

Suspension and engine damage are simulated on the driver's machine and never sent. Only bodywork zones and
tyre damage reach the server.

## Contacts

`CarCollisionEventData` is also sent when the floor touches the ground over crests and kerbs. Those contacts
have an almost vertical normal (`|normal.y| > 0.6`) and are ignored.
