# Discord bot

The bot reads the website API and the shared data files, edits the game server configuration and restarts the game
container through the Docker socket. Configure it in `config/bot.env` (see [CONFIGURATION.md](CONFIGURATION.md)).

## What it posts by itself

| Event | Message |
|---|---|
| Always | A pinned **live board**, edited in place: status, track, session and time left (or lap X/N), fastest lap of the session, race order with gaps, drivers, track record and top 5 |
| New track record | Gold embed, pinned (the previous record pin is removed) |
| New car record | Green embed |
| Invalidated lap | Short red notice with the reason |
| Penalties and race control | The penalty and its reason, race-control messages from the game |
| Session start, new looped session | "Qualifying starts at…", "New Hotlap session at…" |
| Race | "Lights out" at the start, final classification with podium, DNF and DSQ at the chequered flag |
| Track change | The new track with the record to beat |
| Joins and leaves | Optional (`DISCORD_ANNOUNCE_JOINS`) |

## Commands for everyone

| Command | |
|---|---|
| `/server` | Status, session, records |
| `/drivers` | Connected drivers with on-track/pit state and personal bests |
| `/session` | Live timing; during a race the official order with gaps, pit stops and penalties |
| `/record [track]` | Track record and top 5 |
| `/leaderboard <car> [track]` | Leaderboard of one car |
| `/tracks` | Every layout with its record; layouts without a race weekend are marked |
| `/laps [driver]` | Latest laps with validity and sectors |
| `/driver <name>` | Statistics and personal records |
| `/packs` | Car classes and packs available for challenges, with their PI range |
| `/map`, `/site` | Link to the website |

## Admin commands

Admin commands are limited to `DISCORD_ADMIN_IDS` (or to Discord administrators when that is empty). Every command
that restarts the game server refuses to run while drivers are connected unless it is given `force: True`
(`REQUIRE_FORCE_WITH_DRIVERS`). Settings commands also take `restart: False` to apply the change at the next restart.

| Command | |
|---|---|
| `/changetrack <track> [weather] [duration] [mode]` | Track, and optionally weather, length and mode in one step. Race weekends use the server's race event list |
| `/raceweekend [track] [practice] [qualifying] [race] [race_type] [mandatory_pit] [tyre_change] [refuel] [weather]` | Practice, qualifying and race (laps or minutes), pit stop rules |
| `/challenge <track> [class] [mode] [weather] [duration] [title] [target_time] [target_driver]` | One class or pack only; the record holder (hotlap) or last winner (race) goes into the server name. `title` is the track name used in the server name; `target_time` with `target_driver` sets a time to beat that stays in the name until a real lap is faster. The target never enters the leaderboards |
| `/challengeoff` | Back to every car and the base server name |
| `/mode`, `/duration`, `/weather` | Single session settings |
| `/cycle <on/off>` | Let the server start a new session when one ends |
| `/maxdrivers`, `/password`, `/servername` | Server settings (the password reply is private) |
| `/settings` | Current configuration (passwords are only shown as set or not) |
| `/restart`, `/stop`, `/start` | Game server control |
| `/update` | Download the latest game files from Steam. It explains Steam Guard (approve the sign-in in the Steam mobile app), restores the settings if the download replaced them and lists the new cars |
| `/block`, `/unblock`, `/blocked` | Keep a driver out of the leaderboards |

## Classes and packs

`/challenge` offers every entry of `classes` in `config/challenge.json`:

- **GT3, GT2, GT4** are built from the game's car list: every preset whose name ends with ` - GT3` (and so on) is in
  the class, so cars added by game updates join automatically.
- **Packs** list presets explicitly: Cup, Porsche Cup, MX-5 Cup, M2 Racing, F1, Supercars, Sports, Hot Hatch, JDM,
  Homologation, 80s Supercars, Retro and Caterham in the shipped file. Each pack groups cars of the same kind with a
  close performance index (PI). Presets the server does not know are skipped.

```json
"JDM": {
  "label": "JDM",
  "description": "Japanese icons",
  "presets": ["preset_nsxr_mech_1", "preset_s2000ap1_mech_1", "preset_rx7fd_mech_1"]
}
```

Preset names and PI values are in the server's `server-data/server/cars.json`.
