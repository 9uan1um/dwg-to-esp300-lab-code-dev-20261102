# ESP300 Connection and Reconnection Guide

[한국어 설명서](esp300-wsl-connection.ko.md)

**Optional fallback:** a working Windows COM connection needs no WSL bridge.
Start with the [portable/Windows quick start](quick-start.ko.md). Hardware
verification below describes the historical lab PC, not every target PC.

This guide connects the DWG to ESP300 web app to the ESP300 on the current lab
PC. It uses the same USB-to-RS232 cable through WSL's Linux driver while keeping
the installed Windows Prolific driver.

**Installation on this PC is complete.** For routine use, including after a PC
restart with the USB cable unplugged, follow the seven steps below. Do not run
the installation scripts every time.

On October 27, 2026, both the web app and the command-line probe received
`ESP300 Version 3.09`. The stage IDs and positions were also read. These
connection checks did not enable or move the motors.

## Seven steps after a PC restart, starting with USB unplugged

These steps assume WSL, usbipd-win and the application are already installed.
For a different PC, complete the initial setup section first and adjust the
project and Python paths to that PC.

Enter the commands in **Command Prompt (CMD)**. Routine startup uses
`esp300-bridge.cmd` and `dwg-esp300-launch.cmd`. They call the tested PowerShell
scripts internally; you do not need to open a PowerShell window. Their execution
policy override applies only to the child process, not the machine-wide policy.

### 1. Turn on the PC and sign in to Windows

After a restart, do not assume the previous WSL instance, bridge or web server
is still running. You do not need to remember a Windows COM number.

### 2. Turn on the ESP300 and reconnect the unplugged USB cable

Confirm that the ESP300 LCD shows the three axis positions. The RS232 end must
be connected to the ESP300 and the USB end to the PC. **The USB cable must be
plugged in before the bridge and controller connection can be completed.**

This step concerns the PC-side USB connection. Keep the stage-to-controller
motor cables connected during this procedure.

### 3. Prepare WSL in a normal CMD window

Search for `cmd` in the Start menu, open **Command Prompt**, and run:

```bat
cd /d "C:\path\to\FLW-ESP300"
wsl.exe -d FLW-ESP300 -u flw -- echo WSL-ready
```

**Expected:** `WSL-ready`, followed by the `C:\...>` prompt. You do not need to
keep a separate Ubuntu terminal open. The bridge script also starts WSL again
if necessary.

If WSL reports that the distribution does not exist, initial setup is incomplete.
Check the installation section instead of repeatedly trying the bridge command.

### 4. Attach USB to WSL and start the bridge in the same window

```bat
esp300-bridge.cmd
```

The launcher automatically finds the current BUSID of the `067b:2303` adapter.
You do not need to type an old BUSID such as `2-4`, or a Windows name such as
COM9. If the current USB port needs sharing registration, Windows requests
administrator approval. Approve it to continue.

**If USB is missing:** the launcher reports
`No 067b:2303 USB adapter is plugged in` and stops. Plug the PC-side USB cable
in, then run the command again.

Normal progress includes `Selected adapter`, `[1/4]` through `[4/4]`, then:

```text
ESP300 BRIDGE RUNNING IN THIS WINDOW. Keep it open. Press Ctrl+C to stop.
... Listening on 127.0.0.1:22170 -> /dev/ttyUSB0 (one client at a time)
```

**This CMD window directly runs the bridge. Leave it open and use a second
CMD window for step 5.** It does not return to the prompt during normal
operation. The device number in `/dev/ttyUSB0` may differ.

To stop only the bridge, press **Ctrl+C in this window**. If CMD asks
`Terminate batch job (Y/N)?`, enter **Y**.

If a bridge is already running, startup reports an error instead of silently
reusing a process that this window cannot stop. Stop the existing bridge in its
own window, or run the following in another CMD at the project directory before
starting again:

```bat
esp300-stop.cmd
```

