#!/bin/bash
# This script safely removes the System Process Logger from Linux.
# It must be run as root (e.g., sudo ./uninstall_linux.sh)

echo "----------------------------------------"
echo "Uninstalling System Process Logger"
echo "----------------------------------------"

# Check for root privileges
if [ "$EUID" -ne 0 ]; then
  echo "[ERROR] Please run as root: sudo ./uninstall_linux.sh"
  exit 1
fi

INSTALL_DIR="/opt/syslogger"
EXE_NAME="logger"
SERVICE_FILE="/etc/systemd/system/syslogger.service"

echo "[*] Stopping the service..."
systemctl stop syslogger.service 2>/dev/null

echo "[*] Disabling start-on-boot..."
systemctl disable syslogger.service 2>/dev/null

echo "[*] Removing service file..."
if [ -f "$SERVICE_FILE" ]; then
    rm "$SERVICE_FILE"
fi
systemctl daemon-reload

echo "[*] Removing binary executable..."
if [ -f "$INSTALL_DIR/$EXE_NAME" ]; then
    rm "$INSTALL_DIR/$EXE_NAME"
fi

echo "----------------------------------------"
echo "[SUCCESS] Logger has been safely removed and stopped."
echo "Note: Your logged data in '$INSTALL_DIR/logs.db' has been kept safe and was NOT deleted."
echo "You may delete the '$INSTALL_DIR' directory manually if you no longer need the logs."
echo "----------------------------------------"
