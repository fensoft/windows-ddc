# Architecture

This document describes the tagged `0.1.0` release and the current repository sources. `windows-ddc` is a small Windows desktop process: Tk owns the UI, native Win32 message loops provide display-change protection, the tray icon, and the global volume-key hook, and short-lived workers perform DDC/CI operations against physical monitors.

There is no server-side tier. The project has no HTTP API, listening port, database, container, service, authentication system, broker, cron process, telemetry client, or runtime network dependency.

## High-level flow

1. The supported entrypoint, `app.py`, acquires a session-local named mutex. A duplicate broadcasts a restore request and exits before creating Tk or application subsystems.
2. The primary instance configures a rotating per-user diagnostic log, creates one `tk.Tk`, constructs `gui.MonitorVolumeApp`, and enters `root.mainloop()` while retaining the mutex handle.
3. `MonitorVolumeApp.__init__()` samples the Windows app-theme preference, reads the optional current-user autostart value, and loads the saved monitor selection and Change speed preference from `settings.py`.
4. It builds the fixed-size control window, status bar, and hidden, native-no-activate `overlay.VolumeOverlay` on the Tk thread.
5. It starts a dedicated `DisplayChangeListener` hidden window. Failure leaves all monitor-volume writes disabled; the app can still enumerate and display status.
6. It independently starts the tray controller and global keyboard hook. Tk publishes immutable menu snapshots to the tray, while tray Refresh/selection/restore/exit actions enqueue Tk callbacks. Their failures remain nonfatal to the other subsystems.
7. It schedules the recurring Tk queue poll and a one-shot initial monitor refresh after 50 ms.
8. The refresh worker enumerates DDC wrappers and Windows monitor identities, exact-matches the saved target, and reads its volume. With no saved selection, automatic selection occurs only when exactly one verifiable monitor exists.
9. The worker enqueues a tokened completion callback. The Tk queue poll applies the monitor list, selection, displayed volume, readiness, and status text.
10. A volume request updates the UI optimistically, resolves the cursor's Windows display work area for the overlay with selected-display fallback, then a serialized worker reacquires all wrappers and exact-matches the identity before set/readback.
11. The readback becomes authoritative. A coalesced follow-up starts another worker and therefore performs another fresh discovery/match.
12. Display/device notifications invalidate a thread-safe topology generation immediately, release key consumption, clear pending writes, and schedule debounced discovery with bounded retries.
13. A 10-second watchdog fails a stalled DDC operation closed without releasing its serialization slot; when the worker eventually returns, its result is ignored and read-only rediscovery follows.
14. Shutdown disables key consumption, cancels Tk timers, stops display/hook/tray loops, reports missed stop deadlines, closes the overlay, destroys Tk, closes the diagnostic handler, and releases the mutex handle.

## Runtime process and thread ownership

Source execution uses one interactive process per Windows session, enforced by `SingleInstanceGuard` and the named `Local\windows-ddc-single-instance` mutex. The one-file Nuitka executable adds a compiler-controlled bootstrap/extraction phase, but the repository does not customize that phase.

| Thread | Lifetime | Owns or performs | Communication boundary |
| --- | --- | --- | --- |
| Tk main thread | Process lifetime | Widgets, state mutation, selection persistence, status, overlay, queue draining, diagnostic-handler lifecycle | Receives queued callables and key deltas every 50 ms |
| `display-change-listener` | Long-lived daemon | Hidden Win32 window, monitor device registration, `WM_DISPLAYCHANGE` / `WM_DEVICECHANGE` message pump | Invalidates the topology generation and enqueues Tk work |
| `tray-icon` | Long-lived daemon | Hidden Win32 window, notification icon, live snapshot menu, message pump | Reads lock-protected immutable state; controller actions enqueue Tk work through `_post_to_ui()` |
| `volume-key-hook` | Long-lived daemon | `WH_KEYBOARD_LL` hook and message pump | Reads readiness through `should_consume()` and enqueues integer deltas |
| `ddc-gui-worker` | One short-lived daemon per accepted refresh/selection read | Enumeration and selected-monitor volume reads | Enqueues success or failure callable |
| `ddc-volume-write` | One short-lived daemon at a time | Selected-monitor set followed by readback | Enqueues write success or failure callable |

