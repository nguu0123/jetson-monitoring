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

from datetime import datetime
import threading
import humps
import logging
import time
import os
import subprocess
from collections import defaultdict
import signal


GPU_SOURCE = "tegrastats"
logger = logging.getLogger(__name__)


class GpuEvent():
    def __init__(self, key, value, label, **kwargs):
        self.timestamp = datetime.utcnow().isoformat()
        self.module = GPU_SOURCE
        self.object = GPU_SOURCE
        self.source = GPU_SOURCE
        self.key = key
        self.value = value
        self.label = label

        for k, v in kwargs.items():
            setattr(self, k, v)


    def to_dict(self):
        return humps.camelize(self.__dict__)

class GpuModule:
    "GpuModule class that monitors gpu utilization through tegrastats"

    def __init__(self, db, _log_parsing_period):
        self.db = db
        self.log_parsing_period = _log_parsing_period
        self.metric_set = defaultdict(set)
        self.tegra_stats = {}
        self.per_process_gpu_usage = {}
        self.td = None
        self.tegrastats_subprocess = None

    def store_gpu_event(
        self,
        metric_value: str,
        metric_name: str,
        metric_key: str,
        **kwargs
    ) -> None:
        event = GpuEvent(metric_key, metric_value, metric_name, **kwargs)
        self.db.store(event.to_dict())

    def _nullify_gpu_data(self):
        try:
            for metric_name, metric_keys in self.metric_set.items():
                for metric_key in metric_keys:
                    self.store_gpu_event(0.0, metric_name, metric_key)
        except Exception:
            logger.exception("Unable to nullify GPU data !!!")

    def _get_per_process_gpu_stats(self):
        script = "sudo cat /sys/kernel/debug/nvmap/iovmm/clients"
        self.per_process_usage = {}
        try:
            output = subprocess.run(script.split(' '), stdout=subprocess.PIPE, timeout=1)
            self.per_process_usage = output.stdout.decode('utf-8').strip()
        except Exception:
            raise Exception('Unable to get per process GPU usage  !')

    def _parse_per_process_gpu_stats(self):
        process_mem_usage = {}
        per_process_usage = self.per_process_usage.split('\n')[1:-1]
        for process_info in per_process_usage:
            process_info = process_info.split()
            # sample prcess_info:
            #   user   process_name  process_id   mem_usage
            # ['user  rosie-perceptio    27278     753528K']
            process_mem_usage[process_info[1]] = int(process_info[3][:-1])

        self.per_process_usage = process_mem_usage

    def _get_tegra_stats(self):
        script = "sudo timeout 0.2 tegrastats --load_cfg ./tstats.txt --interval 100"
        self.tegra_stats = ""

        try:
            # launch a process group so that all child processes get purged as well when the command
            # times out due to high cpu usage
            p = subprocess.Popen(script.split(' '), stdout=subprocess.PIPE, preexec_fn=os.setsid)
            self.tegrastats_subprocess = p
            output, _ = p.communicate(timeout=1)
        except Exception:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            raise Exception('Unable to call tegrastats utility !')
        try:
            self.tegra_stats = output.decode('utf-8').strip()
            return self.tegra_stats
        except Exception:
            raise Exception('Unable to decode tegrastats output !')

    def _parse_tegra_stats(self, tegra_stats_buffer, tegra_stats_iter):
        entity = next(tegra_stats_iter, None)
        if entity is None:
            return entity

        if entity == "RAM":
            ram_info = next(tegra_stats_iter)
            ram_info = ram_info.split("/")[0]
            tegra_stats_buffer[entity] = ram_info

        if entity == "CPU":
            cpu_info = next(tegra_stats_iter)
            cpu_info = cpu_info.replace("[", "").replace("]", "").split(",")
            cpu_info = [e.split("%")[0] for e in cpu_info]
            if entity not in tegra_stats_buffer.keys():
                tegra_stats_buffer[entity] = cpu_info

        if entity == "EMC_FREQ":
            emc_info = next(tegra_stats_iter)
            emc_util = emc_info.split("%")[0]
            emc_freq = str(int(emc_info.split("@")[-1]) * 1000000)
            tegra_stats_buffer["EMC_UTIL"] = emc_util
            tegra_stats_buffer["EMC_FREQ"] = emc_freq

        if entity == "GR3D_FREQ":
            gpu_info = next(tegra_stats_iter)
            gpu_util = gpu_info.split("%")[0]
            gpu_freq = gpu_info.split("@")[-1].replace("[", "").replace("]", "").split(",")
            gpu_freq = [str(int(g)*int(1E6)) for g in gpu_freq]
            tegra_stats_buffer["GPU_UTIL"] = gpu_util
            tegra_stats_buffer["GPU_FREQ"] = gpu_freq

        if entity in ["NVENC", "NVENC1", "NVDEC", "NVDEC1"]:
            nv_info = next(tegra_stats_iter)
            if nv_info != 'off':
                nv_info = str(int(nv_info.split("@")[-1]) * 1000000)
                tegra_stats_buffer[entity] = nv_info

        if "GPU@" in entity or "gpu@" in entity:
            gpu_temp = entity.split("@")[1][:-1]
            tegra_stats_buffer["GPU_TEMP"] = gpu_temp

        if "CPU@" in entity or "cpu@" in entity:
            cpu_temp = entity.split("@")[1][:-1]
            tegra_stats_buffer["CPU_TEMP"] = cpu_temp
        return entity

    def _produce_gpu_event(self):
        for k, v in self.tegra_stats.items():
            if k == "GPU_UTIL":
                self.store_gpu_event(
                    v,
                    "GPU_UTIL",
                    "tegrastats_gpu_util",
                )
                self.metric_set["GPU_UTIL"].add("tegrastats_gpu_util")
            if k == "GPU_FREQ":
                for gpc_id, gpc_freq in enumerate(v):
                    self.store_gpu_event(
                        gpc_freq,
                        "GPU_FREQ",
                        "tegrastats_gpu_freq",
                        **dict(index=gpc_id)
                    )
                    self.metric_set["GPU_FREQ"].add("tegrastats_gpu_freq_{}".format(gpc_id))
            if k == "GPU_TEMP":
                self.store_gpu_event(
                    v,
                    "GPU_TEMP",
                    "tegrastats_gpu_temp",
                )
                self.metric_set["GPU_TEMP"].add("tegrastats_gpu_temp")
            if k == "CPU_TEMP":
                self.store_gpu_event(
                    v,
                    "CPU_TEMP",
                    "tegrastats_cpu_temp",
                )
                self.metric_set["CPU_TEMP"].add("tegrastats_cpu_temp")
            if k == "CPU":
                for cpu_id, cpu_util in enumerate(v):
                    if cpu_util != 'off':
                        self.store_gpu_event(
                            cpu_util,
                            "CPU",
                            "tegrastats_cpu_usage",
                            **dict(index=cpu_id)
                        )
                        self.metric_set["CPU"].add("tegrastats_cpu_usage_{}".format(cpu_id))
            if k == "RAM":
                self.store_gpu_event(
                    v,
                    "RAM",
                    "tegrastats_ram_usage",
                )
                self.metric_set["RAM"].add("tegrastats_ram_usage")
            if k == "EMC_FREQ":
                self.store_gpu_event(
                    v,
                    "EMC_FREQ",
                    "tegrastats_emc_freq",
                )
                self.metric_set["EMC_FREQ"].add("tegrastats_emc_freq")
            if k == "EMC_UTIL":
                self.store_gpu_event(
                    v,
                    "EMC_UTIL",
                    "tegrastats_emc_util",
                )
                self.metric_set["EMC_UTIL"].add("tegrastats_emc_util")
            if k == "NVENC":
                self.store_gpu_event(
                    v,
                    "NVENC",
                    "tegrastats_nvenc_freq",
                )
                self.metric_set["NVENC"].add("tegrastats_nvenc_freq")
            if k == "NVENC1":
                self.store_gpu_event(
                    v,
                    "NVENC1",
                    "tegrastats_nvenc1_freq",
                )
                self.metric_set["NVENC1"].add("tegrastats_nvenc1_freq")
            if k == "NVDEC":
                self.store_gpu_event(
                    v,
                    "NVDEC",
                    "tegrastats_nvdec_freq",
                )
                self.metric_set["NVDEC"].add("tegrastats_nvdec_freq")
            if k == "NVDEC1":
                self.store_gpu_event(
                    v,
                    "NVDEC1",
                    "tegrastats_nvdec1_freq",
                )
                self.metric_set["NVDEC1"].add("tegrastats_nvdec1_freq")

        for k, v in self.per_process_usage.items():
            self.store_gpu_event(v, k, "tegrastats_per_process_gpu_mem",)
            self.metric_set[k].add("tegrastats_per_process_gpu_mem")

    def _process_gpu_stats_forever(self):
        while True:
            time.sleep(self.log_parsing_period)
            try:
                try:
                    self._get_tegra_stats()
                except Exception as e:
                    logger.exception("Failed to get tegra stats !!!")
                    raise e

                tegra_stats_iter = iter(self.tegra_stats.split(" "))
                tegra_stats_buffer = {}
                entity = None
                while True:
                    try:
                        entity = self._parse_tegra_stats(
                            tegra_stats_buffer, tegra_stats_iter)
                        if entity is None:
                            break
                    except Exception as e:
                        logger.exception("Failed to parse tegra stats")
                        raise e
                self.tegra_stats = tegra_stats_buffer

                try:
                    self._get_per_process_gpu_stats()
                except Exception as e:
                    logger.exception("Failed to get per process gpu usage !!!")
                    raise e

                try:
                    self._parse_per_process_gpu_stats()
                except Exception as e:
                    logger.exception("Failed to get per process gpu usage !!!")
                    raise e

                try:
                    self._produce_gpu_event()
                except Exception as e:
                    logger.exception("Failed to store gpu event !!!")
                    raise e

            except Exception:
                self._nullify_gpu_data()

    def run(self, async_mode=True):
        if async_mode:
            self.td = threading.Thread(target=self._process_gpu_stats_forever, args=(), daemon=True)
            self.td.start()
            return self.td
        else:
            self._process_gpu_stats_forever()
