import os
import socket
import asyncio
import subprocess
import struct

class ScrcpyStreamer:
    def __init__(self, device_id, port=None):
        self.device_id = device_id
        self.port = port
        self.process = None
        self.video_socket = None
        self.control_socket = None
        # self.scid removed to use default socket name
        self.server_path = self._find_server()
        self.device_width = 720 
        self.device_height = 1280

    def _find_server(self):
        # Check env var first
        if os.environ.get('SCRCPY_SERVER_PATH'):
            if os.path.exists(os.environ['SCRCPY_SERVER_PATH']):
                return os.environ['SCRCPY_SERVER_PATH']

        paths = [
            os.path.join(os.getcwd(), 'app', 'scrcpy-server'),
            'app/scrcpy-server',
            'scrcpy-server', # In current dir
            'scrcpy-server.jar'
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        raise FileNotFoundError("scrcpy-server not found. Please install scrcpy or set SCRCPY_SERVER_PATH.")

    async def start(self):
        # 0. Detect Screen Size
        try:
            res = subprocess.run(['adb', '-s', self.device_id, 'shell', 'wm', 'size'], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout:
                line = res.stdout.splitlines()[0]
                if 'Physical size:' in line:
                    parts = line.split(': ')[1].strip().split('x')
                    self.device_width = int(parts[0])
                    self.device_height = int(parts[1])
                    print(f"Detected device resolution: {self.device_width}x{self.device_height}")
        except Exception as e:
            print(f"Failed to detect screen size: {e}")

        # 1. Push Server
        print(f"Pushing scrcpy server from {self.server_path} to device...")
        try:
            subprocess.run(['adb', '-s', self.device_id, 'push', self.server_path, '/data/local/tmp/scrcpy-server.jar'], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Failed to push scrcpy-server: {e}")
            raise

        # 2. Forward Port
        if not self.port:
            # Find free port
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', 0))
                self.port = s.getsockname()[1]
        
        subprocess.run(['adb', '-s', self.device_id, 'forward', f'tcp:{self.port}', f'localabstract:scrcpy'], check=True)
        print(f"Forwarded local port {self.port} to scrcpy on device.")

        # 3. Start Server
        # Scrcpy 2.x+ arguments
        cmd = [
            'adb', '-s', self.device_id, 'shell',
            'CLASSPATH=/data/local/tmp/scrcpy-server.jar',
            'app_process', '/', 'com.genymobile.scrcpy.Server',
            '2.7', # Protocol version
            'log_level=info',
            'video=true',
            'audio=false',
            'control=true',
            'tunnel_forward=true',
            'video_bit_rate=1000000', # Reduced bitrate for stability
            'max_size=720',           # Reduced max size for stability
            'send_device_meta=false', # Skip device name header
            'send_frame_meta=true',   # Send PTS + Size header
            'send_dummy_byte=true',   # Enable handshake
            'raw_stream=false',
            'video_encoder=OMX.google.h264.encoder'
        ]
        
        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Wait a bit for server to start
        await asyncio.sleep(1)
        
        # 4. Connect Video Socket
        self.video_socket = await self._connect_socket_with_retry()
        if not self.video_socket:
            self.stop()
            raise ConnectionError("Failed to connect to scrcpy video socket")
            
        # 5. Handshake (Video Socket)
        loop = asyncio.get_running_loop()
        try:
            # Read dummy byte to confirm connection and stream start
            await asyncio.wait_for(loop.sock_recv(self.video_socket, 1), timeout=2.0)
            print("Scrcpy handshake successful (dummy byte received)")
        except Exception as e:
            print(f"Scrcpy handshake failed: {e}")
            self._print_server_error()
            self.stop()
            raise ConnectionError(f"Failed to receive handshake from scrcpy: {e}")

        # 6. Connect Control Socket
        # The server expects a second connection for control if control=true
        try:
            self.control_socket = await self._connect_socket_with_retry()
            if not self.control_socket:
                print("Warning: Failed to connect to control socket. Touch input may not work.")
            else:
                print("Connected to scrcpy control socket")
        except Exception as e:
             print(f"Error connecting control socket: {e}")

    async def _connect_socket_with_retry(self):
        retry = 0
        while retry < 5:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect(('localhost', self.port))
                s.setblocking(False)
                return s
            except ConnectionRefusedError:
                retry += 1
                await asyncio.sleep(0.5)
        return None

    def _print_server_error(self):
        if self.process and self.process.poll() is not None:
            stderr = self.process.stderr.read().decode('utf-8', errors='replace')
            print(f"Scrcpy server stderr:\n{stderr}")

    async def read_loop(self):
        loop = asyncio.get_running_loop()
        
        # 1. Read Video Metadata (12 bytes)
        # codec id (u32), width (u32), height (u32)
        meta_buffer = b''
        while len(meta_buffer) < 12:
            chunk = await loop.sock_recv(self.video_socket, 12 - len(meta_buffer))
            if not chunk:
                print("Socket closed during metadata read")
                self._print_server_error()
                return
            meta_buffer += chunk
            
        codec_id, width, height = struct.unpack('!III', meta_buffer)
        try:
            codec_name = meta_buffer[:4].decode('ascii')
        except:
            codec_name = f"0x{codec_id:x}"
        print(f"Video Metadata: Codec={codec_name}, Width={width}, Height={height}")

        # Update device dimensions to match the stream resolution
        # This ensures touch coordinates (which are relative to the stream) map correctly
        self.device_width = width
        self.device_height = height

        header_buffer = b''
        first_packet = True
        
        try:
            while True:
                # Read 12-byte header (8 bytes PTS + 4 bytes Size)
                while len(header_buffer) < 12:
                    chunk = await loop.sock_recv(self.video_socket, 12 - len(header_buffer))
                    if not chunk:
                        print("Socket closed during header read")
                        self._print_server_error()
                        return
                    header_buffer += chunk
                
                pts_flags, size = struct.unpack('!QI', header_buffer)
                
                # Parse flags and PTS from the 64-bit integer
                # config packet flag (u1) -> bit 63
                # key frame flag (u1) -> bit 62
                # PTS (u62) -> bits 0-61
                is_config = (pts_flags >> 63) & 1
                is_keyframe = (pts_flags >> 62) & 1
                pts = pts_flags & 0x3FFFFFFFFFFFFFFF

                header_buffer = b'' # Reset for next packet
                
                if first_packet:
                    print(f"First video packet: Size={size}, PTS={pts}, Config={is_config}, Keyframe={is_keyframe}")
                    first_packet = False
                
                if size > 2000000: # Sanity check
                    print(f"Warning: Large packet size {size}")

                # Read 'size' bytes of data
                data_buffer = b''
                while len(data_buffer) < size:
                    chunk = await loop.sock_recv(self.video_socket, size - len(data_buffer))
                    if not chunk:
                        print("Socket closed during data read")
                        return
                    data_buffer += chunk
                
                yield data_buffer
                
        except Exception as e:
            print(f"Scrcpy read error: {e}")
            pass

    async def inject_touch(self, action, x, y):
        if not self.control_socket: return
        try:
            # Scrcpy Protocol v2 InjectTouch (Type 2)
            # 1b type, 1b action, 8b pointerId, 4b x, 4b y, 2b w, 2b h, 2b pressure, 4b actionBtn, 4b buttons
            # Action: 0=down, 1=up, 2=move
            pressure = 0xFFFF if action != 1 else 0
            buttons = 1 if action != 1 else 0 # Set primary button for down/move
            pointer_id = 0 # Use consistent pointer_id for single touch
            msg = struct.pack('!BBQiiHHHii', 
                2, action, pointer_id, int(x), int(y), 
                self.device_width, self.device_height, pressure, 0, buttons
            )
            loop = asyncio.get_running_loop()
            await loop.sock_sendall(self.control_socket, msg)
        except Exception as e:
            print(f"Failed to inject touch: {e}")

    async def inject_keycode(self, action, keycode):
        if not self.control_socket: return
        try:
            # Scrcpy Protocol v2 InjectKeyCode (Type 0)
            # 1b type, 1b action, 4b keycode, 4b repeat, 4b metaState
            msg = struct.pack('!BBiII', 0, action, int(keycode), 0, 0)
            loop = asyncio.get_running_loop()
            await loop.sock_sendall(self.control_socket, msg)
        except Exception as e:
            print(f"Failed to inject keycode: {e}")

    def stop(self):
        if self.video_socket:
            self.video_socket.close()
        if self.control_socket:
            self.control_socket.close()
        if self.process:
            self.process.terminate()
        if self.port:
            subprocess.run(['adb', '-s', self.device_id, 'forward', '--remove', f'tcp:{self.port}'], stderr=subprocess.DEVNULL)