After unplugging USB, finish use of the old bridge and app, then repeat this
step. Do not skip it solely because USB is marked Shared or Attached.
RUNNING/Listening confirms bridge readiness; verify the ESP300 reply in step 7.

Only when more than one matching adapter is present, inspect the list and
specify the intended current BUSID:

```bat
"C:\Program Files\usbipd-win\usbipd.exe" list
REM Example only: replace 2-4 with the current BUSID shown for 067b:2303.
esp300-bridge.cmd -BusId 2-4
```

### 5. Start the web app in a second normal CMD window

Leave the bridge window open and open a **second Command Prompt**. Run:

```bat
cd /d "C:\path\to\FLW-ESP300"
dwg-esp300-launch.cmd
```

When the web server is ready, this appears:

```text
ESP300 WEB SERVER RUNNING: http://127.0.0.1:8768
Keep this window open. Press Ctrl+C to stop the web server.
```

**The web server runs directly in this second CMD window.** The browser opens
<http://127.0.0.1:8768> automatically. Keep this window open during use; normal
operation does not return to the prompt. Refresh an existing browser tab after
updating the program.

To stop only the web server, press **Ctrl+C in its CMD window** and enter **Y**
if asked `Terminate batch job (Y/N)?`. Closing the browser tab does not stop
the server. Startup rejects another server already on 8768; stop the existing
one first, or use `esp300-stop.cmd`.

If startup reports a Python environment error, resolve it before trying Connect.
The batch launcher pauses on failure so the error remains visible. The launcher
uses the application's bundled `runtime\python.exe`; no Conda activation is required.

### 6. Connect the web app to the real ESP300

In **Jog → Manual jog (ESP300)** on the right:

1. Click **Use WSL**.
2. Confirm `rfc2217://127.0.0.1:22170` and Baud `19200`.
3. **Uncheck Dry run (no hardware).**
4. Click **Connect**.

The camera panel's Connect button controls a separate device.

**Expected:**

```text
Connected: rfc2217://127.0.0.1:22170 @ 19200
Controller axes: X=1, Y=2, Z=3
```

Live Connect **enables the three motors** and reads their positions. It does
not automatically home the stages or run a drawing. Jog, Home, Go and Run on
machine are not needed to establish the connection.

`Connected (dry run, ...)` means simulation; it does not confirm a live
controller connection.

### 7. Test actual communication while keeping the connection open

With the live `Connected` status from step 6, click
**Test hardware link (no motion)**.

**Expected:**

```text
Version reply: ESP300 Version 3.09. Test complete; live connection kept open.
```

The status above it must remain `Connected: ... @ 19200`. The test reuses the
existing connection and sends only the `VE` version query. It does not reopen
or close the connection or send additional motor, homing or movement commands.
Testing is blocked while a job is running, so complete this check before
starting a job.

**Success requires both the live Connected status and the controller version
reply.** `WSL-ready`, `Listening` and `Ready` alone do not confirm an ESP300 reply.

You may also test before connecting. That uses a temporary connection, leaves
the app disconnected and reports `temporary test connection released`. Distinguish
that result from `live connection kept open` in the step 6 → 7 sequence.

### Verification limits

CMD launchers, the internal PowerShell 5.1/7 scripts, automatic BUSID discovery,
the actual `ESP300 Version 3.09` reply were verified. Foreground CMD startup,
Ctrl+C shutdown and stopping both servers with the stop launcher were also
verified. Fourteen communication/server tests and five adapter-selection cases passed. The
post-Connect behavior was tested with a simulated device, and two VE queries on
the same open real serial connection confirmed that the connection stayed open.
No real motor enable or movement command was sent during these checks.

An uninterrupted run from actual PC power-off and physical USB disconnection
through step 7, and actual motion performance, remain separate verification.

## Axis mapping and button behavior

The controller reported these models, and the user confirmed their logical names:

| Web-app axis | Controller channel | Stage model |
|---|---|---|
| X | Axis 1 | M-ILS150PP |
| Y | Axis 2 | UTS100PP |
| Z | Axis 3 | GTS150 |

