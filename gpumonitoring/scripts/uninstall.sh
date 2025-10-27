#!/bin/bash

set -e

SERVICE_NAME="jetson_gpu_exporter"
INSTALL_DIR="/opt/${SERVICE_NAME}"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
echo "============================================="
echo "🧹 Uninstalling Jetson GPU Prometheus Exporter"
echo "============================================="

if systemctl list-units --type=service --all | grep -q ${SERVICE_NAME}.service; then
  echo "⏹️  Stopping and disabling service..."
  systemctl stop ${SERVICE_NAME} || true
  systemctl disable ${SERVICE_NAME} || true
fi

echo "🗑️  Removing files..."
rm -rf ${INSTALL_DIR}
rm -f ${SERVICE_FILE}

echo "🔄 Reloading systemd..."
systemctl daemon-reload

echo "✅ Uninstallation complete!"
echo "Service ${SERVICE_NAME} and its files have been removed."
echo "============================================="
