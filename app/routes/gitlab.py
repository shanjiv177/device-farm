from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi import Cookie, HTTPException
import os
from dotenv import load_dotenv
from httpx import request
from app import database
from app.database import get_token_from_session, get_connection
import app.services.gitlab_service as gitlab_service

load_dotenv()
GITLAB_URL = os.getenv("GITLAB_URL", "https://git.iris.nitk.ac.in") 
ARTIFACTS_DIR = os.path.join(os.getcwd(), "storage", "artifacts")

router = APIRouter(prefix="/gitlab", tags=["GitLab"])

@router.get("/user")
def get_current_user(dev_farm_session: str = Cookie(None)):
    if not dev_farm_session:
        raise HTTPException(status_code=401, detail="No session cookie found")
    
    gl = gitlab_service.GitLabService(
        url=GITLAB_URL,
        private_token=get_token_from_session(dev_farm_session)
    )

    user = gl.get_user()
    return {"user": user}

@router.get("/branches")
def get_branches(dev_farm_session: str = Cookie(None), project_id: int = 63):
    if not dev_farm_session:
        raise HTTPException(status_code=401, detail="No session cookie found")
    
    gl = gitlab_service.GitLabService(
        url=GITLAB_URL,
        private_token=get_token_from_session(dev_farm_session)
    )

    branches = gl.list_branches(project_id)
    return {"branches": branches}

@router.post("/pipeline/trigger")
def trigger_pipeline(dev_farm_session: str = Cookie(None), project_id: int = 63, branch: str = None, platform: str = None):
    if not dev_farm_session:
        raise HTTPException(status_code=401, detail="No session cookie found")
    
    gl = gitlab_service.GitLabService(
        url=GITLAB_URL,
        private_token=get_token_from_session(dev_farm_session)
    )

    variables = {
        "SCHEME": "debug",
        "PLATFORM": platform,
    }

    user = gl.get_user()
    username = user.get('username')

    pipeline = gl.trigger_pipeline(project_id, branch, variables, username=username)
    return pipeline

@router.get("/pipeline/status/{pipeline_id}")
def get_pipeline_status(dev_farm_session: str = Cookie(None), project_id: int = 63, pipeline_id: int = None):
    if not dev_farm_session:
        raise HTTPException(status_code=401, detail="No session cookie found")
    
    gl = gitlab_service.GitLabService(
        url=GITLAB_URL,
        private_token=get_token_from_session(dev_farm_session)
    )

    pipeline = gl.get_pipeline_status(project_id, pipeline_id)
    return {"pipeline_id": pipeline["id"], "status": pipeline["status"], "web_url": pipeline["web_url"]}

@router.post("/build/{pipeline_id}/download")
def download_build_artifacts(
    pipeline_id: int,
    platform: str,
    project_id: int = 63,
    dev_farm_session: str = Cookie(None)
):
    if not dev_farm_session:
        raise HTTPException(status_code=401, detail="No session cookie found")
    
    token = get_token_from_session(dev_farm_session)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid session")

    gl = gitlab_service.GitLabService(
        url=GITLAB_URL,
        private_token=token
    )
    
    # Determine job name and artifact path based on platform
    job_name = "build_debug_android" if platform == "android" else "build_debug_ios"
    artifact_path_in_zip = "build/app/outputs/flutter-apk/app-debug.apk" if platform == "android" else "build/ios/iphonesimulator/Runner.app"
    
    job = gl.get_job_by_name(project_id, pipeline_id, job_name)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_name} not found in pipeline {pipeline_id}")
        
    if job.status != 'success':
        raise HTTPException(status_code=400, detail=f"Job status is {job.status}, cannot download artifacts yet")

    try:
        if platform == "android":
            # Save as pipeline_id.apk
            filename = f"{pipeline_id}.apk"
            local_path = gl.download_and_extract_artifact(project_id, job.id, artifact_path_in_zip, filename)
            message = "APK downloaded"
        else:
            # Unzip Runner.app directory to folder named pipeline_id.app
            output_dir = f"{pipeline_id}.app"
            local_path = gl.download_and_unzip_ios_app(project_id, job.id, artifact_path_in_zip, output_dir)
            message = "iOS app unzipped"
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download artifact: {str(e)}")

    return {"message": message, "local_path": local_path}

@router.get("/builds")
def list_builds(dev_farm_session: str = Cookie(None)):
    if not dev_farm_session:
        raise HTTPException(status_code=401, detail="No session cookie found")
    
    token = get_token_from_session(dev_farm_session)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid session")

    conn = database.get_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM builds WHERE username = (SELECT username FROM sessions WHERE session_id = ?) ORDER BY created_at DESC', (dev_farm_session,))
    rows = cursor.fetchall()
    conn.close()

    builds = []
    for row in rows:
        print(row)
        builds.append({
            "pipeline_id": row["pipeline_id"],
            "project_id": row["project_id"],
            "ref": row["ref"],
            "platform": row["platform"],
            "web_url": row["web_url"],
            "artifact_path": row["artifact_path"],
            "username": row["username"],
            "created_at": row["created_at"],
        })

    return {"builds": builds}

