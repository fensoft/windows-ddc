# windows-ddc

`windows-ddc` is a Windows desktop application that sends the system Volume Up and Volume Down keys to one DDC/CI-capable monitor. It also provides a small Tkinter control window, a notification-area icon, and an on-screen volume overlay.

It controls the monitor's DDC/CI audio-volume value, not the Windows audio mixer, application volumes, brightness, or mute state.

## Screenshots

### Control window

![Monitor Volume control window](docs/app.png)

### Volume overlay

![On-screen monitor volume overlay](docs/overlay.png)

These manually maintained captures predate the wider serial-bearing monitor selector, Change speed selector, Start with Windows checkbox, and unavailable/error overlay. Update them only from a real application capture on compatible hardware.

## Features

- Discovers DDC/CI monitors and lets the user select one target.
- Reads and writes the selected monitor's volume in the `0`–`100` range.
- Provides a slider and `-`/`+` buttons with a persistent Slow, Medium, or Fast change speed.
- Intercepts the global Windows Volume Down and Volume Up keys only while the native hook is live and a target is ready.
- Shows volume and fail-closed monitor errors in a bottom-centered overlay on the cursor's DPI-scaled screen work area, falling back to the selected screen without taking focus.
- Starts in the Windows notification area only after Windows confirms the icon was added, with live monitor/volume/routing status, Refresh, quick monitor switching, Restore, Exit, and Explorer-restart recovery.
- Remembers the selected physical monitor by EDID manufacturer/product/serial when available, with a Windows device-path fallback.
- Invalidates monitor control on Windows display/device notifications and reacquires fresh DDC handles before every actual write.
- Follows the current user's Windows light/dark application preference at startup.
- Keeps DDC/CI work off Tk's UI thread and coalesces rapid volume changes.
- Fails closed on stalled DDC calls or internal UI callbacks, with bounded native-thread lifecycle waits.
- Allows one instance per Windows session; launching it again restores the existing control window instead of starting competing hooks or DDC workers.
- Keeps a small rotating per-user diagnostic log for the console-free executable.
- Can opt the current user into launching the same source entrypoint or packaged executable at Windows sign-in.

> [!IMPORTANT]
> Once a monitor has been selected and its volume read successfully, Volume Up and Volume Down are consumed globally by this application. They no longer change Windows system volume until the application is exited or loses readiness. The mute key is not intercepted.

## Technology and runtime

| Area | Implementation |
| --- | --- |
| User interface | Python `tkinter` / `ttk` |
| Monitor control | `monitorcontrol==4.2.0` over DDC/CI |
| Windows integration | `ctypes` calls to User32, Kernel32, Shell32, Dxva2, SetupAPI, Advapi32, and optional DWM APIs |
| Source packaging | setuptools with flat `py-modules` |
| Executable build | `Nuitka==2.4.8`, one-file Windows executable |
| Continuous integration | GitHub Actions on `windows-latest`, Python 3.10 and 3.14 |
| Persistent app data | Per-user JSON settings, optional Windows Run value, and rotating diagnostic logs |

The runtime is one interactive user-session process. It is not a Windows service and does not open a port, expose an HTTP API, use a database, or contact a runtime network service. See [Architecture](docs/ARCHITECTURE.md) for the process, thread, and event flows.

## Requirements

- Windows 10 or Windows 11. These are the documented targets; the repository has no automated OS compatibility matrix.
- A monitor with DDC/CI enabled in its on-screen display and support for DDC/CI audio-volume reads and writes.
- For source execution: Python 3.10 or newer with Tkinter available.
- For local executable builds: the optional build dependencies described below.

No administrator workflow is implemented or requested by the application. Run it in the interactive Windows user session whose volume keys and monitor should be controlled.

## Install and first run

### Use the release executable

