# AGENTS.md

These instructions apply to the entire repository. Keep this file operational and repository-specific; user setup belongs in `README.md`, and implementation detail belongs in `docs/ARCHITECTURE.md`.

## Project Snapshot

- This is a Windows-only Python 3.10+ Tkinter application for one selected monitor's DDC/CI audio volume.
- The supported composition root is `app.py`. `main.py` is deliberately an exit-1 rejection stub that directs users to `app.py` without launching it.
- Runtime dependency: `monitorcontrol==4.2.0`. Optional executable builder: `Nuitka==2.4.8`.
- The app is an interactive current-user process, not a service. It has no HTTP/API server, port, database, authentication, external broker/job queue, cron, telemetry, or runtime network client.
- The global Volume Down/Up hook and physical DDC writes are safety-sensitive. Do not launch the app or call monitor operations as routine automated validation.
- There is a standard-library unit-test suite for fail-safe hotkeys, stable identity/settings, display invalidation, and fresh-handle revalidation. There is no lint, format, type-check, third-party test-framework, or CI configuration. State that limitation accurately.

## Runtime Shape

1. `app.py` creates the single `tk.Tk`, constructs `gui.MonitorVolumeApp`, and enters Tk's main loop.
2. The Tk main thread owns widgets, application state, settings writes, and overlay calls.
3. `display-change-listener`, `tray-icon`, and `volume-key-hook` are long-lived daemon threads with native Win32 message loops.
4. `ddc-gui-worker` and `ddc-volume-write` are short-lived daemon workers for blocking DDC/CI work.
5. Worker and native-thread callbacks cross into Tk through `queue.Queue`; `_poll_queues()` drains them every 50 ms.
6. Only one application-issued DDC operation should be active. Rapid writes are serialized and reduced to the latest `_pending_target_volume`.
7. A successful exact-identity volume read enables monitor control only while the display-change listener remains live and the topology generation is valid. If the native keyboard hook is also live, Volume Down/Up events are consumed instead of reaching Windows system audio.
8. A successful tray initialization makes startup tray-first. Closing the restored window exits; minimizing returns it to the tray.

Always preserve Tk's thread affinity. Never call Tk methods from tray, hook, or DDC worker threads; enqueue a callback with `_post_to_ui()`.

## Important Files

| File | Responsibility |
| --- | --- |
| `app.py` | Supported process entrypoint and Tk composition root. |
| `main.py` | Unsupported launcher stub; prints migration guidance and returns `1`. |
| `gui.py` | UI state machine, selection, readiness, queues, worker serialization, tray/window lifecycle. |
| `ddc.py` | Monitor identity, enumeration, clamping, and DDC read/write wrappers. |
| `settings.py` | Per-user selected-monitor JSON load/save. |
| `overlay.py` | Topmost, auto-hiding volume `Toplevel`. |
| `theme.py` | Windows theme read, ttk styles, DWM chrome, and runtime icon path. |
| `windows_platform.py` | Win32 ctypes ABI, monitor identity/EDID inventory, display notifications, tray controller, global keyboard hook, and DWM helpers. |
| `tests/` | Hardware-free hotkey, identity, settings, topology-generation, and fresh-write regressions. |
| `pyproject.toml` | Python requirement, dependency pins, and installed flat modules. |
| `build_exe.ps1` | One-file Nuitka build for `dist\windows-ddc.exe`. |
| `windows-ddc.ico` | Tracked executable, window, and tray icon source. |
| `docs/app.png`, `docs/overlay.png` | Manually maintained screenshots; there is no generation pipeline. |

Adding, renaming, or removing a distributable runtime module must keep `[tool.setuptools].py-modules` in `pyproject.toml` synchronized. Do not add `main.py` there or turn it back into a launcher without an explicit compatibility decision.

Changes to the icon name or location must update `theme.APP_ICON_PATH`, `--windows-icon-from-ico`, and `--include-data-files` in `build_exe.ps1`. The runtime icon must remain included as data even though it is also embedded as the executable icon.