`MonitorVolumeApp._result_queue` carries zero-argument callbacks into Tk. `_hotkey_delta_queue` carries signed step changes. `_poll_queues()` drains all result callbacks first, combines key deltas accumulated during the poll interval, then schedules itself again after 50 ms. Each callback and the combined adjustment are caught independently; a failure is reported through Tk's callback reporter, fails monitor control closed, and the next poll is scheduled from `finally`.

The `_busy` flag prevents a new refresh/selection worker while another general operation is active. Volume controls remain usable during a valid active volume write, but they update `_pending_target_volume` rather than starting another DDC worker. A token identifies the one application-issued DDC operation, and a Tk watchdog tracks it. A timeout disables controls and interception but deliberately retains the token and busy/write flags until the uncancellable worker returns. This is the application's serialization boundary; there is no separate DDC lock.

Display, tray, and hook startup readiness waits and shutdown joins each have two-second deadlines. Stop methods report whether their native thread exited; shutdown writes missed deadlines or stop exceptions to the diagnostic log, standard error, and the status bar before destroying Tk. DDC workers are daemon threads and are not cancelled or joined; `_closing` drops their eventual callbacks.

All Tk calls must remain on the Tk thread. A native or DDC thread must enqueue work rather than touching widgets. Queued callbacks must remain small and exception-safe even though the polling boundary now contains and reports their failures.

## Application entrypoints and composition

### Supported entrypoint: `app.py`

`app.main()` is intentionally small:

```text
SingleInstanceGuard -> configure logging -> tk.Tk -> MonitorVolumeApp -> Tk mainloop -> close logging -> release guard
```

The guard is acquired before logging or Tk and always closed in `finally`. This keeps a duplicate from opening the rotating log concurrently with the primary. `ERROR_ALREADY_EXISTS` makes the duplicate register and broadcast the restore message, then return `0` without reading settings or creating hooks, tray state, or DDC workers. Keeping composition here makes `gui.py` responsible for application behavior without creating a second root or hidden launcher layer. Both source execution and `build_exe.ps1` use `app.py` and therefore share the same mutex.

### Unsupported entrypoint: `main.py`

`main.py` prints `This launcher is no longer supported. Run: python app.py` to standard error and returns `1`. It is not listed in `[tool.setuptools].py-modules`. It is a compatibility signal, not an alternate composition root.

### No command or HTTP entrypoint

`pyproject.toml` has no `[project.scripts]` or `[project.gui-scripts]` entry, and the code has no argument parser. There are no HTTP handlers, routes, sockets, or method/route semantics. The only user entry is process launch. Principal runtime inputs include GUI/native events, DDC results, Windows theme and system metrics, the current-user Run value, settings-path/environment resolution, settings contents, and tracked icon-file availability.

## Module responsibilities

| Module | Responsibility |
| --- | --- |
| `app.py` | Enforces the single-instance boundary, then creates and runs the application. |
| `autostart.py` | Quotes source/packaged launch commands and reads/writes the named current-user Run value. |
| `diagnostics.py` | Configures and closes the bounded per-user rotating log and provides component loggers. |
| `gui.py` | Coordinates Tk, monitor selection, readiness, DDC workers, rapid-write coalescing, overlay display targeting, persistence calls, tray state/lifecycle, and shutdown. |
| `ddc.py` | Defines `MonitorRef`, selection identity, monitor discovery, clamping, and DDC read/change/write wrappers. |
| `settings.py` | Atomically loads and replaces the selected-monitor and Change speed JSON settings. |
| `overlay.py` | Calculates work-area/DPI-aware geometry and implements focus-safe topmost transient volume and unavailable/error presentations. |
| `theme.py` | Samples the Windows theme, defines ttk dark styling, applies DWM dark chrome, and resolves the icon. |
| `windows_platform.py` | Declares the Win32 ctypes ABI and implements the single-instance mutex/restore signal, monitor identity/EDID inventory, display work-area/scale lookup, no-activate overlay operations, display notifications, snapshot-driven tray menu, keyboard-hook, and DWM helpers. |
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

Each immutable `MonitorRef` retains the transient index, monitorcontrol wrapper, description/ordinal, short GDI display name, and optional `MonitorIdentity`. The combobox adds `S/N <serial>` when usable, otherwise the short `DISPLAYn` name; the full device-interface path remains internal.

