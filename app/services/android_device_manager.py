from asyncio import log
import asyncio
import time
import os
import shutil
import subprocess
import threading
import signal
import socket
from app.services.scrcpy_streamer import ScrcpyStreamer

class AndroidDeviceManager:
    def __init__(self):
        self.stream = {} # Stores ScrcpyStreamer instances
        self.log_streams = {}

    def _ensure_cmd_available(self, cmd: str):
        """Ensure the required command exists on PATH, else raise FileNotFoundError."""
        if shutil.which(cmd) is None:
            raise FileNotFoundError(f"Required command '{cmd}' not found in PATH. Please install it and ensure it's accessible.")

    def list_avds(self):
        # emulator is used to list AVDs
        self._ensure_cmd_available('emulator')
        result = subprocess.run(['emulator', '-list-avds'], capture_output=True, text=True)
        devices = result.stdout.splitlines()
        return devices

    def list_connected_devices(self):
        self._ensure_cmd_available('adb')
        result = subprocess.run(['adb', 'devices'], capture_output=True, text=True)
        lines = result.stdout.splitlines()
        devices = []
        for line in lines[1:]: # Skip "List of devices attached"
            if line.strip():
                parts = line.split()
                if len(parts) >= 2 and parts[1] == 'device':
                    devices.append(parts[0])
        return devices
    
    def list_installed_system_images(self):
        result = subprocess.run(['sdkmanager', '--list_installed'], capture_output=True, text=True)
        lines = result.stdout.splitlines()
        images = [line.split(" ")[2] for line in lines if 'system-images;' in line]
        return images
    
    def create_avd(self, name, package, device_profile='pixel_6'):
        subprocess.run(['avdmanager', 'create', 'avd', '-n', name, '-k', package, '-d', device_profile])
        return f"AVD {name} created."
    
    def delete_avd(self, name):
        avd_dir = os.path.expanduser(f'~/.android/avd/{name}.avd')
        ini_file = os.path.expanduser(f'~/.android/avd/{name}.ini')
        if os.path.isdir(avd_dir):
            shutil.rmtree(avd_dir, ignore_errors=True)
        if os.path.isfile(ini_file):
            os.remove(ini_file)
        return f"AVD {name} deleted."
    
    def _is_port_free(self, port):
        """Check if a port is free on localhost."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) != 0

    def _list_avd_to_emulators(self):
        """Return a mapping of avd_name -> list of emulator serials (emulator-PORT)."""
        self._ensure_cmd_available('adb')
        connected = self.list_connected_devices()
        emulator_serials = [d for d in connected if d.startswith('emulator-')]
        mapping = {}
        for serial in emulator_serials:
            try:
                res = subprocess.run(['adb', '-s', serial, 'emu', 'avd', 'name'], capture_output=True, text=True)
                # Some adb emu responses include an extra 'OK' line; extract the actual AVD name
                lines = res.stdout.splitlines()
                name = ""
                for line in lines:
                    s = line.strip()
                    if not s:
                        continue
                    if s.upper() == 'OK':
                        continue
                    name = s
                    break
                if not name:
                    continue
                mapping.setdefault(name, []).append(serial)
            except Exception:
                continue
        return mapping

    def start_emulator(self, avd_name, log):
        """Start an emulator for the given AVD name. If it's already running, reuse it."""
        # Ensure required tools are available
        self._ensure_cmd_available('emulator')
        self._ensure_cmd_available('adb')
        mapping = self._list_avd_to_emulators()
        if avd_name in mapping and mapping[avd_name]:
            serial = mapping[avd_name][0]
            print(f"Reusing running emulator for {avd_name} at {serial}")
            return f"Emulator {avd_name} already running at {serial}."

        # Start emulator without explicit port; let it choose next free port
        process = subprocess.Popen([
                'emulator',
                '-avd', avd_name,
                '-no-window',
                '-gpu', 'host',
                '-no-boot-anim',
                '-no-snapshot',
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Optionally stream logs
        if log:
            def log_emulator_output(stream, queue):
                for line in iter(stream.readline, b''):
                    queue.put(line.decode('utf-8'))
                stream.close()
            threading.Thread(target=log_emulator_output, args=(process.stdout, log), daemon=True).start()
            threading.Thread(target=log_emulator_output, args=(process.stderr, log), daemon=True).start()

        # Wait until emulator appears in adb and resolves to this AVD
        serial = None
        for _ in range(60):
            mapping = self._list_avd_to_emulators()
            if avd_name in mapping and mapping[avd_name]:
                serial = mapping[avd_name][0]
                break
            time.sleep(1)

        if not serial:
            raise RuntimeError(f"Emulator {avd_name} did not appear in adb in time.")

        print(f"Started emulator {avd_name} at {serial}")
        return f"Emulator {avd_name} started at {serial}."
    
    def stop_emulator(self, avd_name):
        self._ensure_cmd_available('adb')
        mapping = self._list_avd_to_emulators()
        serials = mapping.get(avd_name, [])
        if not serials:
            return f"No running emulator found for {avd_name}."
        for serial in serials:
            try:
                subprocess.run(['adb', '-s', serial, 'emu', 'kill'], capture_output=True, text=True)
            except Exception:
                pass
        try:
            self.stop_scrcpy_stream(avd_name)
        except Exception:
            pass
        return f"Stopped {len(serials)} emulator(s) for {avd_name}."
    
    def _refresh_emulator_mapping(self):
        """No-op: mapping is computed on demand via adb; kept for API compatibility."""
        return

    def _get_device_id(self, avd_name):
        mapping = self._list_avd_to_emulators()
        serials = mapping.get(avd_name, [])
        if not serials:
            return None
        if len(serials) > 1:
            # Enforce single emulator per AVD expectation
            raise ValueError(f"Multiple emulators running for AVD {avd_name}: {serials}")
        return serials[0]
    
    def _check_if_booted(self, device_id):
        self._ensure_cmd_available('adb')
        result = subprocess.run(['adb', '-s', device_id, 'shell', 'getprop', 'sys.boot_completed'], capture_output=True, text=True)
        return result.stdout.strip() == '1'

    async def get_video_stream(self, avd_name):
        device_id = self._get_device_id(avd_name)
        if not device_id:
            raise ValueError(f"No active emulator found for AVD {avd_name}")
        
        if avd_name in self.stream:
            # If already running, return existing streamer
            return self.stream[avd_name]
        
        # Ensure the device is booted
        booted = False
        for _ in range(60):  # Wait up to 60 seconds
            if self._check_if_booted(device_id):
                booted = True
                break
            await asyncio.sleep(1)
        
        if not booted:
            raise RuntimeError(f"Emulator {avd_name} did not boot in time.")
        
        streamer = ScrcpyStreamer(device_id)
        await streamer.start()
        
        self.stream[avd_name] = streamer
        return streamer

    def stop_scrcpy_stream(self, avd_name):
        if avd_name in self.stream:
            streamer = self.stream[avd_name]
            streamer.stop()
            del self.stream[avd_name]
            return f"Scrcpy stream for {avd_name} stopped."
        return f"No scrcpy stream found for {avd_name}."
 
    
    def start_log_stream(self, avd_name):
        self._ensure_cmd_available('adb')
        device_id = self._get_device_id(avd_name)
        if not device_id:
            raise ValueError(f"No active emulator found for AVD {avd_name}")
        if avd_name in self.log_streams and self.log_streams[avd_name].poll() is None:
            return self.log_streams[avd_name]
        proc = subprocess.Popen(
            ['adb', '-s', device_id, 'logcat', '-v', 'time', '-T', '0'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        self.log_streams[avd_name] = proc
        return proc

    def stop_log_stream(self, avd_name):
        p = self.log_streams.get(avd_name)
        if p and p.poll() is None:
            p.terminate()
            p.wait()
        del self.log_streams[avd_name]
        return f"Log stream for {avd_name} stopped."
    
    def install_app(self, avd_name, app_path):
        self._ensure_cmd_available('adb')
        mapping = self._list_avd_to_emulators()
        serials = mapping.get(avd_name, [])
        if not serials:
            raise ValueError(f"No running emulator found for AVD {avd_name}")
        if len(serials) > 1:
            return f"Error: Multiple emulators running for AVD {avd_name}: {serials}. Stop duplicates and retry."
        device_id = serials[0]

        if not os.path.exists(app_path):
            return f"Error: App path does not exist: {app_path}"

        # Ensure device is booted
        if not self._check_if_booted(device_id):
            return f"Error: Device {device_id} is not booted."

        result = subprocess.run(
            ['adb', '-s', device_id, 'install', '-r', app_path],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return f"App installed successfully on {avd_name}."
        else:
            return f"Failed to install app on {avd_name}: {result.stderr}"