The [0.1.0 release](https://github.com/fensoft/windows-ddc/releases/tag/0.1.0) contains the prebuilt `windows-ddc.exe` asset. Download the executable, place it in a user-controlled location, and run it. It is a standalone one-file application with no installer. That tagged asset predates Start with Windows; an executable built from the current sources can register itself from the control window.

The working tree's ignored `dist\` directory is not the distribution source and may be empty. The repository also does not define executable signing or publishing automation.

### Run from source

From PowerShell:

```powershell
git clone https://github.com/fensoft/windows-ddc.git
Set-Location windows-ddc
python -m pip install -e .
python app.py
```

`python -m pip install -e .` installs the pinned runtime dependency and creates local packaging metadata. It may contact the configured Python package index.

The supported source launcher is `app.py`. `main.py` is an intentional compatibility stub that prints:

```text
This launcher is no longer supported. Run: python app.py
```

and exits with status `1`. `windows-ddc` itself defines no console entry point or application command-line options.

### First-run workflow

1. Enable DDC/CI in the monitor's on-screen settings before starting the application.
2. Start `windows-ddc.exe` or run `python app.py`.
3. Look in the notification area, including its overflow menu. The control window hides only after Windows confirms that the tray icon was added; otherwise it remains available with an error in the status bar.
4. Double-click the tray icon to restore the window, or right-click it for live status, Refresh, monitor switching, Restore, and Exit.
5. Choose the intended monitor and wait for the status bar to report a successful volume read.
6. Test at a safe listening level with the buttons or slider before relying on the global volume keys.

With no saved selection, the app selects automatically only when exactly one verifiable monitor exists. Multiple monitors require an explicit choice. A saved monitor that is missing or ambiguous is never replaced with the first enumerated monitor. The application enforces one instance per Windows session; a duplicate launch exits before Tk, settings, hooks, tray state, or DDC work and requests that the existing instance restore its window.

## Operation

| Action | Behavior |
| --- | --- |
| Start | Acquires the session-local single-instance guard, creates display-change, tray, and keyboard-hook threads with two-second startup deadlines, waits up to two seconds for confirmed tray-icon addition before hiding, then discovers monitors in the background. A duplicate launch restores the existing window and exits. |
| Restore | Double-click the tray icon or use **Restore**. The tray icon is hidden while the control window is visible. |
| Select a monitor | Choose it in the read-only list. The stable identity is saved only after a successful volume read. |
| Change volume | Choose a Slow (`+1`), Medium (`+2`), or Fast (`+3`) change speed, then use `-`, `+`, release the slider, or press Volume Down/Up. Before each actual write, the app reacquires monitor wrappers and exact-matches the saved identity; writes are followed by a readback. |
| Start with Windows | Select the checkbox to write a current-user Run entry for the present source or executable path. Clear it to remove that entry. No administrator access is required. |
| Tray menu | Right-click the icon to see the active monitor, last confirmed volume, and whether global volume-key routing is enabled. Use **Refresh**, choose a verified monitor for exact-match revalidation, or use **Restore**/**Exit**. |
| Overlay | Volume and unavailable notices appear on the screen containing the cursor. If the cursor screen cannot be resolved, the selected monitor's display is used; taskbars, negative screen coordinates, and Windows display scaling are accounted for without activating the overlay. |
| Refresh | Re-enumerates monitors and reads the exact saved selection again. It never falls back to a different monitor. |
| Minimize | Sends the control window to the notification area only after confirmed icon addition; failure restores the normal window. |
| Close the restored window | Exits the application; it does not merely hide the window. |
| Exit from the tray | Removes the hook and tray icon, closes the overlay, and exits. |

Monitor discovery is event-driven rather than periodic. Windows display and monitor-device notifications immediately suspend control and schedule a debounced refresh with bounded retries. The displayed volume is not polled for changes made by another program or the monitor's OSD.

The tray menu is built from a thread-safe immutable snapshot supplied by Tk. A monitor click retains the stable selection identity represented when that menu opened, even if discovery updates concurrently, and all actions are queued back to Tk. Switching is refused while another monitor operation is active; Refresh retains the existing deferred-refresh behavior. The menu's volume is the last confirmed read/readback, not an optimistic pending slider target.

Overlay placement samples the cursor and Windows monitor bounds, work area, and scale factor each time the overlay appears, so cursor movement, a moved taskbar, or a changed display layout is reflected immediately. The cursor's screen is preferred, followed by the selected monitor's Windows display name and then the primary screen. This does not perform another DDC lookup. The window carries `WS_EX_NOACTIVATE` and is shown with `SWP_NOACTIVATE`; if that protection cannot be applied, the overlay remains hidden rather than risking a focus change.

Change speed defaults to Slow (`+1`) when no valid preference is saved. Medium changes by `2` and Fast changes by `3`. The selected speed applies to both the on-screen `-`/`+` buttons and the global Volume Down/Up keys, updates the live hook immediately, and is saved in `settings.json`.

A DDC write and its readback are not transactional. If the write succeeds but readback fails, or if the display changes during an in-flight call, the monitor may already have changed. The application reports that uncertainty in the overlay and status bar, replaces the displayed value with `--`, releases global key interception, and performs read-only rediscovery without retrying the write. Volume changes are not rolled back when the application exits.

Every discovery/read or write/readback worker has a 10-second UI watchdog. A timeout marks the volume unknown and releases global key interception, but the app keeps that worker's serialization slot because the underlying native DDC call cannot be cancelled safely. Its eventual result is ignored and followed by read-only rediscovery. If it never returns, restart the application; no concurrent DDC operation is started against the monitor meanwhile.

The UI range is `0`–`100`, but a monitor can report a lower device maximum and reject a higher target. That dependency error is shown in the status bar.

## Startup validation and status

There is no separate health command, readiness endpoint, or console in the packaged executable. The control window's status bar is the immediate health surface, and a rotating per-user log retains lifecycle and failure diagnostics across runs.

| Status shape | Meaning |
| --- | --- |
| `Searching for monitors...` | DDC/CI enumeration and the initial read are running. |
| `Ready. N monitor(s) detected...` | A selected monitor volume was read; controls and global key interception are enabled. |
| `No DDC/CI monitors found.` | Enumeration returned no monitor wrappers. |
| `Display configuration changed...` | Control was disabled immediately and automatic revalidation is pending. |
| `Selected monitor ... ambiguous/not found` | No substitute target was chosen; select the monitor again or reconnect it. |
| `Display-change listener failed: ...` | All monitor-volume writes are disabled because reset protection is unavailable. |
| `Tray icon failed: ...` | Tray initialization, addition, or recovery failed; the main window remains visible or is restored. |
| `... timed out. Monitor state is unknown...` | A native DDC call exceeded 10 seconds. Control stays disabled until it returns and automatic Refresh succeeds; restart if it remains stuck. |
| `Internal UI callback failed: ...` | One queued UI operation failed. Queue polling continues, but monitor control remains disabled until Refresh succeeds. |
| A read/write/detection error | The underlying operation failed; the status contains the formatted exception text. |
| `Volume-key listener failed: ...` | The global hook failed. The GUI may still control the monitor. |
| `Could not enable/disable Start with Windows: ...` | The current-user Run entry could not be updated; the checkbox returns to its previous state. |

Volume controls remain disabled until the display-change listener is live and the exact selected monitor has a readable volume. Global key interception additionally requires the keyboard listener to be installed and live. During an unavailable period, physical Volume Down/Up presses pass through to Windows and the app shows one error overlay per period. If the keyboard hook fails, the GUI can continue controlling the monitor; if display-change protection fails, all writes remain disabled.

## Configuration and persistent data

There are no application-specific environment variables, CLI flags, environment templates, or administrative settings. Standard Windows `APPDATA` and `LOCALAPPDATA` locations determine where the settings and diagnostic files are stored. Start with Windows is a separate opt-in current-user registry value.

| Input or field | Default | Effect |
| --- | --- | --- |
| `APPDATA` | If unset or empty, `Path.home()` | Base directory for the `windows-ddc` settings folder. |
| `LOCALAPPDATA` | Falls back to `APPDATA`, then `Path.home()` | Base directory for the rotating diagnostic log. |
| `schema_version` | `2` for newly written settings | Selects the stable-identity settings schema. |
| `change_speed` | `slow` | Persistent `slow` (`+1`), `medium` (`+2`), or `fast` (`+3`) volume-change preference. |
| `selected_monitor.description` | No saved value | Human-readable description; used for safe migration of unique legacy selections. |
| `selected_monitor.identity.device_path` | No saved value | Case-insensitive Windows monitor interface path and fallback identity. |
| Optional EDID identity fields | Omitted when unavailable | Manufacturer ID, product code, and normalized serial used as the preferred identity. |
| `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\windows-ddc` | Absent | When present, launches windows-ddc for the current user at sign-in. |

The normal settings path is:

```text
%APPDATA%\windows-ddc\settings.json
```

If `APPDATA` is unavailable, the fallback is:

```text
<home>\windows-ddc\settings.json
```

The exact schema is:

```json
{
  "schema_version": 2,
  "change_speed": "medium",
  "selected_monitor": {
    "description": "Monitor description",
    "identity": {
      "device_path": "Windows monitor interface path",
      "manufacturer_id": "DEL",
      "product_code": 4660,
      "serial_number": "EXAMPLE-SERIAL"
    }
  }
}
```

Writes go to sibling `settings.tmp` first and then replace `settings.json`. There is no file lock; the session-local process mutex prevents normal project instances in the same Windows session from racing, but does not coordinate external tools or separate Windows sessions. A unique EDID manufacturer/product/serial match may follow a monitor to another port; duplicate or unavailable serials require the saved Windows device path. Device paths commonly change when a monitor moves between GPU ports, in which case manual selection is required. Some monitors provide missing, placeholder, or duplicate serial data.

Legacy description/ordinal files remain readable. A legacy selection is promoted to version 2 only when its description identifies exactly one verifiable current monitor; duplicate legacy descriptions fail closed and require manual selection.

Missing, unreadable, syntactically invalid, non-object, unknown-version, or invalid nested monitor settings are treated as no selection. JSON booleans are not accepted as legacy ordinals. A missing or invalid `change_speed` independently defaults to `slow`.

The settings file contains monitor selection and change-speed preference, not volume, credentials, or secrets. The actual volume is monitor hardware state and is read again at startup.

### Start with Windows

The checkbox uses the standard `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run` key, so it affects only the current user and needs no elevation. Windows invokes Run entries at sign-in, although it can delay their start. Clearing the checkbox deletes only the `windows-ddc` value. See [Microsoft's Run/RunOnce documentation](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys).

For the one-file build, the registered command is the original executable path; [Nuitka explicitly preserves that path in `sys.argv[0]`](https://nuitka.net/user-documentation/common-issue-solutions.html#onefile-finding-files) rather than exposing the temporary extraction path. For source execution, the command uses `pythonw.exe` when it is available beside `python.exe`, followed by the absolute `app.py` path. Paths are Windows-quoted, and commands beyond Windows' documented 260-character Run-entry limit are rejected without changing the registry. Moving or deleting a registered source tree or executable can leave a stale command; clear the checkbox before moving it, then enable it again from the new location.

### Diagnostic log

The normal log path is `%LOCALAPPDATA%\windows-ddc\windows-ddc.log`. If `LOCALAPPDATA` is unavailable, it falls back to `APPDATA` and then the current user's home directory. The current file is capped at 512 KiB and keeps two rotated backups named `windows-ddc.log.1` and `windows-ddc.log.2`.

Routine entries contain timestamps, severity, thread/component names, lifecycle events, subsystem failures, and exception classes. They do not deliberately include monitor descriptions or device paths. An unexpected top-level exception can include a traceback or local source paths, so inspect logs before sharing them. If the log directory or file cannot be created, logging is silently disabled and the application continues; the status bar remains available.

## Backup and restore

There is no built-in backup format. Exit the application first, then copy the JSON file. For the normal Windows path:

```powershell
$backupPath = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'windows-ddc-settings.json.backup'
Copy-Item -LiteralPath "$env:APPDATA\windows-ddc\settings.json" -Destination $backupPath
```

To restore, exit every application instance, verify the backup contains the schema above, then run:

```powershell
$backupPath = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'windows-ddc-settings.json.backup'
New-Item -ItemType Directory -Force -Path "$env:APPDATA\windows-ddc" | Out-Null
Copy-Item -LiteralPath $backupPath -Destination "$env:APPDATA\windows-ddc\settings.json" -Force
```

Choose another user-controlled backup location outside the checkout if Documents is unsuitable, and never commit the backup. If `APPDATA` is unset, substitute the fallback path documented above. Moving `settings.json` aside resets monitor selection and Change speed to its Slow default on the next launch; it does not reset monitor volume or remove the separate Start with Windows registry value.

## Interfaces and security boundaries

- `windows-ddc` has no supported application CLI, subcommands, or flags beyond launching `app.py` or the executable.
- Installing the dependency also installs the upstream `monitorcontrol` console command. It is not a `windows-ddc` interface and can directly change monitor volume, brightness, power, mute, or input; do not use it unless that hardware operation is intentional.
- There are no HTTP routes, ports, realtime sockets, external runtime services, accounts, authentication, or authorization roles.
- The process loads native Windows libraries and installs a desktop-wide low-level keyboard hook. Unrelated keys are passed onward; Volume Down and Volume Up are swallowed only when the hook is live and the application's readiness flag is active. Each physical press keeps its initial consume/pass-through decision through the matching release.
- DDC/CI writes cross the process boundary into physical monitor hardware and may have an audible effect.
- The application reads the current user's Windows theme preference. It writes only its named current-user Run value, and only when the user toggles Start with Windows.
- Runtime settings contain no secrets. Do not add credentials or tokens to the tracked repository or the settings schema without an explicit security design.

## Build the executable

Install the runtime and pinned build tooling:

```powershell
python -m pip install -e .[build]
```

Then run the repository build script:

```powershell
.\build_exe.ps1
```

Expected output:

```text
dist\windows-ddc.exe
```

The script resolves the `python` command, changes to the repository root, verifies `app.py` and `windows-ddc.ico`, and executes this Nuitka command shape:

```powershell
python -m nuitka --onefile --windows-console-mode=disable --enable-plugins=tk-inter --windows-icon-from-ico=windows-ddc.ico --include-data-files=windows-ddc.ico=windows-ddc.ico --output-dir=dist --output-filename=windows-ddc.exe --remove-output --assume-yes-for-downloads app.py
```

The icon is both the executable icon and runtime data because `theme.py` loads a sibling `windows-ddc.ico`. The build can download Nuitka support/toolchain components, writes the named artifact under `dist\`, may overwrite an existing artifact, and removes its intermediate build directory. `dist\` is ignored. CI validates source without executing this build; no installer, signing step, CI artifact build, or release-publishing workflow is defined.

## Development and testing

Install the editable runtime environment before developing:

```powershell
python -m pip install -e .
```

The repository has a standard-library unit-test suite for hotkey safety, stable identity, isolated selection/change-speed settings, autostart command/registry behavior, diagnostics rotation, topology generations, fresh-handle revalidation, single-instance behavior, resilience, rich tray-menu snapshots/commands, multi-screen overlay placement/no-activate behavior, CI safety, and tray recovery. It has no lint/type/format configuration. `.github/workflows/ci.yml` runs the following checks on `windows-latest` with Python 3.10 and 3.14 for pushes, pull requests, and manual dispatches. The workflow never launches the UI, executes the Nuitka build, installs native listeners, changes the live Run key, or contacts monitor hardware:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q app.py autostart.py ddc.py diagnostics.py gui.py main.py overlay.py settings.py theme.py windows_platform.py
python -m pip check
git diff --check
git diff --cached --check
git status --short
```

Parse the PowerShell build script without executing it:

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

CI installs only the runtime project with `python -m pip install -e .`; it does not install the optional Nuitka build extra or publish artifacts. A workflow contract test keeps the supported Python boundary, low-risk commands, and prohibited hardware/runtime commands explicit.

Changes to GUI, autostart, tray, hook, display notifications, or DDC behavior still require an authorized manual test on Windows with a compatible monitor. Back up live settings first. At minimum, verify primary startup, duplicate-launch restoration without a second process remaining, Start with Windows enable/disable and restart persistence, unique/no-serial/duplicate identity behavior, Change speed behavior and persistence, driver reset, resolution/orientation change, disconnect/reconnect, exact-match recovery, fresh writes/readback, rapid coalescing, overlay volume/errors on the cursor screen and selected-display fallback at mixed DPI without focus loss, key pass-through while invalid, hook/listener failure, rich tray status/Refresh/monitor switching, confirmed tray-first startup, failed icon-add fallback, minimize/restore, Explorer restart recovery, and clean exit. These tests can change the current-user Run key, physical monitor volume, and user-session keyboard behavior.

For repository-specific maintainer rules, read [AGENTS.md](AGENTS.md).

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| No window appears | Check the notification area and its overflow menu, then double-click the icon or choose **Restore**. Tray-first startup is expected. |
| Launching a second copy does nothing | The second process exits intentionally after asking the existing tray instance to restore. Check the existing window and notification area; restoration is best-effort during very early startup or shutdown. |
| The tray icon cannot be added or disappears | The main window remains visible or is restored automatically. After Explorer restarts, the app re-adds an icon that was visible; if recovery fails, read the restored window's status bar. |
| Tray monitor switching says to wait | A discovery, read, or write is active. Let it finish, reopen the tray menu, and select the monitor again. |
| `No DDC/CI monitors found.` | Enable DDC/CI in the monitor OSD, confirm the monitor exposes DDC/CI over the active connection, then choose **Refresh**. |
| A monitor is listed but volume remains `--` | Enumeration succeeded but its volume read did not. Read the status, try another monitor, and confirm the target supports DDC/CI audio volume. |
| A monitor operation timed out | Wait for automatic Refresh. If the status does not change because the native DDC call never returns, restart the app; it intentionally will not start another hardware call concurrently. |
| `Internal UI callback failed` | Restore the window and choose **Refresh**. Polling continues, but monitor control fails closed until a successful refresh. |
| A failure disappears from the status bar | Review `%LOCALAPPDATA%\windows-ddc\windows-ddc.log` and its two backups. If that directory was unavailable, logging may have been disabled without blocking startup. |
| `Display-change listener failed` | Monitor writes intentionally remain disabled because the app cannot provide reset protection. Restart the app; if it repeats, use Windows system volume instead. |
| `monitorcontrol is not installed...` | From the repository root, rerun `python -m pip install -e .`. |
| Volume keys still change Windows audio | Restore the UI and wait for a successful volume read. If `Volume-key listener failed` appeared, the buttons/slider may work but global keys will not. |
| Volume keys stop changing Windows audio | This is expected while the app is ready. Close the restored window, or use tray **Exit** while minimized, to restore normal system-volume behavior. |
| A volume press occurs during a display change | Notifications release interception immediately. If Windows did not notify before the first press, that press can be consumed while asynchronous validation rejects the monitor write; later presses pass through. |
| The selected monitor is missing or ambiguous | The app will not choose another monitor. Reconnect it or explicitly select the intended target. |
| The displayed value is stale | Choose **Refresh** after changes made by the monitor OSD or another tool. Display topology changes refresh automatically, but external volume is not polled. |
| Selection is not remembered | Ensure the per-user settings directory is writable and only one instance is running. Save failures are retained in the diagnostic log. |
| Change speed is not remembered | Ensure the per-user settings directory is writable and only one instance is running. Invalid values safely fall back to Slow; save failures are logged. |
| Start with Windows cannot be enabled | Read the status/log, confirm the current user can write their Run key, and check that the absolute command is no longer than 260 characters. Move the app to a shorter stable path if needed. |
| Start with Windows points to an old location | Run the app from the old location if available and clear the checkbox, or remove the `windows-ddc` value from the current-user Run key, then enable it from the new location. |
| Selection is lost after moving a no-serial monitor | Its Windows device path changed. Select it again so schema version 2 records the new path. |
| Build fails before compilation | Install `.[build]`, ensure `python` resolves on `PATH`, and keep `app.py` and `windows-ddc.ico` at the repository root. |

## Further documentation

- [Changelog](CHANGELOG.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Coding-agent instructions](AGENTS.md)
