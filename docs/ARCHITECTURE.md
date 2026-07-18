# Architecture

This document describes the tagged `0.1.0` runtime and the current repository sources. `windows-ddc` is a small Windows desktop process: Tk owns the UI, native Win32 message loops provide the tray icon and global volume-key hook, and short-lived worker threads perform DDC/CI operations against physical monitors.

There is no server-side tier. The project has no HTTP API, listening port, database, container, service, authentication system, broker, cron process, telemetry client, or runtime network dependency.

## High-level flow

1. The supported entrypoint, `app.py`, creates one `tk.Tk`, constructs `gui.MonitorVolumeApp`, and enters `root.mainloop()`.
2. `MonitorVolumeApp.__init__()` samples the Windows app-theme preference and loads a saved monitor selection from `settings.py`.
3. It builds the fixed-size control window, status bar, and hidden `overlay.VolumeOverlay` on the Tk thread.
4. It attempts to start `windows_platform.TrayIconController`. On success, the application posts an icon-add request and withdraws the Tk window. A synchronous tray-start failure is reported in the still-visible window and startup continues without tray-first hiding.
5. It independently attempts to start `windows_platform.GlobalVolumeKeyListener`, which installs a desktop-wide low-level keyboard hook on its own message-loop thread. Hook-start failure is reported and startup continues without a listener. Both native `start()` calls wait on readiness events without a timeout.
6. It schedules two Tk callbacks after 50 ms: the recurring cross-thread queue poll and a one-shot initial monitor refresh.
7. The refresh worker enumerates DDC/CI monitors, chooses the saved selection or the first monitor, and reads that monitor's current volume.
8. The worker enqueues a completion callback. The Tk queue poll applies the monitor list, selection, displayed volume, readiness, and status text.
9. A button, slider release, or intercepted volume-key event computes a clamped target, updates the UI optimistically, displays the overlay, and starts a serialized DDC set/readback worker.
10. The readback becomes authoritative. Any requests accumulated during the active write are reduced to the most recent target and executed next.
11. Shutdown disables key consumption, cancels Tk timers, stops the hook and tray loops, closes the overlay, and finally destroys the Tk root.

## Runtime process and thread ownership

Source execution uses one interactive process. The one-file Nuitka executable adds a compiler-controlled bootstrap/extraction phase, but the repository does not customize that phase.

| Thread | Lifetime | Owns or performs | Communication boundary |
| --- | --- | --- | --- |
| Tk main thread | Process lifetime | Widgets, state mutation, selection persistence, status, overlay, queue draining | Receives queued callables and key deltas every 50 ms |
| `tray-icon` | Long-lived daemon | Hidden Win32 window, notification icon, native menu, message pump | Controller callbacks enqueue Tk work through `_post_to_ui()` |
| `volume-key-hook` | Long-lived daemon | `WH_KEYBOARD_LL` hook and message pump | Reads readiness through `should_consume()` and enqueues integer deltas |
| `ddc-gui-worker` | One short-lived daemon per accepted refresh/selection read | Enumeration and selected-monitor volume reads | Enqueues success or failure callable |
| `ddc-volume-write` | One short-lived daemon at a time | Selected-monitor set followed by readback | Enqueues write success or failure callable |

`MonitorVolumeApp._result_queue` carries zero-argument callbacks into Tk. `_hotkey_delta_queue` carries `+1`/`-1` changes. `_poll_queues()` drains all result callbacks first, combines key deltas accumulated during the poll interval, then schedules itself again after 50 ms.

The `_busy` flag prevents a new refresh/selection worker while another general operation is active. Volume controls remain usable during an active volume write, but they update `_pending_target_volume` rather than starting another DDC worker. This is the application's serialization boundary; there is no separate DDC lock.

Tray and hook threads are explicitly stopped and joined with two-second timeouts. DDC workers are daemon threads and are not cancelled or joined; `_closing` causes their eventual callbacks to be dropped.

All Tk calls must remain on the Tk thread. A native or DDC thread must enqueue work rather than touching widgets. Queued callbacks also need to remain exception-safe: `_poll_queues()` does not wrap each callback, so an exception can prevent the next poll from being scheduled.

