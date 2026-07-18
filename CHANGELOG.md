# Changelog

All notable changes to this project are documented in this file. The reconstruction audit covered the complete reachable repository history through `0b4f263`, all local and remote-tracking branches, and the live origin heads and tags before the documentation changes listed under Unreleased.

That audited history contains one parentless commit. The audit clone had no local tag ref, but origin advertised a lightweight `0.1.0` tag at the same commit as the then-current `master` and `origin/master`. Because a lightweight tag has no independent tagger timestamp, the version date below uses the tagged commit's committer date; the GitHub release was published shortly afterward on the same calendar date. There is no earlier release boundary or separate untagged development period to reconstruct.

## [Unreleased]

### Added

- Added release-history, architecture, and repository-agent documentation.
- Added hardware-free unit coverage for hook liveness, readiness loss, write failures, shutdown, and paired volume-key events.

### Changed

- Expanded user and operator documentation without changing runtime behavior.
- Made global Volume Down/Up interception require a live native hook and release subsequent presses after an uncertain DDC write result until Refresh succeeds.
- Kept the consume/pass-through decision stable from the first key-down through the matching key-up.

## [0.1.0] - 2026-03-22

### Added

- DDC/CI monitor discovery and a refreshable selector, including ordinal disambiguation for monitors that report the same description.
- Audio-volume reads and clamped `0`–`100` writes with immediate hardware readback.
- A fixed-size Tkinter control window with a volume slider, percentage display, status bar, and one-point decrement/increment controls.
- Global Windows Volume Down and Volume Up interception that redirects ready-state key presses to the selected monitor while passing keys through before readiness.
- A topmost, translucent on-screen volume overlay that automatically hides after 1.4 seconds.
- Tray-first operation with startup minimization, double-click/menu restore, minimize-to-tray behavior, and an Exit action.
- Per-user selected-monitor persistence in `%APPDATA%\windows-ddc\settings.json`, with a home-directory fallback and temporary-file replacement.
- Windows light/dark application-theme detection, dark DWM title-bar support, and a shared application/tray icon.
- Background DDC/CI reads and serialized, coalesced rapid volume writes so blocking hardware access does not run on Tk's UI thread.
- Native Win32 tray and low-level keyboard-hook integration through `ctypes`.
- Python 3.10+ setuptools metadata with pinned `monitorcontrol==4.2.0` runtime and `Nuitka==2.4.8` build dependencies.
- A one-file, console-free Nuitka build for `dist\windows-ddc.exe`, including the Tk plugin and icon as both executable metadata and runtime data.
- The supported `app.py` launcher, an explicit exit-1 rejection stub in `main.py` that directs users to `app.py`, setup/build documentation, and tracked UI screenshots.
- A published `windows-ddc.exe` asset on the GitHub `0.1.0` release.

[Unreleased]: https://github.com/fensoft/windows-ddc/compare/0.1.0...HEAD
[0.1.0]: https://github.com/fensoft/windows-ddc/releases/tag/0.1.0
