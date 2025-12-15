from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
import app.services.android_device_manager as adm
import asyncio
import os
import json

router = APIRouter(prefix="/device-manager/android", tags=["Android"])

manager = adm.AndroidDeviceManager()

@router.get("/status")
def get_device_manager_status():
    return {"status": "Device Manager is running"}

@router.get("/ui", response_class=HTMLResponse)
def get_device_manager_ui():
    """
    Serves a simple UI to test the device manager and streaming.
    """
    html_path = os.path.join(os.path.dirname(__file__), "../templates/device_manager.html")
    if os.path.exists(html_path):
        with open(html_path, "r") as f:
            return f.read()
    return "<h1>UI Template not found</h1>"

@router.get("/devices")
def list_connected_android_devices():
    # Keep emulator mapping warm before listing devices
    try:
        manager._refresh_emulator_mapping()
    except Exception:
        pass
    try:
        devices = manager.list_connected_devices()
        return {"connected_devices": devices}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

@router.get("/avds")
def list_avds():
    # Refresh emulator mapping to ensure avd_name <-> emulator serial stays accurate
    try:
        manager._refresh_emulator_mapping()
    except Exception:
        pass
    try:
        avds = manager.list_avds()
        return {"avds": avds}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

@router.get("/avds/status")
def list_avds_with_status():
    """Return AVDs with their running emulator serials."""
    try:
        manager._refresh_emulator_mapping()
    except Exception:
        pass
    try:
        avds = manager.list_avds()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    # mapping avd_name -> [emulator-PORT]
    try:
        mapping = manager._list_avd_to_emulators()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        mapping = {}
    items = []
    for name in avds:
        serials = mapping.get(name, [])
        items.append({
            "avd_name": name,
            "running_serials": serials,
            "running": bool(serials)
        })
    return {"avds": items}

@router.get("/emulators")
def list_running_emulators():
    """List running emulator serials and their resolved AVD names."""
    try:
        manager._refresh_emulator_mapping()
    except Exception:
        pass
    try:
        mapping = manager._list_avd_to_emulators()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    emulators = []
    for avd_name, serials in mapping.items():
        for serial in serials:
            emulators.append({"avd_name": avd_name, "serial": serial})
    return {"emulators": emulators}

@router.get("/system-images")
def list_installed_system_images():
    # Not strictly required, but safe to refresh
    try:
        manager._refresh_emulator_mapping()
    except Exception:
        pass
    try:
        images = manager.list_installed_system_images()
        return {"installed_system_images": images}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

@router.get("/device-info")
def get_android_device_info(avd_name: str):
    """
    Returns device resolution for the current scrcpy stream if available.
    width/height are in device pixels. Also returns boot status when known.
    """
    # Ensure latest emulator mapping before querying
    try:
        manager._refresh_emulator_mapping()
    except Exception:
        pass
    info = {"avd_name": avd_name}
    try:
        streamer = manager.stream.get(avd_name)
        if streamer:
            info.update({
                "width": streamer.device_width,
                "height": streamer.device_height,
                "booted": True
            })
        else:
            # No active stream; we can still indicate boot status if emulator is managed
            try:
                device_id = manager._get_device_id(avd_name)
                if device_id:
                    info["booted"] = manager._check_if_booted(device_id)
            except FileNotFoundError as e:
                raise HTTPException(status_code=503, detail=str(e))
            else:
                info["booted"] = False
    except Exception as e:
        info["error"] = str(e)
    return info

@router.post("/avd/create")
def create_android_avd(name: str, package: str, device_profile: str = 'pixel_6'):
    result = manager.create_avd(name, package, device_profile)
    return {"message": result}

@router.delete("/avd/delete")
def delete_android_avd(name: str):
    result = manager.delete_avd(name)
    return {"message": result}