## Application entrypoints and composition

### Supported entrypoint: `app.py`

`app.main()` is intentionally small:

```text
tk.Tk -> MonitorVolumeApp -> Tk mainloop
```

Keeping composition here makes `gui.py` responsible for application behavior without creating a second root or hidden launcher layer. Both source execution and `build_exe.ps1` use `app.py`.

### Unsupported entrypoint: `main.py`

`main.py` prints `This launcher is no longer supported. Run: python app.py` to standard error and returns `1`. It is not listed in `[tool.setuptools].py-modules`. It is a compatibility signal, not an alternate composition root.

### No command or HTTP entrypoint

`pyproject.toml` has no `[project.scripts]` or `[project.gui-scripts]` entry, and the code has no argument parser. There are no HTTP handlers, routes, sockets, or method/route semantics. The only user entry is process launch. Principal runtime inputs include GUI/native events, DDC results, Windows theme and system metrics, settings-path/environment resolution, settings contents, and tracked icon-file availability.

## Module responsibilities

| Module | Responsibility |
| --- | --- |
| `app.py` | Creates and runs the application. |
| `gui.py` | Coordinates Tk, monitor selection, readiness, DDC workers, rapid-write coalescing, persistence calls, tray lifecycle, and shutdown. |
| `ddc.py` | Defines `MonitorRef`, selection identity, monitor discovery, clamping, and DDC read/change/write wrappers. |
| `settings.py` | Loads and replaces the selected-monitor JSON file. |
| `overlay.py` | Implements the topmost, transient volume overlay. |
| `theme.py` | Samples the Windows theme, defines ttk dark styling, applies DWM dark chrome, and resolves the icon. |
| `windows_platform.py` | Declares the Win32 ctypes ABI and implements tray, keyboard-hook, and DWM helpers. |
| `main.py` | Rejects the old launch path. |

`ddc.change_monitor_volume()` is an internal helper but is not used by the GUI. The GUI uses its own cached-target and serialized-write flow so rapid key events can be coalesced.

## Monitor model and DDC/CI boundary

### Dependency boundary

`ddc.py` imports `monitorcontrol.get_monitors` and `monitorcontrol.vcp.VCPError`. An unavailable dependency is captured at import time so the GUI can start far enough to report a `DDCError` during discovery rather than failing the module import immediately.

The pinned `monitorcontrol==4.2.0` library maps `get_volume()` / `set_volume()` to MCCS VCP sound-volume code `0x62`. Inside that dependency—not in application code—the Windows backend enumerates with `EnumDisplayMonitors`, `GetNumberOfPhysicalMonitorsFromHMONITOR`, and `GetPhysicalMonitorsFromHMONITOR`; reads with `GetVCPFeatureAndVCPFeatureReply`; writes with `SetVCPFeature`; and ultimately releases handles with `DestroyPhysicalMonitor`. The application treats the library's monitor wrapper as the external hardware boundary and always enters it as a context manager:

```python
with monitor_ref.monitor:
    # get_volume() and/or set_volume(...)
```

Application code never touches a raw physical-monitor handle; the dependency owns the wrapper and handle lifetime. Keep application calls inside the existing context-manager boundary, but do not assume that leaving the context itself destroys the pinned Windows backend's retained handle.

### `MonitorRef` and selection identity

Each discovery result becomes an immutable `ddc.MonitorRef` with:

- `index`: one-based position in the current enumeration;
- `monitor`: the external monitorcontrol wrapper;
- `description`: `monitor.vcp.description`, trimmed, or `Unnamed monitor`;
- `description_ordinal`: one-based occurrence of that description in this enumeration.

The UI label is `"<index>. <description>"`. The persistent selection key is `(description, description_ordinal)`. The display index is deliberately not durable.

This identity avoids immediate ambiguity when two monitors report the same description, but it is not stable hardware identity. Port, topology, or enumeration-order changes can cause the same key to resolve to another identical monitor. There is no EDID or serial-number matching.

