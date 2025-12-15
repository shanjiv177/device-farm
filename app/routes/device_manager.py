from fastapi import APIRouter
from fastapi.responses import HTMLResponse
import os


router = APIRouter(prefix="/device-manager", tags=["Device Manager"])

@router.get("/ui", response_class=HTMLResponse)
def get_device_manager_ui():
    """
    Serves the unified device manager UI.
    """
    html_path = os.path.join(os.path.dirname(__file__), "../templates/device_manager.html")
    if os.path.exists(html_path):
        with open(html_path, "r") as f:
            return f.read()
    return "<h1>UI Template not found</h1>"