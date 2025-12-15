import os
import shutil
from urllib.parse import urlencode
import uuid
import httpx
from fastapi import FastAPI, HTTPException, Cookie
from fastapi.responses import RedirectResponse
from app.routes.android_device_manager import router as android_router
from fastapi.middleware.cors import CORSMiddleware
from app.routes.ios_device_manager import router as ios_router
from app.routes.device_manager import router as device_manager_router
import app.database as database
from dotenv import load_dotenv
import app.services.gitlab_service as gitlab_service
from app.routes.gitlab import router as gitlab_router


load_dotenv()

GITLAB_URL = os.getenv("GITLAB_URL", "https://git.iris.nitk.ac.in")
GITLAB_APPLICATION_ID = os.getenv("GITLAB_APPLICATION_ID")
GITLAB_APPLICATION_SECRET = os.getenv("GITLAB_APPLICATION_SECRET")
GITLAB_REDIRECT_URI = os.getenv("GITLAB_REDIRECT_URI", "http://localhost:8000/gitlab/callback")

app = FastAPI()

origins = [
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Explicit origins to support credentials
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(device_manager_router)
app.include_router(ios_router)
app.include_router(android_router)
app.include_router(gitlab_router)

database.init_db()

@app.on_event("startup")
async def on_startup():
    try:
        # Warn if critical tools are missing
        if shutil.which('adb') is None:
            print("[Startup] Warning: 'adb' not found in PATH. Android emulator/device operations will be unavailable.")
        if shutil.which('xcrun') is None:
            print("[Startup] Warning: 'xcrun' not found in PATH. iOS simulator operations will be unavailable.")
        # Log preexisting AVDs and running emulators for visibility
        from app.services.android_device_manager import AndroidDeviceManager
        adm = AndroidDeviceManager()
        try:
            avds = adm.list_avds()
            print(f"[Startup] AVDs: {avds}")
        except FileNotFoundError as e:
            print(f"[Startup] Skipping AVD list: {e}")
        try:
            mapping = adm._list_avd_to_emulators()
            print(f"[Startup] Running emulators: {mapping}")
        except FileNotFoundError as e:
            print(f"[Startup] Skipping emulator mapping: {e}")
    except Exception as e:
        print(f"[Startup] Android scan failed: {e}")

@app.get("/")
def root():
    return {"message": "Open /docs to see the api documentation."}

@app.get("/login")
def login():
    params = {
        "client_id": GITLAB_APPLICATION_ID,
        "redirect_uri": f"http://10.15.0.91:8000/gitlab/callback",
        "response_type": "code",
        "scope": "api",
    }

    print(GITLAB_APPLICATION_ID)

    url = f"{GITLAB_URL}/oauth/authorize?{urlencode(params)}"

    return RedirectResponse(url)

@app.get("/gitlab/callback")
async def gitlab_callback(code: str):
    # Validate required env vars before making request
    if not GITLAB_APPLICATION_ID or not GITLAB_APPLICATION_SECRET:
        raise HTTPException(status_code=500, detail="GitLab OAuth env vars missing: GITLAB_APPLICATION_ID/GITLAB_APPLICATION_SECRET")
    redirect_uri = GITLAB_REDIRECT_URI
    print(redirect_uri)

    async with httpx.AsyncClient() as client:
        try:
            token_response = await client.post(
                f"{GITLAB_URL}/oauth/token",
                data={
                    "client_id": GITLAB_APPLICATION_ID,
                    "client_secret": GITLAB_APPLICATION_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
            )
            token_response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Return a clearer error with response body for diagnostics (e.g., redirect mismatch)
            detail = {
                "error": "GitLab token exchange failed",
                "status": e.response.status_code,
                "url": str(e.request.url),
                "response": e.response.text,
                "hint": "Ensure redirect_uri matches the app configuration in GitLab and env GITLAB_REDIRECT_URI."
            }
            raise HTTPException(status_code=400, detail=detail)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"GitLab token request error: {e}")
        tokens = token_response.json()

        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        if not access_token or not refresh_token:
            raise HTTPException(status_code=400, detail="Failed to obtain access token")
        
        # Fetch user info to get username
        gl = gitlab_service.GitLabService(GITLAB_URL, access_token)
        user = gl.get_user()
        username = user.get('username')
        
        session_id = str(uuid.uuid4())

        conn = database.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO sessions (session_id, access_token, refresh_token, username)
            VALUES (?, ?, ?, ?)
        ''', (session_id, access_token, refresh_token, username))
        conn.commit()
        conn.close()

        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
        response = RedirectResponse(url=frontend_url)
        response.set_cookie(
            key="dev_farm_session",
            value=session_id,
            httponly=True,
            samesite="lax",
            secure=False
        )
        return response
    
@app.get("/logout")
def logout(dev_farm_session: str = Cookie(None)):
    if not dev_farm_session:
        raise HTTPException(status_code=400, detail="No session cookie found")

    conn = database.get_connection()
    cursor = conn.cursor()

    cursor.execute('DELETE FROM sessions WHERE session_id = ?', (dev_farm_session,))
    conn.commit()
    conn.close()

    response = RedirectResponse(url=os.getenv("FRONTEND_URL", "http://localhost:5173"))
    response.delete_cookie(key="dev_farm_session")
    return response

    
def get_token_from_session(session_id: str):
    conn = database.get_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT access_token FROM sessions WHERE session_id = ?', (session_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return row["access_token"]
    return None



