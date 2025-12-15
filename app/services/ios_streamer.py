import asyncio
import subprocess
import math
import json
import os
import time
import tempfile
import io
from PIL import Image

class IOSStreamer:
    def __init__(self, udid):
        self.udid = udid
        self.screen_info = None
        self.last_touch_down = None
        self.running = False
        self.debug = False  # set True for verbose logging
        self._frame_counter = 0

    async def start(self):
        if self.debug:
            print(f"[IOSStreamer] Starting streamer for {self.udid}")
        # Ensure idb is connected
        try:
            res = subprocess.run(['idb', 'connect', self.udid], capture_output=True, text=True)
            if res.returncode != 0:
                if self.debug:
                    print(f"[IOSStreamer] idb connect failed: {res.stderr}")
            else:
                if self.debug:
                    print(f"[IOSStreamer] idb connected")
        except FileNotFoundError:
            if self.debug:
                print("[IOSStreamer] idb executable not found! Will attempt fallback if available.")
            
        await self._fetch_screen_info()
        self.running = True

    async def _fetch_screen_info(self):
        # (Same as your original code)
        try:
            proc = await asyncio.create_subprocess_exec(
                'idb', 'describe', '--udid', self.udid, '--json',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                data = json.loads(stdout)
                self.screen_info = data.get('screen_dimensions')
                if self.debug:
                    print(f"[IOSStreamer] Screen info: {self.screen_info}")
            else:
                if self.debug:
                    print(f"Failed to get screen info: {stderr.decode()}")
        except Exception as e:
            if self.debug:
                print(f"Error fetching screen info: {e}")

    def _scale_coords(self, x, y):
        if not self.screen_info:
            return x, y
            
        # screen_info typically contains:
        # width_pixels, height_pixels (Physical resolution)
        # width, height (Logical points)
        # density (Scale factor)
        
        # The frontend sends coordinates based on the displayed image.
        # Since we are sending JPEGs, the image size matches the physical pixels (usually).
        # However, idb commands expect logical points.
        
        w_pixels = self.screen_info.get('width_pixels')
        w_points = self.screen_info.get('width')
        
        # Calculate scale factor from pixels to points
        scale_x = 1.0
        scale_y = 1.0
        
        if w_pixels and w_points:
            scale_x = w_points / w_pixels
            # Assuming square pixels, scale_y should be the same, but let's calculate if height is available
            h_pixels = self.screen_info.get('height_pixels')
            h_points = self.screen_info.get('height')
            if h_pixels and h_points:
                scale_y = h_points / h_pixels
            else:
                scale_y = scale_x
        elif self.screen_info.get('density'):
             # Fallback to density if explicit dimensions aren't clear
             density = self.screen_info.get('density')
             if density > 0:
                 scale_x = 1.0 / density
                 scale_y = 1.0 / density

        return x * scale_x, y * scale_y

    async def read_loop(self):
        loop = asyncio.get_running_loop()
        if self.debug:
            print(f"[IOSStreamer] Entering read_loop for {self.udid}")
        # Ultra fast screenshot loop
        while self.running:
            start_time = time.time()
            try:
                # Use run_in_executor to avoid blocking the event loop with IO/Image processing
                jpeg_data = await loop.run_in_executor(None, self._capture_screenshot)
                
                if jpeg_data:
                    # Increment frame counter; avoid per-frame prints to reduce IO blocking
                    self._frame_counter += 1
                    yield jpeg_data
                else:
                    # print("[IOSStreamer] No jpeg data captured")
                    await asyncio.sleep(0.05)
                
            except Exception as e:
                if self.debug:
                    print(f"Screenshot capture error: {e}")
                await asyncio.sleep(0.1)

            # Frame pacing for ~60fps
            elapsed = time.time() - start_time
            sleep_time = max(0, (1/60) - elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    def _capture_screenshot(self):
        """
        Capture a screenshot and return JPEG bytes.
        Prefer a zero-tempfile path by streaming PNG to stdout and converting in-memory.
        Fallback to the prior tempfile-based approach if stdout capture fails.
        """
        # First try: xcrun stdout pipeline (fast, no disk IO)
        try:
            proc = subprocess.run(
                ['xcrun', 'simctl', 'io', self.udid, 'screenshot', '--type=png', '-'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2
            )
            if proc.returncode == 0 and proc.stdout:
                try:
                    with Image.open(io.BytesIO(proc.stdout)) as img:
                        if img.mode != 'RGB':
                            img = img.convert('RGB')
                        out = io.BytesIO()
                        # Use modest quality and avoid optimize for speed; subsampling for size
                        img.save(out, format='JPEG', quality=58, optimize=False, subsampling=2)
                        return out.getvalue()
                except Exception as e:
                    if self.debug:
                        print(f"[IOSStreamer] PIL decode/encode failed (stdout path): {e}")
            else:
                if self.debug:
                    err = proc.stderr.decode(errors='ignore') if proc.stderr else ''
                    print(f"[IOSStreamer] xcrun stdout screenshot failed rc={proc.returncode}: {err}")
        except Exception as e:
            if self.debug:
                print(f"[IOSStreamer] xcrun stdout capture error: {e}")

        # Second try: fallback to tempfile-based capture (idb or xcrun)
        fd, temp_path = tempfile.mkstemp(suffix='.png')
        os.close(fd)
        try:
            # Try idb first
            result = subprocess.run(
                ['idb', 'screenshot', '--udid', self.udid, temp_path],
                capture_output=True,
                timeout=2
            )
            if result.returncode != 0:
                # Fallback to xcrun simctl
                result = subprocess.run(
                    ['xcrun', 'simctl', 'io', self.udid, 'screenshot', '--type=png', temp_path],
                    capture_output=True,
                    timeout=2
                )
                if result.returncode != 0:
                    if self.debug:
                        print(f"[IOSStreamer] Tempfile screenshot failed: {result.stderr.decode(errors='ignore')}")
                    return None

            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                with Image.open(temp_path) as img:
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    output = io.BytesIO()
                    img.save(output, format='JPEG', quality=58, optimize=False, subsampling=2)
                    return output.getvalue()
            else:
                if self.debug:
                    print(f"[IOSStreamer] Screenshot file empty or missing: {temp_path}")
                return None
        except Exception as e:
            if self.debug:
                print(f"[IOSStreamer] Error in _capture_screenshot (tempfile path): {e}")
            return None
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass

    async def inject_touch(self, action, x, y):
        # action: 0=down, 1=up, 2=move
        # We only care about down (start) and up (end) for tap/swipe
        
        if self.debug:
            print(f"[IOSStreamer] Touch event received: action={action}, x={x}, y={y}")

        if action == 0: # Down
            self.last_touch_down = (x, y)
            if self.debug:
                print(f"[IOSStreamer] Touch DOWN stored at {self.last_touch_down}")
        elif action == 1: # Up
            if self.last_touch_down:
                start_x_raw, start_y_raw = self.last_touch_down
                
                # Scale both start and end coordinates
                start_x, start_y = self._scale_coords(start_x_raw, start_y_raw)
                end_x, end_y = self._scale_coords(x, y)
                
                # Calculate distance in raw pixels to determine tap vs swipe
                dist = math.sqrt((x - start_x_raw)**2 + (y - start_y_raw)**2)
                
                if self.debug:
                    print(f"[IOSStreamer] Touch UP processing. Raw Dist: {dist:.2f}")
                    print(f"[IOSStreamer] Coords: Raw({start_x_raw},{start_y_raw})->({x},{y}) | Scaled({start_x:.1f},{start_y:.1f})->({end_x:.1f},{end_y:.1f})")

                if dist > 20: 
                    # Swipe
                    if self.debug:
                        print(f"[IOSStreamer] Executing SWIPE from ({int(start_x)},{int(start_y)}) to ({int(end_x)},{int(end_y)})")
                    asyncio.create_task(self._execute_swipe(start_x, start_y, end_x, end_y))
                else:
                    # Tap - use the UP coordinates for the tap location
                    if self.debug:
                        print(f"[IOSStreamer] Executing TAP at ({int(end_x)},{int(end_y)})")
                    await asyncio.create_subprocess_exec(
                        'idb', 'ui', 'tap', 
                        str(int(end_x)), str(int(end_y)), 
                        '--udid', self.udid
                    )
                self.last_touch_down = None
            else:
                if self.debug:
                    print("[IOSStreamer] Touch UP ignored (no matching DOWN)")

    async def _execute_swipe(self, start_x, start_y, end_x, end_y):
        try:
            proc = await asyncio.create_subprocess_exec(
                'idb', 'ui', 'swipe', 
                str(int(start_x)), str(int(start_y)), str(int(end_x)), str(int(end_y)), 
                '--duration', '0.05', # Reduced duration for faster swipe detection
                '--udid', self.udid,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if self.debug:
                if proc.returncode != 0:
                    print(f"[IOSStreamer] Swipe failed: {stderr.decode()}")
                else:
                    print(f"[IOSStreamer] Swipe command sent successfully")
        except Exception as e:
            if self.debug:
                print(f"[IOSStreamer] Swipe execution error: {e}")

    async def go_home(self):
        # (Same as your original code)
        await asyncio.create_subprocess_exec('idb', 'ui', 'button', 'HOME', '--udid', self.udid)

    async def inject_keycode(self, action, keycode):
        # (Same as your original code)
        pass

    def stop(self):
        self.running = False