## Persistent or Sensitive Data

- Live settings normally reside at `%APPDATA%\windows-ddc\settings.json`; if `APPDATA` is empty or unset, the fallback is `<home>\windows-ddc\settings.json`.
- New settings use schema version 2 and persist description plus a Windows device path and optional EDID manufacturer/product/serial identity. Never persist the transient display index.
- Unique EDID serial identity is preferred. Duplicate serials require the saved device path; monitors without a usable serial use the device path. Missing or ambiguous matches fail closed.
- Saving writes `settings.tmp` and then replaces `settings.json`. There is backward-compatible loading/promotion for unambiguous legacy description/ordinal files, but no lock or multi-instance coordination.
- Missing, unreadable, invalid-JSON, non-object, unknown-version, and invalid nested settings are treated as absent. JSON booleans are rejected as legacy ordinals.
- Do not read, overwrite, delete, or reset a user's live `settings.json` or leftover `settings.tmp` during automated work. Patch `settings.SETTINGS_PATH` to a unique temporary path before calling load/save functions.
- The physical monitor volume is external mutable state. A set can succeed even if the following readback fails, and shutdown does not restore the old value.
- No secrets are currently used or stored. Never add tokens, credentials, private endpoints, dumps, or machine-specific values to source, screenshots, fixtures, logs, or documentation.

There is no database and no migration command. If the settings schema changes, implement backward-compatible loading or an explicit migration, update README and architecture examples, and test old, missing, malformed, and new formats.

## CLI and Operational Commands

| Command | Use and side effects |
| --- | --- |
| `python -m pip install -e .` | Installs the pinned runtime dependency, can contact package indexes, modifies the active Python environment, and creates ignored egg-info. |
| `python app.py` | Starts native threads, reads/writes per-user settings, installs a global hook, and contacts monitor hardware. Run only with explicit authorization for interactive/manual testing. |
| `python main.py` | Intentionally prints the unsupported-launcher message and exits `1`; do not treat the nonzero result as a regression. |
| `python -m pip install -e .[build]` | Also installs pinned Nuitka tooling and may contact package indexes. |
| `.\build_exe.ps1` | May download Nuitka support/toolchain components, writes under ignored `dist\`, may overwrite an existing artifact, and removes intermediate build output. Run only when a build is requested. |

Do not call `enumerate_monitors()`, `read_monitor_volume()`, `set_monitor_volume()`, `change_monitor_volume()`, the packaged executable, `monitorcontrol`, `python -m monitorcontrol`, or `start()` on the display/global-hook/tray controllers as generic smoke tests. They cross hardware or user-session boundaries; the upstream dependency CLI can mutate multiple monitor settings.

There is no deploy, publish, tag, installer, or signing command in this repository. Do not push, tag, upload a release, publish a package, or invent a release workflow without explicit user authorization.

## API Shape

`windows-ddc` defines no external API or installed project CLI command. Its dependency's `monitorcontrol` command is an upstream hardware-management interface, not a supported project entrypoint. The important internal boundaries are:

- `ddc.enumerate_monitors() -> list[MonitorRef]`
- `ddc.match_selected_monitor(monitors, selected_key) -> SelectionMatch`
- `ddc.read_monitor_volume(monitor_ref) -> int`
- `ddc.set_monitor_volume(monitor_ref, target_volume) -> int`
- `ddc.change_monitor_volume(monitor_ref, delta) -> int` (currently unused by the GUI)
- `settings.load_selected_monitor_key()` and `settings.save_selected_monitor_key()`
- `windows_platform.DisplayChangeListener`, `TrayIconController`, and `GlobalVolumeKeyListener`

Keep each per-monitor DDC get/set sequence inside `with monitor_ref.monitor:`. Enumeration remains through `get_monitors()`, and description lookup remains on the wrapper. Preserve `0`–`100` application clamping and treat the post-write readback as authoritative when it succeeds.

## Tests Before Commit

Run these low-risk validation checks from the repository root:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q app.py ddc.py gui.py main.py overlay.py settings.py theme.py windows_platform.py
python -m pip check
git diff --check
git diff --cached --check
git status --short
```

