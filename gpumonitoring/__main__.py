from gpu_module import GpuModule
from db_prometheus import DataBaseProm
import time
import signal
import os
import logging


class GracefulKiller:
    def __init__(self):
        self.kill_now = False
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, *args):
        self.kill_now = True


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    metric_port = 9001

    log_parsing_period = float(os.getenv("LOG_PARSING_PERIOD", "2"))

    db = DataBaseProm(metric_port)
    gpu_module = GpuModule(db, log_parsing_period)
    gpu_module.run(async_mode=True)

    killer = GracefulKiller()
    logging.info(
        f"Jetson GPU Exporter started. Metrics available at :{metric_port}/metrics "
        f"(log parsing period = {log_parsing_period}s)"
    )

    while not killer.kill_now:
        time.sleep(1)

    logging.info("Jetson GPU Exporter shutting down...")
    p = gpu_module.tegrastats_subprocess
    if p:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
