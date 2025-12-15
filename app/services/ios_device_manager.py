import asyncio
import subprocess
import json
import shutil
import os
from app.services.ios_streamer import IOSStreamer

class IOSDeviceManager:
    def __init__(self):
        self.stream = {}  # Stores IOSStreamer instances
        self.log_streams = {}

    def _ensure_xcrun_available(self):
        """Ensure xcrun (and thus simctl) is available on PATH."""
        if shutil.which('xcrun') is None:
            raise FileNotFoundError("Required command 'xcrun' (for simctl) not found in PATH. Install Xcode command-line tools.")

    def _ensure_idb_available(self):
        if shutil.which('idb') is None:
            # Not strictly requested, but helpful to surface clearly
            raise FileNotFoundError("Required command 'idb' not found in PATH. Install Facebook idb or remove features requiring it.")

    def list_targets(self):
        self._ensure_idb_available()
        result = subprocess.run([
            'idb',
            'list-targets',
            '--json'
        ], capture_output=True, text=True)
        
        # idb output is often JSON Lines
        targets = []
        for line in result.stdout.splitlines():
            if line.strip():
                try:
                    targets.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return targets
    
    def list_simulators(self):
        self._ensure_xcrun_available()
        result = subprocess.run([
            'xcrun',
            'simctl',
            'list',
            'devices',
            '--json'
        ], capture_output=True, text=True)
        devices_dict = json.loads(result.stdout)['devices']
        
        # Flatten the dictionary
        flat_list = []
        for runtime, devices in devices_dict.items():
            for device in devices:
                device['runtime'] = runtime
                flat_list.append(device)
        return flat_list

    def list_device_types(self):
        self._ensure_xcrun_available()
        result = subprocess.run(['xcrun', 'simctl', 'list', 'devicetypes', '--json'], capture_output=True, text=True)
        try:
            return json.loads(result.stdout)['devicetypes']
        except (json.JSONDecodeError, KeyError):
            return []

    def list_runtimes(self):
        self._ensure_xcrun_available()
        result = subprocess.run(['xcrun', 'simctl', 'list', 'runtimes', '--json'], capture_output=True, text=True)
        try:
            return json.loads(result.stdout)['runtimes']
        except (json.JSONDecodeError, KeyError):
            return []

    def create_simulator(self, name, device_type, runtime):
        self._ensure_xcrun_available()
        # device_type example: "com.apple.CoreSimulator.SimDeviceType.iPhone-14"
        # runtime example: "com.apple.CoreSimulator.SimRuntime.iOS-16-2"
        try:
            result = subprocess.run(
                ['xcrun', 'simctl', 'create', name, device_type, runtime],
                capture_output=True, text=True, check=True
            )
            udid = result.stdout.strip()
            return f"Simulator {name} created with UDID {udid}."
        except subprocess.CalledProcessError as e:
            return f"Failed to create simulator: {e.stderr}"

    def delete_simulator(self, udid):
        self._ensure_xcrun_available()
        try:
            subprocess.run(['xcrun', 'simctl', 'delete', udid], check=True)
            return f"Simulator {udid} deleted."
        except subprocess.CalledProcessError as e:
            return f"Failed to delete simulator: {e.stderr}"

    def start_simulator(self, udid):
        self._ensure_xcrun_available()
        # Check if already booted to avoid redundant boot
        try:
            devices = self.list_simulators()
            for d in devices:
                if d.get('udid') == udid and d.get('state') == 'Booted':
                    return f"Simulator {udid} already booted."
        except Exception:
            # If listing fails, attempt boot anyway
            pass

        subprocess.run(['xcrun', 'simctl', 'boot', udid], check=True)
        # Connect idb
        # idb is optional for streaming; check availability before using
        if shutil.which('idb') is not None:
            subprocess.run(['idb', 'connect', udid])
        return f"Simulator {udid} booted."

    def stop_simulator(self, udid):
        self._ensure_xcrun_available()
        subprocess.run(['xcrun', 'simctl', 'shutdown', udid], check=True)
        self.stop_video_stream(udid)
        self.stop_log_stream(udid)
        return f"Simulator {udid} shutdown."

    async def get_video_stream(self, udid):
        if udid in self.stream:
            return self.stream[udid]
        
        streamer = IOSStreamer(udid)
        await streamer.start()
        self.stream[udid] = streamer
        return streamer

    def stop_video_stream(self, udid):
        if udid in self.stream:
            self.stream[udid].stop()
            del self.stream[udid]

    def start_log_stream(self, udid):
        self._ensure_xcrun_available()
        if udid in self.log_streams and self.log_streams[udid].poll() is None:
            return self.log_streams[udid]
        
        # xcrun simctl spawn booted log stream --style compact
        process = subprocess.Popen(
            ['xcrun', 'simctl', 'spawn', udid, 'log', 'stream', '--style', 'compact'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        self.log_streams[udid] = process
        return process

    def stop_log_stream(self, udid):
        if udid in self.log_streams:
            p = self.log_streams[udid]
            if p.poll() is None:
                p.terminate()
                p.wait()
            del self.log_streams[udid]

    def install_app(self, udid, app_path):
        # Requires idb and xcrun boot/shutdown
        self._ensure_xcrun_available()
        self._ensure_idb_available()
        try:
            # Resolve install target:
            # - If app_path is an .app directory, install directly
            # - If app_path is a parent directory containing a single .app (e.g., pipeline folder), pick nested .app
            # - If it's an .ipa file, idb supports installing it; pass through
            target_path = app_path
            if os.path.isdir(app_path) and not app_path.endswith('.app'):
                # Search one level for a nested .app
                try:
                    for child in os.listdir(app_path):
                        p = os.path.join(app_path, child)
                        if os.path.isdir(p) and child.endswith('.app'):
                            target_path = p
                            break
                except Exception:
                    pass

            result = subprocess.run(
                ['idb', 'install', '--udid', udid, target_path],
                capture_output=True, text=True, check=True
            )
            return f"App installed on {udid}: {result.stdout}"
        except subprocess.CalledProcessError as e:
            return f"Failed to install app on {udid}: {e.stderr}"