`pick_selected_monitor_index()` returns the saved match, otherwise the first monitor, otherwise `None`. The GUI persists the chosen key before proving that the selected monitor supports a volume read. An absent saved monitor therefore causes the first enumerated monitor to become the new saved choice.

### Read and write semantics

All volume targets and readbacks exposed by `ddc.py` are clamped to `0`–`100`.

- `read_monitor_volume()` opens the monitor context, calls `get_volume()`, and clamps the result.
- `set_monitor_volume()` opens one context, writes the clamped target, immediately reads it back, and returns the clamped readback.
- `change_monitor_volume()` reads, adds the requested delta, clamps the resulting target, writes only when the value changes, then reads back.

The set/readback sequence is not a database transaction and has no rollback. A write can reach the monitor and the subsequent read can fail. In that case the GUI's error path restores its previous cached display value even though the hardware may already have changed.

Application clamping defines the UI range; it does not prove that every device accepts every target. For example, the pinned dependency can raise `ValueError` when a monitor reports a maximum below the requested value. Such non-`VCPError` exceptions cross the generic GUI worker boundary and their message is shown in the status bar.

Discovery catches `NotImplementedError` and `VCPError` as a detection error. Individual DDC operations translate `VCPError` to `DDCError`. The GUI worker boundary catches other exceptions and exposes their message in the status bar.

## Volume request and concurrency flow

The GUI maintains both confirmed and requested state:

- `current_volume`: last successful read or write readback;
- `target_volume`: latest UI target;
- `_volume_write_inflight`: whether a DDC write worker owns the operation slot;
- `_pending_target_volume`: the newest target requested during that write.

A request follows this sequence:

1. `_request_volume_target()` clamps and stores the target.
2. The scale/text are updated optimistically and the overlay is shown immediately.
3. If a write is active, only `_pending_target_volume` is replaced.
4. Otherwise `_start_volume_write()` marks the app busy and launches `ddc-volume-write`.
5. `set_monitor_volume()` performs the hardware set and readback inside one context.
6. Success updates `current_volume`. If the latest pending target differs and the same selection remains active, the next worker starts without clearing the operation slot.
7. When no distinct follow-up is needed, confirmed state is displayed, the overlay is shown again with the readback (resetting its 1.4-second timer), and controls return to the normal ready state. An equal pending value can remain stored until `_start_volume_write()` clears it at the beginning of the next write, but it is not acted on.
8. Failure clears the pending target and busy/write flags, marks confirmed and target volume unknown, displays `--`, hides the optimistic overlay, clears hotkey readiness, and reports that Refresh is required. The native hook immediately passes subsequent physical volume-key presses back to Windows.

This last-target-wins design limits DDC traffic during key repeat while keeping the UI responsive. Replacing it with a worker per key event would introduce concurrent hardware access and stale completion ordering.

## Global keyboard event flow

`windows_platform.GlobalVolumeKeyListener` installs a `WH_KEYBOARD_LL` hook with thread ID `0`. Its ctypes callback is kept alive in `_hook_callback` for the controller's lifetime.

The callback passes unrelated keys directly to `CallNextHookEx`. It recognizes only:

- `VK_VOLUME_DOWN` (`0xAE`)
- `VK_VOLUME_UP` (`0xAF`)

When `MonitorVolumeApp._should_consume_volume_keys()` is false, those keys are also passed onward. On the first key-down of a physical press, the hook records whether that press should be consumed. Repeated key-down and the matching key-up retain that decision even if readiness changes mid-press. A consumed repeat enqueues a `-1` or `+1` delta only while readiness remains active; after readiness loss it remains consumed without producing more DDC requests until release. The mute key is not recognized.

The callback does not inspect the `KBDLLHOOKSTRUCT.flags` injection bits. Synthesized Volume Down/Up events are therefore handled like physical-key events.

`_update_hotkey_state()` computes the key-consumption state as:

```text
`_hotkeys_ready` is true
AND app not closing
AND the listener exists and its native hook is active
AND selected key exists
AND confirmed current volume exists
```