Parse `build_exe.ps1` without executing it:

```powershell
$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path .\build_exe.ps1),
    [ref]$tokens,
    [ref]$parseErrors
) | Out-Null
if ($parseErrors.Count -ne 0) { $parseErrors; exit 1 }
```

For settings changes, add isolated tests around a temporary `SETTINGS_PATH`. For pure helper changes, prefer tests that use fake monitor objects and do not import or exercise real hardware unnecessarily.

GUI, tray, hook, theme, or DDC changes require an authorized Windows/manual pass with a compatible monitor. Verify:

- startup and tray-first behavior;
- discovery, duplicate descriptions, fallback, and saved selection;
- successful and failed volume reads;
- slider/button/key writes and readback;
- key pass-through before readiness and after exit;
- rapid-write coalescing and `0`/`100` boundaries;
- overlay visibility and auto-hide;
- minimize, restore, Refresh, and clean shutdown;
- disconnect/stale-handle behavior without leaving keys unexpectedly consumed.

Manual DDC tests can be audible and mutate monitor state. Record what was actually exercised; do not imply hardware or OS coverage that was not run.

## Gotchas and Things To Preserve

- Do not perform blocking DDC work on the Tk thread.
- Do not mutate Tk state directly from another thread. Keep callbacks small and exception-safe so `_poll_queues()` continues rescheduling itself.
- Preserve `_volume_write_inflight` / `_pending_target_volume` serialization. Do not introduce concurrent operations against the selected monitor wrapper.
- Do not broaden key consumption beyond `_hotkeys_enabled`. Readiness also requires a live display listener and valid topology event. Display notification, Refresh start, selection clearing, listener error, write failure, and shutdown clear it. Preserve the per-press consume/pass-through decision through matching key-up and the one-notice unavailable latch. Test hook/display-listener failures, reads, writes, Refresh, disconnect, shutdown, and held keys across transitions.
- Keep ctypes callback objects (`_wndproc` and `_hook_callback`) strongly referenced for their controllers' lifetimes. Incorrect ctypes signatures or callback lifetimes can crash the process.
- Stop display, hook, and tray message loops before destroying Tk. Their current joins have two-second timeouts; DDC workers are daemon threads and are not joined.
- Do not assume a DDC error means no hardware change occurred. Set plus readback is not transactional.
- Do not treat a topology generation check as cancellation. A native DDC call already in progress can still mutate hardware; stale completions must remain non-authoritative and trigger read-only rediscovery.
- Do not assume a listed monitor supports volume. Enumeration precedes the selected monitor's volume read.
- Display/device notifications trigger debounced discovery with bounded retries; every actual write also reacquires monitor wrappers. Do not claim that external OSD/program volume changes are polled.
- Do not ignore tray failure paths. Tray addition is asynchronous and a withdrawn Tk window can become unreachable if the icon is lost; Explorer `TaskbarCreated` recovery is not implemented.
- Do not run multiple instances during testing. There is no mutex; hooks, tray icons, DDC traffic, and `settings.tmp` can conflict.
- Do not hand-edit or commit `dist/`, `windows_ddc.egg-info/`, or `__pycache__/`. The present egg-info is ignored generated residue and can be stale; `pyproject.toml` and tracked sources are authoritative.
- Review `docs/app.png` and `docs/overlay.png` when visible UI changes. Update them only with real application captures and scrub machine-specific or sensitive content.
- Keep `README.md`, `CHANGELOG.md`, this file, and `docs/ARCHITECTURE.md` consistent when commands, dependencies, entrypoints, paths, settings, release behavior, or architectural boundaries change.
- The local clone can lack the remote lightweight `0.1.0` tag. For release-history work, inspect local refs and the live origin before concluding that no tags exist.
