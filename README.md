# windows-ddc

Windows desktop app for controlling a monitor's DDC/CI volume with a tray UI, keyboard volume keys, and an on-screen volume overlay.

Generated with GPT-5.4 using extra high reasoning.

## Screenshots

### App

![App UI](docs/app.png)

### Overlay

![Overlay UI](docs/overlay.png)

## Requirements

- Windows 11 or Windows 10
- Python 3.10 or newer
- DDC/CI enabled in your monitor's OSD

## Setup

Install the runtime dependency:

```powershell
python -m pip install -e .
```

Install runtime plus build tooling:

```powershell
python -m pip install -e .[build]
```

## Run

Launch the app with:

```powershell
python app.py
```

`main.py` is only a redirect stub and is not the supported launcher.

## Build An EXE With Nuitka

From the repo root, run:

```powershell
.\build_exe.ps1
```

This uses the following Nuitka command shape:

```powershell
python -m nuitka --onefile --windows-console-mode=disable --enable-plugins=tk-inter --windows-icon-from-ico=windows-ddc.ico --include-data-files=windows-ddc.ico=windows-ddc.ico --output-dir=dist --output-filename=windows-ddc.exe --remove-output --assume-yes-for-downloads app.py
```

Expected output:

```text
dist\windows-ddc.exe
```

Notes:

- The build is Windows-only.
- The app icon file `windows-ddc.ico` is bundled as data on purpose because the runtime code still loads it from disk.
- Nuitka onefile extracts internally at runtime before launching the app.

## Development Notes

- Runtime dependency: `monitorcontrol==4.2.0`
- Build dependency: `Nuitka==2.4.8`