`enumerate_monitors()` takes a Windows identity snapshot before and after `get_monitors()`. Identity enumeration follows the same `EnumDisplayMonitors` traversal, maps a one-physical-monitor/one-active-interface logical display, reads EDID through SetupAPI, and returns no identity for ambiguous mappings. A changed snapshot or wrapper/identity count mismatch rejects the discovery.

Stable matching follows these rules:

1. A unique normalized EDID manufacturer/product/serial tuple matches across device-path changes.
2. Duplicate serial tuples require an exact case-insensitive saved device path.
3. A monitor without a usable serial requires its exact saved device path.
4. Missing, ambiguous, and unverifiable targets never fall back to another monitor.
5. With no saved target, only one verifiable monitor can be selected automatically.

Legacy description/ordinal settings are loaded, but the ordinal is not trusted after topology changes. A legacy description promotes only when exactly one verifiable current monitor has that description. Selection is persisted only after a successful volume read.

### Read and write semantics

All volume targets and readbacks exposed by `ddc.py` are clamped to `0`–`100`.

- `read_monitor_volume()` opens the monitor context, calls `get_volume()`, and clamps the result.
- `set_monitor_volume()` opens one context, writes the clamped target, immediately reads it back, and returns the clamped readback.
- `change_monitor_volume()` reads, adds the requested delta, clamps the resulting target, writes only when the value changes, then reads back.

The set/readback sequence is not a transaction and has no rollback. A write can reach the monitor before readback or topology validation fails. The GUI then marks volume unknown, disables control, reports uncertainty in the overlay/status, and performs read-only rediscovery without retrying the write.

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
5. The worker calls `enumerate_monitors()`, exact-matches the saved identity, and checks its captured topology generation immediately before the write.
6. `set_monitor_volume()` performs set/readback only through the newly acquired wrapper and inside one context.
7. Success is accepted only if the generation remains current. A distinct pending target starts another worker and another discovery/match.
8. When no follow-up remains, confirmed readback is displayed and readiness is restored.
9. Missing/ambiguous identity, DDC failure, or a stale generation clears pending state, marks volume unknown, releases interception, shows an unavailable overlay, and schedules read-only rediscovery.
10. If the 10-second watchdog fires first, the operation token remains active and no new worker can start. The late completion is non-authoritative; only after it arrives is the slot released and a read-only refresh scheduled.

This last-target-wins design limits DDC traffic while ensuring every actual hardware write—not every key-repeat message—uses fresh handles. An in-flight native DDC call cannot be cancelled; generation checks reduce but cannot remove the final check-to-write race.

The watchdog bounds how long readiness remains trusted; it does not cancel or terminate the native DDC call.

## Global keyboard event flow

`windows_platform.GlobalVolumeKeyListener` installs a `WH_KEYBOARD_LL` hook with thread ID `0`. Its ctypes callback is kept alive in `_hook_callback` for the controller's lifetime.

The callback passes unrelated keys directly to `CallNextHookEx`. It recognizes only:

- `VK_VOLUME_DOWN` (`0xAE`)
- `VK_VOLUME_UP` (`0xAF`)

When `MonitorVolumeApp._should_consume_volume_keys()` is false, those keys pass onward. If a previously configured target is unavailable, the first key-down in that invalid period also queues an error overlay without consuming the event. The notice is latched until readiness is restored or a new invalidation begins. On a consumed press, repeated key-down and matching key-up retain the initial consume decision; readiness loss stops new deltas but does not split a press between the app and Windows. The hook's numeric step is updated through a lock-protected setter when Tk handles the persistent Slow (`+1`), Medium (`+2`), or Fast (`+3`) Change speed event, so the native thread never reads Tk state. The mute key is not recognized.

The callback does not inspect the `KBDLLHOOKSTRUCT.flags` injection bits. Synthesized Volume Down/Up events are therefore handled like physical-key events.

`_update_hotkey_state()` computes the key-consumption state as:

```text
`_hotkeys_ready` is true
AND app not closing
AND the display-change listener is live
AND the topology generation is valid
AND the listener exists and its native hook is active
AND selected key exists
AND confirmed current volume exists
```

`_hotkeys_ready` is application/DDC state set after successful selected-volume reads or write readbacks. Native hook liveness is tracked independently by `GlobalVolumeKeyListener.is_active`; `_should_consume_volume_keys()` rechecks both the computed state and live listener state at callback time.

