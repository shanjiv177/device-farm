from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from app.services.ios_device_manager import IOSDeviceManager
import asyncio
import json
import os

router = APIRouter(prefix="/device-manager/ios", tags=["iOS"])

manager = IOSDeviceManager()

@router.get("/devices")
def list_simulators():
    try:
        return {"devices": manager.list_simulators()}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/device-types")
def list_device_types():
    try:
        return {"device_types": manager.list_device_types()}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/runtimes")
def list_runtimes():
    try:
        return {"runtimes": manager.list_runtimes()}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/simulator/create")
def create_simulator(name: str, device_type: str, runtime: str):
    try:
        return {"message": manager.create_simulator(name, device_type, runtime)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.delete("/simulator/delete")
def delete_simulator(udid: str):
    try:
        return {"message": manager.delete_simulator(udid)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/simulator/start")
def start_simulator(udid: str):
    try:
        return {"message": manager.start_simulator(udid)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/simulator/stop")
def stop_simulator(udid: str):
    try:
        return {"message": manager.stop_simulator(udid)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/simulator/install-app")
def install_ios_app(udid: str, app_path: str):
    try:
        return {"message": manager.install_app(udid, app_path)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

@router.get("/device-info")
def get_ios_device_info(udid: str):
    """
    Returns iOS device screen dimensions if a streamer is active.
    width_pixels/height_pixels are physical pixels; width/height are logical points.
    """
    info = {"udid": udid}
    try:
        streamer = manager.stream.get(udid)
        if streamer and getattr(streamer, 'screen_info', None):
            si = streamer.screen_info or {}
            info.update({
                "width_pixels": si.get('width_pixels'),
                "height_pixels": si.get('height_pixels'),
                "width": si.get('width'),
                "height": si.get('height'),
                "density": si.get('density'),
                "booted": True
            })
        else:
            # Best effort: check simulator boot state
            # xcrun simctl list devices --json includes state; reuse manager.list_simulators
            try:
                devices = manager.list_simulators()
            except FileNotFoundError as e:
                raise HTTPException(status_code=503, detail=str(e))
            state = None
            for d in devices:
                if d.get('udid') == udid:
                    state = d.get('state')
                    break
            info["booted"] = (state == 'Booted')
    except Exception as e:
        info["error"] = str(e)
    return info


@router.websocket("/logs/{udid}")
async def stream_logs(websocket: WebSocket, udid: str):
    await websocket.accept()
    process = None
    try:
        process = manager.start_log_stream(udid)
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, process.stdout.readline)
            if not line:
                break
            # Send a single log line without trailing newline; client will append \n
            text = line.decode('utf-8', errors='replace').rstrip('\r\n')
            await websocket.send_text(text)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"iOS Log stream error: {e}")
    finally:
        if process:
            manager.stop_log_stream(udid)
        try:
            await websocket.close()
        except:
            pass


@router.websocket("/stream/{udid}")
async def stream_video(websocket: WebSocket, udid: str):
    await websocket.accept()
    streamer = None
    try:
        streamer = await manager.get_video_stream(udid)
        print(f"[iOS] Video stream started for {udid}")

        async def send_video_loop():
            frame_count = 0
            async for data in streamer.read_loop():
                try:
                    # frame_count += 1
                    # size = len(data) if hasattr(data, '__len__') else None
                    # if size is not None:
                    #     print(f"[iOS] Sending frame {frame_count} ({size} bytes) for {udid}")
                    # else:
                    #     print(f"[iOS] Sending frame {frame_count} for {udid}")
                    await websocket.send_bytes(data)
                except Exception as e:
                    print(f"[iOS] Error sending frame for {udid}: {e}")
                    raise

        async def receive_input_loop():
            try:
                while True:
                    message = await websocket.receive_text()
                    data = json.loads(message)
                    if data.get('type') == 'touch':
                        print(f"[iOS] Touch event received: {data}")
                        await streamer.inject_touch(data['action'], data['x'], data['y'])
                    elif data.get('type') == 'home':
                        print(f"[iOS] Home event received for {udid}")
                        await streamer.go_home()
            except WebSocketDisconnect:
                pass

        done, pending = await asyncio.wait(
            [
                asyncio.create_task(send_video_loop()),
                asyncio.create_task(receive_input_loop())
            ],
            return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()

    except Exception as e:
        print(f"[iOS] Video stream error for {udid}: {e}")
    finally:
        manager.stop_video_stream(udid)
        try:
            await websocket.close()
        except:
            pass