The mapping is **X=1, Y=2, Z=3**. Do not infer logical Z from physical vertical
orientation. Manual jog, web-app plan execution and newly exported scripts share
the mapping in `esp300_connection.py`.

| Control | Behavior |
|---|---|
| Use WSL | Fills the WSL address; does not open a connection |
| Test hardware link (no motion) | Reads the version; keeps an idle live connection open, or closes its own temporary test connection |
| Connect with Dry run checked | Starts simulation without hardware |
| Connect with Dry run unchecked | Opens communication, enables three motors and reads positions |
| Disconnect | Sends motor-disable commands and closes communication |
| Home (0, 0, 0) | Moves to local coordinate 0,0,0; this is not a machine homing search |
| Center (sensors) | Searches the factory central references sequentially on X, Y, Z; see [central sensor home](central-sensor-home.md) |
| Set local home (here = 0) | Assigns the drawing-center coordinates to the current position and stores a reference, without moving |
| Go to local home | Physically moves to the saved reference |

Although the Set local home button says `here = 0`, the current implementation
assigns the **drawing-center X/Y and focus Z shown in its confirmation dialog**.
Defaults are X=12.5, Y=12.5, Z=0. Home (0,0,0) and Go to local home can therefore
have different destinations. Read the coordinates in the confirmation dialog.

Disconnect also disables the motors; consider loads that depend on motor holding
force before using it.

The bridge serves one client at a time. Do not run a separate serial program or
command-line probe while the web app is live-connected. The app's own test button
can reuse its live connection while no job is running.

## Finish use or unplug USB

Stop any job and confirm physical movement has ended first. **Shutting down
servers is not a machine emergency stop.** The app's Disconnect button sends
motor-disable commands; distinguish that from closing an application server.

- Stop only the bridge: **Ctrl+C in the first CMD window**.
- Stop only the web server: **Ctrl+C in the second CMD window**.
- Enter **Y** if CMD asks `Terminate batch job (Y/N)?`.
- Stop all ESP300 application servers from another CMD at the project directory:

```bat
esp300-stop.cmd
```

The stop tool closes the ESP300 web server (8768), an ESP300 preview server if
present (18768), and this repository's WSL bridge (22170). It sends no motor
on/off commands. Finish or stop a running job first.

After stopping the servers, return USB to Windows using a normal CMD window:

```bat
set /p "ESP300_BUSID=Current BUSID of the 067b:2303 device: "
"C:\Program Files\usbipd-win\usbipd.exe" detach --busid %ESP300_BUSID%
```

Detaching returns the adapter to Windows but does not resolve the original
Windows driver's port-open problem. Use the WSL connection again next time.

To remove persistent sharing registration, use an **administrator CMD window**:

```bat
set /p "ESP300_BUSID=Current BUSID of the 067b:2303 device: "
"C:\Program Files\usbipd-win\usbipd.exe" unbind --busid %ESP300_BUSID%
```

Unbinding is not required after each use. After a PC restart or USB replug,
run the routine bridge command again so the current USB device is attached.

## Troubleshooting

