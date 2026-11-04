# Central sensor home

한국어 사용 절차: [중앙 원점 센서를 이용한 스테이지 중앙 정렬](central-sensor-home.ko.md)

`Center (sensors)` finds the factory central origin references. It is beside
`Home (0, 0, 0)`; `Set local home` and `Go to local home` occupy the second row.
The existing Home button still moves to local coordinate zero without searching
for sensors.

| Search order | Logical axis / channel | Expected stage | ESP300 search mode |
|---|---|---|---|
| 1 | X / 1 | M-ILS150PP | 1: home sensor and encoder index |
| 2 | Y / 2 (physical vertical axis) | UTS100PP | 2: home sensor only; no encoder |
| 3 | Z / 3 | GTS150 | 1: home sensor and encoder index |

This is an origin search, not a sweep between end stops. Factory origin is a
nominal central reference, not a measurement of the midpoint between installed
obstacles or software limits. No full-travel move is used.

## Operation

1. Stop any path, focus scan or survey and turn Active autofocus off. Turn the
   laser off independently; this feature cannot verify or control laser power.
2. Check clearance to the central reference on all axes, including vertical Y,
   specimen holders, objectives and cables. Existing drawing-area jog limits do
   not define the homing route; the controller's limits remain in effect.
3. Connect jog control in the desired mode. `Dry run` simulates all three origins
   without sending serial commands. Connecting never starts a sensor search.
4. Click `Center (sensors)` and confirm. Watch the status under the four buttons.
   Other motion controls are blocked until the sequential operation ends. Each
   axis has a 300-second timeout; an error prevents later axes from starting.
5. After successful homing, all displayed local coordinates are zero. Existing
   controller home presets (`SH`) are preserved; measured raw home coordinates
   become the new software offset. Old sample/focus registration is discarded.
6. Align the specimen and use `Set local home` before running a planned path.
   A path is blocked until that registration is explicitly set again.

In live mode, preflight checks all three stage IDs, millimetre units, enabled
motors, stationary axes, valid search speeds, and home presets inside the
controller software limits. Both hardware (`ZH`) and software (`ZS`) limit
abort-on-limit bits and hardware checking must already be enabled. If software
checking is disabled (`ZS=4H` on this rig), the confirmed Center operation enables
only that missing bit after validating every axis, its current position, and its
home preset against the existing `SL/SR` limits. It reads back the setting before
any search. Missing/invalid replies or controller errors reject the operation.
Limits are never enlarged or disabled, and enabled checking remains enabled.
No nonvolatile save is performed; a power cycle may restore the previous setting.

Center assigns local zero at the sensors. Home immediately afterwards normally
has no distance to travel and now explicitly reports that fact. To test return
motion, jog away from zero and then use Home. Reconnecting resets the local offset;
it is not a substitute for moving to a different target. The connection form now
reflects the server's live/dry-run mode on page reload.

Search speed is temporarily capped at 1 mm/s high and 0.1 mm/s low. Slower
configured values are retained. Saved `OH`, `OL` and `OM` are restored after a
successful sequence; no nonvolatile save is performed. Completion requires
`MD? = 1`, no controller error, and position within 0.01 mm of the home preset.
That tolerance validates the reference assignment, not absolute centering accuracy.

STOP during sensor homing sends `AB` and retains motor holding power, including
on vertical Y. Other existing E-STOP behavior is unchanged. An unsuccessful search
requires reconnecting and repeating the search before trusting the reference.
After an abort, reduced search speeds or the selected mode can remain: setup
commands are not sent while the controller could still be stopping. Review those
settings before the next search. If the link is lost, software cannot guarantee
delivery of an abort; use the physical controller stop.

## Verification

On 2026-10-27, hardware-free tests covered sequential search modes, all-axis
preflight rejection before movement, dry-run isolation, explicit live confirmation,
focus/path exclusion, timeout, STOP, position validation, lost-link handling,
speed preservation, registration reset and the HTTP route. Existing communication
tests also passed. The UI simulation completed in a separate preview process
whose hardware and camera connection factories were blocked; button positions
were verified as two rows of two. No real ESP300 connection or movement was used.

Run the tests with the project's Python 3.12 environment:

```powershell
& .\runtime\python.exe -m unittest test_sensor_home test_esp300_bridge -v
node --check visualizer/app.js
```

Restart the web server when ready to load the new backend, then reload its page.
An existing live server was not restarted during implementation.

*Local screenshot omitted from the public source snapshot: Hardware-blocked preview after a simulated search.*

## Manufacturer references

- [ESP300 manual](https://www.newport.com/medias/sys_master/images/images/h2f/haa/8797091299358/ESP300-User-Manual.pdf): OR, MD, OH, OL, OM, SH, ZH and ZS commands.
- [ILS manual](https://api.p1.mks.com/medias/sys_master/images/images/h7b/hbe/9050123501598/ILS-User-s-Manual.pdf): central origin and encoder index.
- [UTS manual](https://api.p1.mks.com/medias/sys_master/resources/h18/h79/9954227453982/UTS%20-%20User%27s%20Manual/UTS-User-s-Manual.pdf): central origin; PP has no position feedback.
- [GTS manual](https://api.p1.mks.com/medias/sys_master/resources/h59/h75/9954227322910/GTS%20-%20User%27s%20Manual/GTS-User-s-Manual.pdf): central origin and encoder index.