@router.post("/emulator/start")
def start_android_emulator(avd_name: str):
    log = None
    # Refresh mapping before start in case of stale DB
    try:
        manager._refresh_emulator_mapping()
    except Exception:
        pass
    try:
        result = manager.start_emulator(avd_name, log)
        return {"message": result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

@router.post("/emulator/stop")
def stop_android_emulator(avd_name: str):
    # Refresh mapping so stop resolves correct serial/pid
    try:
        manager._refresh_emulator_mapping()
    except Exception:
        pass
    try:
        result = manager.stop_emulator(avd_name)
        return {"message": result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

@router.post("/emulator/install-app")
def install_android_app(avd_name: str, app_path: str):
    # Refresh mapping so install targets the correct emulator
    try:
        manager._refresh_emulator_mapping()
    except Exception:
        pass
    try:
        result = manager.install_app(avd_name, app_path)
        return {"message": result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

@router.websocket("/logs/{avd_name}")
async def stream_logs(websocket: WebSocket, avd_name: str):
    # Refresh mapping prior to launching logcat
    try:
        manager._refresh_emulator_mapping()
    except Exception:
        pass
    await websocket.accept()
    process = None
    try:
        process = manager.start_log_stream(avd_name)
        print(f"Log stream started (PID: {process.pid}) for {avd_name}")
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, process.stdout.readline)
            if not line:
                err = process.stderr.read()
                if err:
                    print(f"Logcat stderr: {err.decode(errors='replace')}")
                break
            await websocket.send_text(line.decode('utf-8', errors='replace').rstrip())
    except WebSocketDisconnect:
        print(f"Log WebSocket disconnected for {avd_name}")
    except Exception as e:
        print(f"Error in log stream for {avd_name}: {e}")
    finally:
        if process:
            manager.stop_log_stream(avd_name)
        try:
            if websocket.client_state.name != "DISCONNECTED":
                await websocket.close()
        except RuntimeError:
            pass

@router.websocket("/stream/{avd_name}")
async def stream_video(websocket: WebSocket, avd_name: str):
    await websocket.accept()
    streamer = None
    try:
        # First consult current mapping from Home page's perspective
        try:
            mapping = manager._list_avd_to_emulators()
        except Exception:
            mapping = {}

        # If there's already a running emulator for the requested AVD, proceed directly
        if mapping.get(avd_name):
            try:
                streamer = await manager.get_video_stream(avd_name)
                print(f"Video stream started for {avd_name}")
            except Exception as e:
                await websocket.send_text(json.dumps({
                    "error": f"Failed to start stream for running emulator {avd_name}: {e}",
                }))
                return
        else:
            # No running emulator for this AVD; start it and then retry
            print(f"No active emulator for {avd_name}, attempting to start...")
            try:
                _ = manager.start_emulator(avd_name, log=None)
            except Exception as e2:
                await websocket.send_text(json.dumps({
                    "error": f"Failed to start emulator for {avd_name}: {e2}",
                }))
                return
            # Poll mapping until the new emulator is visible, then start stream
            for _ in range(60):
                try:
                    mapping = manager._list_avd_to_emulators()
                except Exception:
                    mapping = {}
                if mapping.get(avd_name):
                    break
                await asyncio.sleep(1)
            if not mapping.get(avd_name):
                await websocket.send_text(json.dumps({
                    "error": f"Emulator for {avd_name} did not appear in mapping in time.",
                }))
                return
            try:
                streamer = await manager.get_video_stream(avd_name)
                print(f"Video stream started for {avd_name} after auto-start")
            except Exception as e3:
                await websocket.send_text(json.dumps({
                    "error": f"Failed to start stream after emulator launch for {avd_name}: {e3}",
                }))
                return
        
        # Task 1: Read video from Scrcpy -> Send to WebSocket
        async def send_video_loop():
            try:
                # read_loop yields bytes. If it stops yielding, the stream died.
                async for data in streamer.read_loop():
                    await websocket.send_bytes(data)
            except Exception as e:
                print(f"Video send error: {e}")
                # If video fails, we want to exit to trigger cleanup
                raise e 

        # Task 2: Read Input from WebSocket -> Send to Scrcpy
        async def receive_input_loop():
            try:
                while True:
                    message = await websocket.receive_text()
                    data = json.loads(message)
                    if data.get('type') == 'touch':
                        # action: 0=down, 1=up, 2=move
                        x = data['x']
                        y = data['y']
                        # Allow normalized coordinates (0..1) from frontend; scale to device pixels
                        try:
                            if 0 <= x <= 1 and 0 <= y <= 1:
                                x = int(x * streamer.device_width)
                                y = int(y * streamer.device_height)
                        except Exception:
                            # If types are unexpected, fallback to ints
                            try:
                                x = int(x)
                                y = int(y)
                            except Exception:
                                pass
                        await streamer.inject_touch(data['action'], x, y)
                        print(f"injecting touch at {x}, {y}")
                    elif data.get('type') == 'key':
                        # action: 0=down, 1=up
                        await streamer.inject_keycode(0, data['keycode'])
                        await streamer.inject_keycode(1, data['keycode'])
            except WebSocketDisconnect:
                # Normal disconnect, just exit
                pass
            except Exception as e:
                print(f"Input receive error: {e}")

        # RUN BOTH: Wait for whichever finishes first
        # - If client disconnects -> receive_input_loop finishes -> We cancel video
        # - If scrcpy crashes -> send_video_loop finishes -> We close socket
        done, pending = await asyncio.wait(
            [
                asyncio.create_task(send_video_loop()), 
                asyncio.create_task(receive_input_loop())
            ],
            return_when=asyncio.FIRST_COMPLETED
        )

        # Cancel whichever task is still running
        for task in pending:
            task.cancel()
            
    except Exception as e:
        print(f"Stream setup error for {avd_name}: {e}")
    
    finally:
        # Stop Scrcpy (Optional: Keep running if you want shared sessions)
        manager.stop_scrcpy_stream(avd_name)
        
        try:
            await websocket.close()
        except RuntimeError:
            # Socket might already be closed/disconnected
            pass

@router.post("/emulators/refresh")
def refresh_emulator_mapping():
    """Manually refresh AVD to emulator mapping from running instances."""
    try:
        manager._refresh_emulator_mapping()
        return {"message": "Emulator mapping refreshed"}
    except Exception as e:
        return {"message": f"Failed to refresh mapping: {e}"}