| Symptom or message | Check or action |
|---|---|
| No `067b:2303` device in the list | Reconnect PC-side USB and check `usbipd list` |
| `No 067b:2303 USB adapter is plugged in` | Plug in USB and repeat step 4 |
| `not the expected 067b:2303 serial adapter` | Check the VID:PID and current BUSID; do not select the camera or Bluetooth device |
| Administrator approval was cancelled | Repeat step 4 and approve sharing registration for the intended adapter |
| `NameError: name 'Expected' is not defined`, `found:: command not found`, or `null-valued expression` | Old PowerShell 5.1 quoting bug. Use the updated launcher and `tools/esp300_bridge_runtime.py` together |
| `Ready. Reusing...` then the prompt returns | Old launcher version. Stop old servers and use the updated CMD files, which run in their owner windows |
| `A bridge/listener is already running` or `A server already uses port` | Use Ctrl+C in the owner window or esp300-stop.cmd before starting again |
| `Could not uniquely locate the Linux serial device` | Check USB attachment and the Linux port list below; multiple matching adapters must be distinguished |
| `Permission denied` | Check the `flw` user's dialout membership and udev rule; the Linux setup script can restore them |
| `Address already in use` or a different/stale bridge is reported | Identify the existing listener; run only one compatible bridge on port 22170 |
| `WinError 10061` / connection refused | Check the bridge's Listening or Ready output, the WSL address and port 22170 |
| `No complete VE reply` | Confirm ESP300 power and LCD coordinates first, then RS232 wiring and baud rate |
| A pre-Connect test succeeds but status stays Disconnected | Expected temporary-test behavior; continue with steps 6 and 7 |
| A post-Connect test closes the connection | Confirm the server was restarted after installing the updated code |
| `Stop the current job before testing` | Wait until the job and physical movement have stopped before testing |
| Only `Connected (dry run, ...)` appears | Uncheck Dry run and Connect for a live session |
| `Axis ... position read failed` | Record the error and inspect logs; do not run a fabrication job to test communication |
| Windows still shows `PL2303HXA PHASED OUT...` | This is the existing Windows driver description. Verify Linux device creation and a real VE reply |

List Linux serial devices without moving the stages:

```bat
wsl.exe -d FLW-ESP300 -u flw -- python3 -m serial.tools.list_ports -v
```

Find `USB VID:PID=067B:2303`. The device was `/dev/ttyUSB0` during setup; its number
may change. The launcher discovers the current device automatically.

To query the version from CMD instead of the web app, first ensure the app has
no live connection, then run from the project directory:

```bat
runtime\python.exe esp300_connection.py
```

A successful result contains `"versionReply": "ESP300 Version 3.09"`. This sends
only the version query and exits.

Logs from the bridge and web server started in the background during setup are
under `research\verification\esp300-virtualization`. A bridge started
manually using this guide reports errors in its CMD window.

## Connection architecture and port names

```text
Windows DWG to ESP300 web app
    -> rfc2217://127.0.0.1:22170
WSL serial bridge
    -> /dev/ttyUSB0 or another discovered device
Linux pl2303 driver
    -> USB-to-RS232 adapter and RS232 cable
ESP300 controller
```

| Name | Meaning | Use here |
|---|---|---|
| COM5, COM8, COM9 | Windows serial-device names | The old Windows route, not the WSL address |
| BUSID | USB/IP's identifier for a PC USB device | Sharing, attaching, detaching and adapter selection |
| `/dev/ttyUSB0` | Linux serial-device name | Linux bridge access to the adapter |
| `127.0.0.1:22170` | Local bridge endpoint | Web-app Port / WSL address field |
| `127.0.0.1:8768` | Local web-server endpoint | Browser address bar |
| ASCII | Command/response character encoding | ESP300 serial messages |

A COM number and character encoding are separate settings. Changing the COM
number does not add chipset support to the installed Windows driver.

Here USB is passed to WSL and handled by Linux's `pl2303` driver. The Windows
Prolific driver was not downgraded. While attached to WSL, the same USB adapter
is unavailable to Windows serial programs.

| Setting | Verified value |
|---|---|
| Baud rate | 19200 |
| Data bits / parity / stop bits | 8 / none / 1 (8N1) |
| Hardware flow control | RTS/CTS |
| Web-app serial address | `rfc2217://127.0.0.1:22170` |

Camera capture and CAD conversion continue running on Windows. Linux handles
the adapter communication. The RFC2217 bridge listens only on localhost; it is
not configured for access from other PCs. RFC2217 has no authentication or
encryption, so do not expose this listener to a LAN or the Internet.

## Initial installation or Linux permission recovery

**Skip this section for routine use on the current PC.** On another PC, adjust
the project directory and the Python 3.12 environment path.

For initial Windows preparation, run in an **administrator CMD window**:

```bat
cd /d "C:\path\to\FLW-ESP300"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\setup_esp300_virtualization.ps1
```