There is no user preference to disable the hook while leaving the app running. Display invalidation or write failure clears readiness so subsequent physical presses pass through until exact-match rediscovery and a successful read. A hook failure disables only global interception; a display-listener failure disables all monitor-volume writes.

## Display-change event flow

`DisplayChangeListener` owns a separate hidden window registered for `GUID_DEVINTERFACE_MONITOR`. `WM_DISPLAYCHANGE` and relevant `WM_DEVICECHANGE` messages synchronously clear a thread-safe topology-valid event and increment a generation before posting Tk work. Tk then clears cached/pending volume state and schedules a 500 ms debounced refresh; transient automatic failures retry after 1, 2, and 4 seconds. Callbacks do no blocking discovery or Tk work on the native thread.

## Tray and window event flow

`TrayIconController` creates a per-process hidden Win32 window named with the process ID and controller identity. Its message loop handles private show/hide/exit messages, the registered `TaskbarCreated` broadcast, `Shell_NotifyIconW` callbacks, and a native popup menu.

- Icon ID: `1`
- Tooltip: `windows-ddc`
- Double-click: Restore
- Context menu status: active monitor, last confirmed volume, and routing enabled/disabled
- Context menu actions: Restore (`1001`), Exit (`1002`), Refresh (`1003`), and up to 100 selectable monitor commands starting at `2000`

Tk builds `TrayMenuState` from `selected_key`, confirmed `current_volume`, `_hotkeys_enabled`, and every currently verifiable monitor, then replaces the controller's snapshot under a lock whenever those values change. The tray thread copies the snapshot when the popup opens. Checked monitor entries retain that captured `SavedMonitorSelection`; even if Tk publishes a newer list while the native menu is open, its returned command maps to the old menu's exact identity rather than the same numeric index in the new list. Labels normalize whitespace, escape Win32 mnemonic ampersands, and are bounded to 96 characters.

Refresh and monitor-switch callbacks never invoke Tk directly. The controller calls closures that enqueue `refresh_monitors()` or `_select_monitor_from_tray()` through `_post_to_ui()`. A switch starts normal exact-identity discovery/read and is rejected while another DDC operation is active. Menu volume remains the authoritative read/readback value during optimistic or coalesced writes; routing reflects the same `_hotkeys_enabled` state used by the native hook.

The controller tries to load `windows-ddc.ico` at the Windows small-icon dimensions and falls back to `IDI_APPLICATION`. The main Tk window also tries the same tracked icon; icon failure is nonfatal.

The tray's native window is created synchronously from the caller's perspective because `start()` waits up to two seconds for `_ready`. `show()` creates a per-request completion event, posts `WM_TRAY_SHOW`, and waits up to two seconds for the tray thread's actual `Shell_NotifyIconW` result. `MonitorVolumeApp.minimize_to_tray()` withdraws Tk only after that acknowledgement. A native failure, stopped controller, post failure, or timeout keeps/restores and normalizes the main window, hides any late icon best-effort, and reports the error in the visible status bar.

The controller registers the shell's `TaskbarCreated` message and the app's stable duplicate-launch restore message during construction. A restore broadcast invokes the normal tray-to-Tk restore callback. When Explorer recreates the taskbar, a previously visible icon is re-added with `NIM_ADD` and its notification version is restored. If re-registration fails, the error crosses the queue boundary and Tk restores the main window instead of leaving the process unreachable.

Minimizing a visible Tk window schedules an idle check and withdraws it only if the state is `iconic`. Restoring hides the tray icon, normalizes/lifts/focuses the Tk window, and reapplies dark title-bar chrome. Closing the visible window follows the full shutdown path rather than minimizing.

## Frontend and overlay

The control window is a non-resizable Tk/ttk layout at least 520 pixels wide so serial-bearing monitor labels remain readable. It contains:

- a read-only monitor combobox;
- Refresh;
- a `0`–`100` scale;
- a persistent Slow/Medium/Fast Change speed selector and decrement/increment buttons;
- a percentage label and status bar.

Widget state derives from `_busy`, monitor availability, confirmed volume, display-listener liveness, and topology validity. During a valid active write the volume controls remain enabled so a new last target can be queued.

`VolumeOverlay` is a borderless tool `Toplevel` with fixed dark colors. Normal mode shows percentage/progress and hides after 1.4 seconds. Error mode shows a red `Unavailable` heading plus wrapped reason text, hides the progress bar, and remains for 2.8 seconds. Alpha `0.7` and Tk's tool-window attribute remain best-effort.