`_hotkeys_ready` is application/DDC state set after successful selected-volume reads or write readbacks. Native hook liveness is tracked independently by `GlobalVolumeKeyListener.is_active`; `_should_consume_volume_keys()` rechecks both the computed state and live listener state at callback time.

There is no user preference to disable the hook while leaving the app running. A write failure clears `current_volume`, `target_volume`, and `_hotkeys_ready`, so a disconnected or stale target releases subsequent physical key presses until a successful Refresh. A hook-start or runtime failure also prevents `_hotkeys_enabled` from becoming true even if later DDC reads succeed. If readiness is lost during an already-consumed press, that press remains consumed through key-up to avoid splitting one physical press between the monitor and Windows.

## Tray and window event flow

`TrayIconController` creates a per-process hidden Win32 window named with the process ID and controller identity. Its message loop handles private show/hide/exit messages, `Shell_NotifyIconW` callbacks, and a native popup menu.

- Icon ID: `1`
- Tooltip: `windows-ddc`
- Double-click: Restore
- Context menu: Restore (`1001`) and Exit (`1002`)

The controller tries to load `windows-ddc.ico` at the Windows small-icon dimensions and falls back to `IDI_APPLICATION`. The main Tk window also tries the same tracked icon; icon failure is nonfatal.

The tray's native window is created synchronously from the caller's perspective because `start()` waits for `_ready`. Adding the visible notification icon is asynchronous: `show()` posts a native message and `MonitorVolumeApp.minimize_to_tray()` immediately withdraws Tk. If icon addition fails afterward, its error is posted to the now-hidden status bar and the window can become unreachable. Taskbar/Explorer recreation through `TaskbarCreated` is not handled, so a lost icon is not automatically restored.

Minimizing a visible Tk window schedules an idle check and withdraws it only if the state is `iconic`. Restoring hides the tray icon, normalizes/lifts/focuses the Tk window, and reapplies dark title-bar chrome. Closing the visible window follows the full shutdown path rather than minimizing.

## Frontend and overlay

The control window is a non-resizable Tk/ttk layout at least 440 pixels wide. It contains:

- a read-only monitor combobox;
- Refresh;
- a `0`–`100` scale;
- one-point decrement/increment buttons;
- a percentage label and status bar.

Widget state derives from `_busy`, monitor availability, and confirmed volume. During an active write the volume controls remain enabled so a new last target can be queued.

`VolumeOverlay` is a borderless tool `Toplevel` with fixed dark colors and a progress bar. Topmost, alpha `0.7`, and tool-window attributes are best-effort because `TclError` is ignored. It is independent of the main light/dark theme and hides after `AUTO_HIDE_MS = 1400`. Positioning uses Tk's primary-screen dimensions: horizontal centering clamped to at least 24 pixels from the left, and 88 pixels above the screen bottom clamped to at least 32 pixels from the top. It is not selected-monitor-aware, work-area-aware, or explicitly DPI-aware.

