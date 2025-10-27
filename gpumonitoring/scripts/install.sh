#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="jetson_gpu_exporter"
INSTALL_DIR="/opt/${SERVICE_NAME}"
PYTHON_BIN="/usr/bin/python3"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
EXPORTER_SCRIPT="exporter_server.py"

echo "============================================="
echo "🚀 Installing Jetson GPU Prometheus Exporter"
echo "============================================="

# Check Python
if ! command -v ${PYTHON_BIN} &>/dev/null; then
  echo "❌ Python3 not found at ${PYTHON_BIN}"
  echo "   Install Python3 and retry."
  exit 1
fi

# Check for root
if [ "$EUID" -ne 0 ]; then
  echo "❌ Please run as root (sudo)."
  exit 1
fi

# Create install directory
echo "📁 Creating installation directory at ${INSTALL_DIR}"
mkdir -p ${INSTALL_DIR}

# Copy files
echo "📦 Copying exporter files..."
cd "${SCRIPT_DIR}/.."
cp -r gpu_module.py db_prometheus.py exporter_server.py tstats.txt ${INSTALL_DIR}/

# Install dependencies
echo "📦 Installing Python dependencies..."
pip3 install --upgrade pip
pip3 install "prometheus-client==0.23.1" "pyhumps==3.8.0"

# Create systemd service file
echo "🧩 Creating systemd service..."
cat <<EOF >${SERVICE_FILE}
[Unit]
Description=Jetson GPU Prometheus Exporter
After=multi-user.target

[Service]
Type=simple
ExecStart=${PYTHON_BIN} ${INSTALL_DIR}/${EXPORTER_SCRIPT}
WorkingDirectory=${INSTALL_DIR}
Restart=always
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd, enable and start service
echo "⚙️  Enabling and starting service..."
systemctl daemon-reload
systemctl enable ${SERVICE_NAME}
systemctl restart ${SERVICE_NAME}

# Wait a few seconds and check status
sleep 2
if systemctl is-active --quiet ${SERVICE_NAME}; then
  echo "✅ Service ${SERVICE_NAME} is running!"
else
  echo "⚠️  Service failed to start. Checking logs..."
  journalctl -u ${SERVICE_NAME} -n 20 --no-pager
  exit 1
fi

# Test metrics endpoint
echo "🌐 Testing metrics endpoint..."
if curl -s http://localhost:9001/metrics | grep -q "tegrastats_gpu"; then
  echo "✅ Metrics endpoint verified: http://localhost:9001/metrics"
else
  echo "⚠️  Metrics endpoint not responding yet. It may take a few seconds."
fi

echo "============================================="
echo "🎉 Installation complete!"
echo "Metrics available at: http://<this-device>:9001/metrics"
echo "Manage service using: sudo systemctl {status|restart|stop} ${SERVICE_NAME}"
echo "============================================="