Every presentation takes a fresh `GetCursorPos` reading and current `MONITORINFOEXW` snapshots. The display containing the cursor wins. If the cursor cannot be resolved to an enumerated display, the selected `MonitorRef.display_device_name` is used, with the primary or first enumerated display as the final fallback. Geometry is bottom-centered inside `rcWork`, supports negative virtual-screen coordinates, scales the side/top/bottom margins with `GetScaleFactorForMonitor`, and clamps oversized content inside the available work area.

Focus safety is fail-closed. The native top-level HWND must accept the preserved extended styles plus `WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE` before Tk deiconifies it. `SetWindowPos(HWND_TOPMOST, ..., SWP_NOACTIVATE | SWP_SHOWWINDOW)` then positions and reveals it without a Tk `lift()` or focus call. A style or native-show failure withdraws the overlay instead of allowing an activating fallback.

`theme.is_windows_dark_mode_enabled()` reads the current user's:

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize\AppsUseLightTheme
```

Only a DWORD value of `0` selects dark mode. The preference is sampled once at startup. Dark mode creates a custom ttk theme and tries DWM attributes `20` then `19`; light mode prefers `vista`, `xpnative`, then `winnative` when available. This theme lookup is read-only.

The manually maintained screenshots are tracked at `docs/app.png` (452×203) and `docs/overlay.png` (210×122). They predate the wider identity selector, Change speed selector, Start with Windows checkbox, and error presentation; there is no automated screenshot workflow, so updates require real scrubbed captures.

## Persistent data, registry, and filesystem ownership

The intended durable state is the settings file, bounded diagnostic logs, and an optional named current-user Run value. The normal settings path is:

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
  "schema_version": 2,
  "change_speed": "medium",
  "selected_monitor": {
    "description": "physical monitor description",
    "identity": {
      "device_path": "Windows monitor interface path",
      "manufacturer_id": "DEL",
      "product_code": 4660,
      "serial_number": "EXAMPLE-SERIAL"
    }
  }
}
```

`save_selected_monitor_key()` requires a stable identity and preserves a valid Change speed. `save_change_speed()` normalizes its value and preserves current schema-v2 or legacy monitor-selection data. Both create the parent directories, write indented UTF-8 JSON to sibling `settings.tmp`, and replace `settings.json`. This reduces exposure to a partial destination but provides no file lock. The session mutex prevents ordinary project instances in one Windows session from racing, but separate sessions and external tools are not coordinated. Persistence failure is not visible in the status bar.

The monitor-selection writer emits schema version 2. Its loader accepts the old unversioned description/ordinal shape for safe one-time promotion, rejects boolean ordinals, and treats missing files, I/O failures, invalid JSON, non-object roots, unknown versions, and invalid nested data as no selection. Change speed is an independent top-level preference: missing or invalid values default to `slow`, and valid values are `slow`, `medium`, and `fast`.

The monitor's actual volume is external mutable hardware state, not app storage. The app reads it after discovery or selection and never backs it up or restores it on exit.

`diagnostics.LOG_PATH` normally resolves to `%LOCALAPPDATA%\windows-ddc\windows-ddc.log`, falling back to `APPDATA` and then the home directory. `RotatingFileHandler` caps the current log at 512 KiB and retains two backups. Handler creation failure installs a managed `NullHandler`, so an unwritable diagnostic location never blocks application startup. Routine GUI messages log operation classes rather than monitor descriptions, identities, or device paths; unexpected top-level tracebacks can still contain local source paths.

`autostart.py` treats `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\windows-ddc` as the Start with Windows source of truth. Reading occurs during Tk construction; writes and deletion occur only from the checkbox callback. A packaged launch quotes the absolute original one-file path from `sys.argv[0]`; a source launch quotes a sibling `pythonw.exe` when available plus the repository `app.py`. The helper rejects commands longer than the Windows Run-key limit of 260 characters. Registry errors restore the prior checkbox value, update status, and emit a privacy-safe diagnostic. Moving the registered target can leave a stale value until the user disables or replaces it.

### Backup and restore format

Backup is a plain copy of `settings.json` while all instances are stopped. Restore is replacement with a UTF-8 JSON object matching the schema above. Moving the file aside resets saved selection and Change speed. There is no archive, database dump, encryption, integrity marker, or built-in backup command.