`theme.is_windows_dark_mode_enabled()` reads the current user's:

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize\AppsUseLightTheme
```

Only a DWORD value of `0` selects dark mode. The preference is sampled once at startup. Dark mode creates a custom ttk theme and tries DWM attributes `20` then `19`; light mode prefers `vista`, `xpnative`, then `winnative` when available. The registry is read-only.

The real UI screenshots are tracked at `docs/app.png` (452×203) and `docs/overlay.png` (210×122). There is no automated screenshot workflow.

## Persistent data and filesystem ownership

The only intended durable application file is normally:

```text
%APPDATA%\windows-ddc\settings.json
```

If `APPDATA` is unset or empty, `settings.SETTINGS_PATH` uses:

```text
<home>\windows-ddc\settings.json
```

It inherits the current user's filesystem permissions. The schema is:

```json
{
  "selected_monitor": {
    "description": "physical monitor description",
    "ordinal": 1
  }
}
```

`save_selected_monitor_key()` creates the parent directories, writes indented UTF-8 JSON to sibling `settings.tmp`, and replaces `settings.json`. This reduces exposure to a partially written destination but does not coordinate multiple processes; instances share both paths. An interrupted or failed replacement can leave `settings.tmp`, and there is no cleanup path. The GUI deliberately ignores `OSError` from saving, so persistence failure is not visible in the status bar.

There is no schema version or migration history. Missing files, I/O failures, invalid JSON syntax, and invalid nested selection objects return no saved selection. A valid JSON top-level scalar or array currently reaches `data.get(...)` and raises `AttributeError` during application construction. The writer emits a numeric integer ordinal, but the loader's `isinstance(ordinal, int)` check also accepts JSON `true` as ordinal `1` because Python's `bool` is an `int` subclass.

The monitor's actual volume is external mutable hardware state, not app storage. The app reads it after discovery or selection and never backs it up or restores it on exit.

### Backup and restore format

Backup is a plain copy of `settings.json` while all instances are stopped. Restore is replacement with a UTF-8 JSON object matching the schema above. Moving the file aside resets only saved selection. There is no archive, database dump, encryption, integrity marker, or built-in backup command.

Tests must replace `settings.SETTINGS_PATH` with a unique temporary path. They must not redirect or mutate a user's live app-data directory.

## Authentication and security boundaries

There is no account or administrative model because there is no remote or multi-user application interface. The process runs in the launching user's interactive session and the repository contains no elevation manifest or privileged helper.

The security-relevant boundaries are local:

1. **Global input hook.** The low-level hook receives desktop keyboard callbacks, acts only on Volume Down/Up, does not persist events, and can suppress those keys globally while ready.
2. **Physical hardware writes.** DDC/CI writes change monitor state and may produce an audible volume change. They are neither transactional nor rolled back.
3. **Native ABI.** Incorrect ctypes structures, argument types, callback signatures, or callback lifetimes can corrupt or crash the process.
4. **Cross-thread UI.** Tk is not thread-safe; queues are the required ownership boundary.
5. **Per-user file.** Settings are user-writable, unencrypted, and unversioned, but contain only a monitor description and ordinal.

Runtime code has no network path. Dependency installation and Nuitka's `--assume-yes-for-downloads` build can contact external package/toolchain servers; these are development/build effects, not application runtime behavior.

## Build and deployment architecture

`pyproject.toml` uses `setuptools.build_meta` as its PEP 517 backend, with unpinned `setuptools` and `wheel` build-system requirements. It declares project version `0.1.0`, Python `>=3.10`, and explicit flat modules:

```text
app, gui, ddc, settings, theme, overlay, windows_platform
```

The direct runtime dependency is pinned to `monitorcontrol==4.2.0`. The `build` extra pins `Nuitka==2.4.8`. There is no lockfile; build-system requirements and transitive build dependencies are not fully pinned.

`build_exe.ps1` resolves `python`, changes to its own repository directory, checks `app.py` and `windows-ddc.ico`, then invokes Nuitka with:

- `--onefile`
- `--windows-console-mode=disable`
- `--enable-plugins=tk-inter`
- `--windows-icon-from-ico=windows-ddc.ico`
- `--include-data-files=windows-ddc.ico=windows-ddc.ico`
- `--output-dir=dist`
- `--output-filename=windows-ddc.exe`
- `--remove-output`
- `--assume-yes-for-downloads`
- entrypoint `app.py`

The runtime data copy of the icon is essential because `theme.APP_ICON_PATH` resolves a file beside `theme.py`; an embedded PE icon alone does not satisfy that lookup.

The output is ignored `dist\windows-ddc.exe`. Nuitka support/toolchain downloads are accepted automatically, an existing named artifact may be overwritten, and `--remove-output` removes the intermediate build directory after output is produced. The repository defines no installer, Windows service, autostart entry, signing step, CI workflow, publishing script, or deployment environment.

The setuptools configuration defines no package-data rule for `windows-ddc.ico`; generated `SOURCES.txt` also omits it. An ordinary wheel/non-editable source install therefore falls back to default icons at runtime. Editable source execution sees the repository file, while the Nuitka build explicitly includes it.

Ignored `windows_ddc.egg-info\` is setuptools-generated residue, not source of truth, and can lag behind `README.md` or `pyproject.toml`. Ignored `__pycache__\` and `dist\` are also generated. None should be hand-maintained or committed.

## Background activity and absent subsystems

The tray and hook message pumps are event loops, and DDC workers are background threads, but there are no scheduled jobs, periodic monitor polls, job queues, retry workers, or durable events. Initial discovery is a one-shot scheduled callback; subsequent discovery happens only when the user activates Refresh.

There is likewise no web frontend/backend split, API request flow, database schema, migration procedure, realtime protocol, authentication provider, health endpoint, readiness probe, liveness probe, or external service integration to operate.

## Health and failure behavior

The status bar is the only normal health surface:

- startup begins at `Searching for monitors...`;
- successful initial read reports Ready, monitor count, and selected description;
- empty discovery reports `No DDC/CI monitors found.`;
- monitor, hook, and tray exceptions are formatted into status text.

The packaged executable disables its console, and no file logger exists. If the main window is withdrawn, a tray failure can also hide the only error surface.

Volume-control readiness requires monitors plus a confirmed volume. Key-consumption readiness additionally requires an active native listener. A refresh clears `_hotkeys_ready` while it runs and restores it after a successful read. A write failure marks the volume unknown and also requires Refresh before monitor control resumes. There is no automatic retry after topology changes and no live reconciliation with volume changes from the monitor OSD or another tool.

Known failure-state caveats include:

- a stale/hotplug target is detected only when the user invokes Refresh or an attempted DDC operation fails;
- the physical key press that discovers a stale target remains consumed through its release, while subsequent presses pass through;
- tray/icon loss can strand a withdrawn main window;
- `start()` waits on native readiness events without a timeout;
- a set may succeed before its readback fails;
- an exception in a queued Tk callback can stop recurring queue polling.

## Development and testing

The repository contains a small standard-library unit-test suite for fail-safe hotkey state and key-event pairing. It has no third-party test framework configuration, linter, formatter, type checker, or CI workflow. Low-risk validation consists of that suite, Python compilation, an installed-dependency check, PowerShell parsing, tracked/staged diff whitespace checks, and explicit status review; exact commands are in `README.md` and `AGENTS.md`.

Do not use application launch as a routine smoke test. It reads and writes user settings, starts a global hook, creates native tray state, and contacts physical monitor hardware. `build_exe.ps1` also writes ignored artifacts and may download tooling.

An authorized manual Windows/hardware pass is required for changes to discovery, selection, DDC I/O, key interception, tray lifecycle, theme/chrome, overlay, or shutdown. Tests of settings code must patch `SETTINGS_PATH` to a temporary location. Pure DDC wrapper tests should use fake context-manager monitor objects.

## Things to preserve

- Keep `app.py` as the single supported composition root and `main.py` as an explicit unsupported stub unless compatibility policy changes.
- Keep all Tk access on the main thread; use `_result_queue`, `_hotkey_delta_queue`, and `_post_to_ui()` at cross-thread boundaries.
- Keep DDC work off Tk and serialize/coalesce writes. Do not start one hardware worker per key event.
- Keep monitorcontrol operations inside the monitor context manager and clamp all public volume results/targets to `0`–`100`.
- Preserve system key pass-through until a selected monitor has a successful volume read, and clear/pass through safely on loss of readiness.
- Keep native ctypes callbacks strongly referenced and stop hook/tray loops before destroying Tk.
- Do not use the displayed monitor index as persistent identity. Any identity/schema change needs backward-compatible loading or an explicit migration.
- Never touch live per-user settings in automated work; use a temporary path.
- Treat physical monitor volume and global keyboard handling as safety-sensitive side effects.
- Keep `[tool.setuptools].py-modules` synchronized when distributable runtime modules are added, renamed, or removed.
- Keep `windows-ddc.ico`, `theme.APP_ICON_PATH`, and both Nuitka icon flags synchronized.
- Do not treat generated egg-info, `dist\`, or `__pycache__\` as authoritative source.
- Do not document APIs, services, authentication, databases, health probes, hotplug polling, automatic startup, signing, or deployment automation unless they are actually implemented.