@router.get("/artifacts")
def list_available_artifacts():
    """List all artifacts in storage directory with metadata.
    Includes files (apk, ipa, zip) and iOS .app directories (unzipped apps).
    """
    if not os.path.exists(ARTIFACTS_DIR):
        return {"artifacts": []}

    entries = os.listdir(ARTIFACTS_DIR)
    artifacts = []

    for name in entries:
        path = os.path.join(ARTIFACTS_DIR, name)
        try:
            if os.path.isfile(path):
                size_bytes = os.path.getsize(path)
                ext = os.path.splitext(name)[1].lower()

                platform = None
                if ext == '.apk':
                    platform = 'android'
                elif ext in ['.ipa', '.zip']:
                    platform = 'ios'

                artifacts.append({
                    "filename": name,
                    "path": path,
                    "size": size_bytes,
                    "size_mb": round(size_bytes / (1024 * 1024), 2),
                    "extension": ext,
                    "platform": platform,
                    "type": "file",
                })
            elif os.path.isdir(path):
                # Include iOS unzipped apps
                # Case A: directory itself ends with .app
                if name.endswith('.app'):
                    total = 0
                    for root, _, files in os.walk(path):
                        for f in files:
                            fp = os.path.join(root, f)
                            try:
                                total += os.path.getsize(fp)
                            except OSError:
                                pass
                    artifacts.append({
                        "filename": name,
                        "path": path,
                        "size": total,
                        "size_mb": round(total / (1024 * 1024), 2),
                        "extension": ".app",
                        "platform": "ios",
                        "type": "directory",
                    })
                else:
                    # Case B: directory contains a nested .app (e.g., storage/artifacts/23856/Runner.app)
                    nested_app_path = None
                    nested_app_name = None
                    try:
                        # Look only one level deep for performance
                        for child in os.listdir(path):
                            child_path = os.path.join(path, child)
                            if os.path.isdir(child_path) and child.endswith('.app'):
                                nested_app_path = child_path
                                nested_app_name = child
                                break
                    except Exception:
                        pass
                    if nested_app_path:
                        total = 0
                        for root, _, files in os.walk(nested_app_path):
                            for f in files:
                                fp = os.path.join(root, f)
                                try:
                                    total += os.path.getsize(fp)
                                except OSError:
                                    pass
                        # Present filename as parent/nested for clarity (e.g., 23856/Runner.app)
                        artifacts.append({
                            "filename": f"{name}/{nested_app_name}",
                            "path": nested_app_path,
                            "size": total,
                            "size_mb": round(total / (1024 * 1024), 2),
                            "extension": ".app",
                            "platform": "ios",
                            "type": "directory",
                        })
        except Exception:
            # Skip unreadable entries
            continue

    # Sort with iOS .app directories first for convenience
    artifacts.sort(key=lambda a: (0 if a.get('extension') == '.app' else 1, a.get('filename')))
    return {"artifacts": artifacts, "total": len(artifacts)}

@router.post("/jobs/{job_id}/artifacts")
def download_artifacts(job_id: int, dev_farm_session: str = Cookie(None), project_id: int = 63):
    if not dev_farm_session:
        raise HTTPException(status_code=401, detail="No session cookie found")
    
    token = get_token_from_session(dev_farm_session)
    gl = gitlab_service.GitLabService(url=GITLAB_URL, private_token=token)
    
    # We need the username for DB logging
    user_info = gl.get_user()
    username = user_info.get('username')

    try:
        artifact_path = gl.download_job_artifact_generic(project_id, job_id, username)
        return {"message": "Artifact downloaded successfully", "path": artifact_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pipelines/{pipeline_id}/jobs")
def get_pipeline_jobs(pipeline_id: int, dev_farm_session: str = Cookie(None), project_id: int = 63):
    if not dev_farm_session:
        raise HTTPException(status_code=401, detail="No session cookie found")
    
    gl = gitlab_service.GitLabService(
        url=GITLAB_URL,
        private_token=get_token_from_session(dev_farm_session)
    )
    
    jobs = gl.get_pipeline_jobs(project_id, pipeline_id)
    return {"jobs": jobs}

@router.get("/builds")
def get_builds(dev_farm_session: str = Cookie(None)):
    if not dev_farm_session:
        raise HTTPException(status_code=401, detail="No session cookie found")
    
    token = get_token_from_session(dev_farm_session)
    gl = gitlab_service.GitLabService(url=GITLAB_URL, private_token=token)
    
    user_info = gl.get_user()
    username = user_info.get('username')

    builds = gl.list_builds(username=username)
    return {"builds": builds}