Tests must replace `settings.SETTINGS_PATH` and diagnostic destinations with unique temporary paths and mock `autostart.winreg`. They must not read, redirect, mutate, or delete a user's live app-data files or Run value.

## Authentication and security boundaries

There is no account or administrative model because there is no remote or multi-user application interface. The process runs in the launching user's interactive session and the repository contains no elevation manifest or privileged helper.

The security-relevant boundaries are local:

1. **Global input hook.** The low-level hook receives desktop keyboard callbacks, acts only on Volume Down/Up, does not persist events, and can suppress those keys globally while ready.
2. **Physical hardware writes.** DDC/CI writes change monitor state and may produce an audible volume change. They are neither transactional nor rolled back.
3. **Native ABI.** Incorrect ctypes structures, argument types, callback signatures, or callback lifetimes can corrupt or crash the process.
4. **Cross-thread UI.** Tk is not thread-safe; queues are the required ownership boundary.
5. **Per-user files.** Settings and diagnostics are user-writable and unencrypted. Settings contain monitor identity metadata; routine diagnostics avoid it, although unexpected tracebacks can contain local paths. A device-interface path is machine-specific but is not a credential.
6. **Current-user autostart.** The opt-in Run value stores an absolute local command and executes it at sign-in. It requires no administrator access, but moving the target can leave stale machine-specific path data.

Runtime code has no network path. Dependency installation and Nuitka's `--assume-yes-for-downloads` build can contact external package/toolchain servers; these are development/build effects, not application runtime behavior.

## Build and deployment architecture

`pyproject.toml` uses `setuptools.build_meta` as its PEP 517 backend, with unpinned `setuptools` and `wheel` build-system requirements. It declares project version `0.1.0`, Python `>=3.10`, and explicit flat modules:

```text
app, autostart, diagnostics, gui, ddc, settings, theme, overlay, windows_platform
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

The output is ignored `dist\windows-ddc.exe`. Nuitka support/toolchain downloads are accepted automatically, an existing named artifact may be overwritten, and `--remove-output` removes the intermediate build directory after output is produced. The application can create its current-user autostart value interactively, but the repository defines no installer, Windows service, machine-wide startup registration, signing step, CI artifact build, publishing script, or deployment environment.

The setuptools configuration defines no package-data rule for `windows-ddc.ico`; generated `SOURCES.txt` also omits it. An ordinary wheel/non-editable source install therefore falls back to default icons at runtime. Editable source execution sees the repository file, while the Nuitka build explicitly includes it.

Ignored `windows_ddc.egg-info\` is setuptools-generated residue, not source of truth, and can lag behind `README.md` or `pyproject.toml`. Ignored `__pycache__\` and `dist\` are also generated. None should be hand-maintained or committed.

## Background activity and absent subsystems

Display, tray, and hook message pumps are event loops, and DDC workers are background threads. There is no periodic monitor or volume poll. Display notifications schedule a 500 ms debounced refresh and at most three retry timers; manual Refresh and every actual write also perform discovery. There are no durable events, job queues, or cron-style tasks.

There is likewise no web frontend/backend split, API request flow, database schema, migration procedure, realtime protocol, authentication provider, health endpoint, readiness probe, liveness probe, or external service integration to operate.

## Health and failure behavior

The status bar is the immediate health surface:

- startup begins at `Searching for monitors...`;
- successful initial read reports Ready, monitor count, and selected description;
- empty discovery reports `No DDC/CI monitors found.`;
- monitor, hook, tray, and autostart-update exceptions are formatted into status text.

The packaged executable disables its console. `diagnostics.py` retains lifecycle, thread/component, native-subsystem, settings-save, autostart-update, DDC watchdog, refresh/write, queued-callback, shutdown, and top-level failure records in a bounded per-user log. Tray failures still restore the main window so an immediate status remains visible.

Volume-control readiness requires a live display listener, valid topology generation, unique selected identity, and confirmed volume. Key-consumption readiness additionally requires an active keyboard hook. Refresh clears readiness while it runs and restores it only after an exact match and successful read. Topology and write failures trigger bounded automatic rediscovery; external OSD/tool volume changes are not reconciled automatically.

Known failure-state caveats include:

- an in-flight native DDC call cannot be cancelled, so a topology event can race with the final pre-write generation check;
- a DDC call that never returns keeps monitor control disabled until the application is restarted; the worker stays daemonized and no concurrent replacement call is started;
- if Windows emits no notification before a first post-change press, that press can be consumed while asynchronous revalidation rejects the write; subsequent presses pass through;
- a set may succeed before its readback fails;
- duplicate restoration is a best-effort broadcast and can be missed during the primary instance's very early startup or shutdown;
- diagnostic-handler creation is deliberately nonfatal, so an unwritable log location leaves only the status bar (and standard error in source runs).

## Development and testing

The standard-library test suite covers fail-safe hotkeys, EDID parsing, unique/duplicate/path identity matching, schema migration, Change speed persistence, source/packaged autostart command quoting and mocked registry behavior, diagnostic writing/rotation/setup failure, topology generations, display-message routing, fresh-wrapper writes, single-instance composition and signaling, rich tray rendering/snapshot command stability/Tk queue routing, multi-screen/work-area/DPI overlay placement, native no-activate behavior, acknowledged tray addition, visible-window fallback, Explorer restart recovery, queue-callback containment, DDC watchdog state, bounded native lifecycle waits, CI workflow safety, and shutdown diagnostics. It has no third-party test framework, linter, formatter, or type checker.

`.github/workflows/ci.yml` runs on `windows-latest` for pushes, pull requests, and manual dispatches with a Python 3.10/3.14 matrix. It installs the runtime project, runs the unit suite, compiles runtime modules, checks installed dependencies, parses `build_exe.ps1` without executing it, checks tracked/staged whitespace, and requires a clean repository state. It neither starts `app.py` nor invokes hardware tools, monitor enumeration, the Nuitka build, publishing, or deployment. `tests/test_ci_workflow.py` locks down that hardware-free contract.

Do not use application launch as a routine smoke test. It reads and writes user settings, starts a global hook, creates native tray state, and contacts physical monitor hardware. `build_exe.ps1` also writes ignored artifacts and may download tooling.

An authorized manual Windows/hardware pass is required for changes to discovery, selection, DDC I/O, key interception, Change speed, autostart, tray lifecycle, theme/chrome, overlay, or shutdown. Tests of settings code must patch `SETTINGS_PATH` to a temporary location; autostart tests must mock the registry. Pure DDC wrapper tests should use fake context-manager monitor objects.

## Things to preserve

- Keep `app.py` as the single supported composition root and `main.py` as an explicit unsupported stub unless compatibility policy changes.
- Acquire and retain `SingleInstanceGuard` before creating Tk; duplicate launches must remain side-effect-free apart from the best-effort restore broadcast.
- Keep all Tk access on the main thread; use `_result_queue`, `_hotkey_delta_queue`, and `_post_to_ui()` at cross-thread boundaries.
- Keep DDC work off Tk and serialize/coalesce writes. Do not start one hardware worker per key event.
- Keep monitorcontrol operations inside the monitor context manager and clamp all public volume results/targets to `0`–`100`.
- Preserve system key pass-through until a selected monitor has a successful volume read, and clear/pass through safely on loss of readiness.
- Keep native ctypes callbacks strongly referenced and stop display/hook/tray loops before destroying Tk.
- Keep tray state immutable and lock-protected, and keep the menu-open snapshot paired with its command IDs. Tray actions must enter Tk through `_post_to_ui()` and monitor switching must revalidate the captured stable identity.
- Do not use the displayed index or description ordinal as current persistent identity. Preserve version-2 matching and backward-compatible legacy loading.
- Never touch live per-user settings or diagnostics in automated work; use temporary paths.
- Never touch the live Run value in automated work. Preserve current-user-only opt-in writes, Windows quoting, the command-length check, source `pythonw.exe` preference, and original one-file executable path.
- Treat physical monitor volume and global keyboard handling as safety-sensitive side effects.
- Keep `[tool.setuptools].py-modules` synchronized when distributable runtime modules are added, renamed, or removed.
- Keep `windows-ddc.ico`, `theme.APP_ICON_PATH`, and both Nuitka icon flags synchronized.
- Do not treat generated egg-info, `dist\`, or `__pycache__\` as authoritative source.
- Do not document APIs, services, authentication, databases, health probes, hotplug polling, machine-wide startup, signing, or deployment automation unless they are actually implemented.
