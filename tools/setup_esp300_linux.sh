#!/usr/bin/env bash
# Run as root only inside the dedicated FLW-ESP300 WSL distribution.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run through: wsl -d FLW-ESP300 -u root -- bash tools/setup_esp300_linux.sh' >&2
    exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-serial usbutils udev kmod procps
if ! id flw >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash flw
fi
usermod -a -G dialout flw
install -d /etc/udev/rules.d
cat > /etc/udev/rules.d/70-esp300-pl2303.rules <<'EOF'
SUBSYSTEM=="tty", ATTRS{idVendor}=="067b", ATTRS{idProduct}=="2303", GROUP="dialout", MODE="0660"
EOF
if ! pgrep -x systemd-udevd >/dev/null; then
    /lib/systemd/systemd-udevd --daemon
fi
udevadm control --reload-rules
modprobe pl2303
python3 -c 'import serial; print("Linux pySerial", serial.VERSION)'
uname -r
echo 'Linux bridge prerequisites ready. USB is only needed for attach and hardware verification.'
