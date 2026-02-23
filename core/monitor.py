import time

class SystemMonitor:
    def __init__(self, max_points=600, interval=1.0):
        """
        max_points  — how many last points to keep (600 ≈ 10 minutes at 1s step)
        interval    — how often to take new values, in seconds
        """
        self.max_points = max_points
        self.interval = interval
        self.last_sample = 0.0

        # Current values
        self.cpu_percent = 0.0
        self.mem_used = 0
        self.mem_total = 0
        self.temp_c = 0.0

        # History
        self.cpu_history = []
        self.temp_history = []

    def sample(self, now=None):
        """Called from main.py on each loop. Decides itself if it is time to take a new point."""
        if now is None:
            now = time.time()
        if now - self.last_sample < self.interval:
            return
        self.last_sample = now

        self._sample_cpu()
        self._sample_mem()
        self._sample_temp()

        # update histories
        self.cpu_history.append(self.cpu_percent)
        if len(self.cpu_history) > self.max_points:
            self.cpu_history.pop(0)

        self.temp_history.append(self.temp_c)
        if len(self.temp_history) > self.max_points:
            self.temp_history.pop(0)

    def _sample_cpu(self):
        try:
            with open("/proc/loadavg", "r") as f:
                load1 = float(f.read().split()[0])
            # Pi Zero 2W — 4 cores, rough estimate:
            self.cpu_percent = max(0.0, min(100.0, load1 * 25.0))
        except Exception:
            self.cpu_percent = 0.0

    def _sample_mem(self):
        try:
            mem_total = 0
            mem_available = 0
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        mem_total = int(line.split()[1])  # kB
                    elif line.startswith("MemAvailable:"):
                        mem_available = int(line.split()[1])
            self.mem_total = mem_total // 1024
            self.mem_used = (mem_total - mem_available) // 1024
        except Exception:
            self.mem_total = 0
            self.mem_used = 0

    def _sample_temp(self):
        temp = None
        # first vcgencmd
        try:
            import subprocess
            out = subprocess.check_output(["vcgencmd", "measure_temp"]).decode("utf-8")
            if "temp=" in out:
                s = out.split("temp=")[1].split("'")[0]
                temp = float(s)
        except Exception:
            temp = None

        # then sysfs
        if temp is None:
            try:
                with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                    milli = int(f.read().strip())
                temp = milli / 1000.0
            except Exception:
                temp = 0.0

        self.temp_c = temp