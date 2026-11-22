# Install on a new Windows x64 PC

This is a source distribution. It does not include a Windows Python runtime,
a WSL disk image, a USB driver binary, a ready position or equipment calibration.

## Windows application: check with hardware disconnected

1. Clone this repository or extract the source ZIP completely into a new
   folder under your own Windows account. Open PowerShell in that folder.
2. With the controller and camera disconnected, review and explicitly run
   the existing setup script. It installs into this folder's local runtime,
   not into Windows or WSL. It needs network access to Python.org, PyPA and
   the Python package registry and installs the versions in requirements.txt.
   Do not use a sibling checkout as an installation dependency.

       powershell -NoProfile -File .\tools\setup_runtime.ps1
       .\dwg-esp300-launch.cmd -Check

   If your organisation's policy blocks the script, ask the administrator;
   do not change Windows policy for this application. An existing runtime with
   the matching requirements hash does not need to be reinstalled.

   -Check checks dependency imports and compiles selected source files without
   opening/looking up Windows serial ports, camera, WSL, listeners or a stored
   position. A passing check is not a connected-machine or motion test.

## ESP300 configuration is installation-specific

The regular app refuses to initialize without a valid config/z-max-mm.json.
The local operator must verify axis mapping, signs, origin and safe travel
against the controller and installation before commissioning. Only then create
that file containing a single finite JSON number: the approved maximum Z in
the ESP300 machine/HOME coordinate frame, in millimetres (not a local/UI Z).
There is deliberately no example value. Never infer a limit from test values.
Do not copy a Ready position from another installation; it is optional and can
be saved locally after validation. Keep both files local. Connect in Live mode
enables the motors; never use that button just to test installation. Keep the
physical stop procedure and hardware protection in place.

## Optional WSL2 bridge

Native Windows COM is preferable if the appropriate driver works. If it
doesn't, the existing WSL route uses a dedicated Ubuntu 24.04 WSL2 distribution
named FLW-ESP300. An authorized operator reviews the separately documented
Windows feature and usbipd-win setup, then the Linux setup script; it installs
Linux Python/pySerial and module tools, configures the flw user in dialout,
and gives the supported PL2303 (VID:PID 067b:2303) a narrow udev tty rule.
Windows USB sharing may require administrator approval. The launcher finds
the currently attached supported adapter; the BUSID and /dev/ttyUSB index
are not portable constants. Other adapters are not automatically supported.
The bridge accepts one client on 127.0.0.1:22170 with the ESP300 connection
at 19200 baud. Do not expose this port to a network. The bridge itself only
forwards bytes; this is not a motion interlock.

See [ESP300 WSL details](esp300-wsl-connection.md). Package validation must
not configure WSL, bind or attach USB, launch the bridge, open serial or
camera, enable motors or send motion commands.

## Build the source ZIP (maintainers)

Once the local Windows Python runtime is configured, run build-portable.cmd
from a repository checkout. It writes a source ZIP, its SHA-256 and an
internal file manifest under dist/. It never packages installed Python,
third-party Python wheels, WSL or USB state, site calibration, or logs.