The script enables Virtual Machine Platform and installs WSL and usbipd-win.
It does not downgrade the existing Prolific driver or restart automatically.
If a restart is required, save your work and restart Windows.

After restarting, run in a normal CMD window. USB may remain unplugged for this
installation step:

```bat
cd /d "C:\path\to\FLW-ESP300"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\setup_esp300_linux.ps1
```

This prepares the dedicated Ubuntu distribution `FLW-ESP300`, the `flw` user,
dialout membership, pySerial and udev rules. The Linux setup script can also
restore the required permissions and rules.

usbipd-win adds a USB forwarding service, driver and firewall rule. The existing
Prolific driver remains installed, but this setup does make additive Windows
system changes. Setup logs and restart information are under
`../outputs/esp300-virtualization/`.

## Verification record and file locations

These values were verified during setup on **October 27, 2026**. Different version
numbers alone do not establish a fault.

| Item | Result |
|---|---|
| Controller reply | `ESP300 Version 3.09` |
| Windows Prolific driver | 3.9.6.0, `oem188.inf` |
| WSL / usbipd-win | 2.7.14.0 / 5.3.0 |
| Distribution | Ubuntu 24.04, WSL name `FLW-ESP300` |
| Linux kernel | `6.18.33.2-microsoft-standard-WSL2` |
| Linux Python / pySerial | 3.12.3 / 3.5 |
| Hardware checks | Version, three stage IDs and positions read successfully |
| Software checks | Communication tests, adapter-selection checks and Windows-to-WSL loopback passed; see verification limits above |
| Physical movement / fabrication | Not performed as part of these connection checks |

USB/IP adds communication latency. Verify actual axis directions and movement
with a small supervised test before fabrication; existing timing assumptions
need their own validation. Do not relax position limits to hide a communication
failure.

| File | Purpose |
|---|---|
| [`dwg-esp300-launch.cmd`](../dwg-esp300-launch.cmd) | Start the web app from CMD |
| [`esp300-bridge.cmd`](../esp300-bridge.cmd) | Run the bridge in the first CMD; Ctrl+C stops it |
| [`esp300-stop.cmd`](../esp300-stop.cmd) | Stop all ESP300 application servers |
| [`launch_dwg_to_esp300.ps1`](../launch_dwg_to_esp300.ps1) | Web-app startup code called by the batch launcher |
| [`tools/start_esp300_bridge.ps1`](../tools/start_esp300_bridge.ps1) | USB sharing, attachment and bridge startup |
| [`esp300_connection.py`](../esp300_connection.py) | Serial settings, shared axis mapping and version probe |
| [`tools/esp300_serial_bridge.py`](../tools/esp300_serial_bridge.py) | Linux RFC2217 bridge |
| [`tools/esp300_bridge_runtime.py`](../tools/esp300_bridge_runtime.py) | Linux device and existing-bridge discovery |
| [`tools/setup_esp300_virtualization.ps1`](../tools/setup_esp300_virtualization.ps1) | Initial Windows setup |
| [`tools/setup_esp300_linux.ps1`](../tools/setup_esp300_linux.ps1) | Linux setup and permissions |

Newly exported controller scripts support the WSL address. Previously exported
files are not rewritten automatically; check their serial connection code or
export them again. The source export accepts `--port rfc2217://127.0.0.1:22170`.

Run the hardware-free communication suite with the project's Windows Python:

```bat
runtime\python.exe -m unittest test_esp300_bridge -v
runtime\python.exe tools\test_wsl_transport.py
```

The second command uses a single-use Linux loopback server on a temporary port;
it does not open a USB device or leave a mock on production port 22170.

References: [Microsoft WSL USB guide](https://learn.microsoft.com/windows/wsl/connect-usb),
[pySerial RFC2217](https://pyserial.readthedocs.io/en/latest/url_handlers.html#rfc2217),
[ESP300 manual](https://www.newport.com/medias/sys_master/images/images/h2f/haa/8797091299358/ESP300-User-Manual.pdf).
