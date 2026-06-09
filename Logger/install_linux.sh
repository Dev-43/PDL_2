#!/bin/bash
# This script installs the logger as a systemd service on Linux.
# It must be run as root (e.g., sudo ./install_linux.sh)

echo "----------------------------------------"
echo "Installing System Process Logger"
echo "----------------------------------------"

# Check for root privileges
if [ "$EUID" -ne 0 ]; then
  echo "[ERROR] Please run as root: sudo ./install_linux.sh"
  exit 1
fi

INSTALL_DIR="/opt/syslogger"
EXE_NAME="logger"
SERVICE_FILE="/etc/systemd/system/syslogger.service"

# Check if the compiled executable exists in the current directory
if [ ! -f "./$EXE_NAME" ]; then
    echo "[ERROR] The compiled binary '$EXE_NAME' was not found in the current directory."
    echo "Please compile it first on a Linux machine with: g++ main.cpp sqlite3.c -o $EXE_NAME -O3"
    exit 1
fi

# Create installation directory
echo "[*] Creating installation directory at $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

# Copy the executable to the installation directory
echo "[*] Copying binary to $INSTALL_DIR..."
cp "./$EXE_NAME" "$INSTALL_DIR/$EXE_NAME"
chmod +x "$INSTALL_DIR/$EXE_NAME"

# Create Database File with proper permissions
touch "$INSTALL_DIR/logs.db"
chmod 644 "$INSTALL_DIR/logs.db"

# Create the systemd service file
echo "[*] Creating systemd service file at $SERVICE_FILE..."
cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=System Process Logger
After=network.target

[Service]
Type=simple
ExecStart=$INSTALL_DIR/$EXE_NAME
WorkingDirectory=$INSTALL_DIR
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd, enable the service on boot, and start it
echo "[*] Enabling and starting the logger service..."
systemctl daemon-reload
systemctl enable syslogger.service
systemctl start syslogger.service

echo "----------------------------------------"
echo "[SUCCESS] Logger is installed!"
echo "It is now running in the background and will start dynamically on boot."
echo "Logs will be saved in: $INSTALL_DIR/logs.db"
echo "To check the status, run: journalctl -u syslogger.service"
echo "----------------------------------------"
