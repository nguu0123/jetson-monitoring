# SPDX-FileCopyrightText: Copyright (c) 2023-2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: MIT
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

"""
Prometheus as database
Instrumenting message to Prometheus metrics and push to a remote endpoint
"""

from prometheus_client import Gauge, start_http_server, REGISTRY
from threading import Lock
import logging

logger = logging.getLogger(__name__)


class DataBaseProm:
    """
    Prometheus in-memory database (scrape-based)
    Exposes metrics via /metrics endpoint instead of Pushgateway
    """

    def __init__(self, metrics_port: int):
        self._metrics_map = {}
        self._metrics_map_lock = Lock()
        self._labels_tegrastats = ["label", "index"]

        # Start Prometheus HTTP server
        start_http_server(metrics_port)
        logger.info(f"Prometheus exporter running on port {metrics_port}")

    def store(self, msg):
        """Store metrics for tegrastats data"""
        metrics_name = msg["key"].lower()

        with self._metrics_map_lock:
            # Initialize metric if not exists
            if metrics_name not in self._metrics_map:
                help_text = {
                    "tegrastats_gpu_util": "GPU Utilization (%)",
                    "tegrastats_gpu_freq": "GPU Frequency (Hz)",
                    "tegrastats_gpu_temp": "GPU Temperature (°C)",
                    "tegrastats_cpu_temp": "CPU Temperature (°C)",
                    "tegrastats_cpu_usage": "CPU Core Utilization (%)",
                    "tegrastats_ram_usage": "RAM Usage (MB)",
                    "tegrastats_emc_util": "EMC Memory BW Utilization (%)",
                    "tegrastats_emc_freq": "EMC Frequency (Hz)",
                    "tegrastats_nvenc_freq": "NVENC Frequency (Hz)",
                    "tegrastats_nvenc1_freq": "NVENC1 Frequency (Hz)",
                    "tegrastats_nvdec_freq": "NVDEC Frequency (Hz)",
                    "tegrastats_nvdec1_freq": "NVDEC1 Frequency (Hz)",
                    "tegrastats_per_process_gpu_mem": "Per-process GPU Memory (KB)",
                }.get(metrics_name, None)

                if help_text is None:
                    logger.warning(f"Unrecognized metric: {metrics_name}")
                    return

                gauge = Gauge(
                    metrics_name, help_text, self._labels_tegrastats, registry=REGISTRY
                )
                self._metrics_map[metrics_name] = gauge

            # Set metric value
            metric = self._metrics_map[metrics_name].labels(
                label=msg.get("label", "none"), index=msg.get("index", "0")
            )
            try:
                metric.set(float(msg["value"]))
            except Exception:
                logger.warning(f"Invalid value for {metrics_name}: {msg['value']}")
