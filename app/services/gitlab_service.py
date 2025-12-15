import gitlab
import os
import zipfile
import shutil
from app.database import get_connection


ARTIFACTS_DIR = "storage/artifacts"


class GitLabService:
    def __init__(self, url, private_token):
        self.gl = gitlab.Gitlab(url, oauth_token=private_token)
        self.gl.auth()

    def get_user(self):
        return self.gl.user.attributes

    def list_projects(self):
        return self.gl.projects.list()
    
    def list_branches(self, project_id=63):
        project = self.gl.projects.get(project_id)
        branches = project.branches.list(get_all=True)
        return [
            {
                "name": branch.name,
                "commit": branch.commit['id'],
                "merged": branch.merged,
                "protected": branch.protected,
            }
            for branch in branches
        ]
    
    def trigger_pipeline(self, project_id=63, ref=None, variables=None, username=None):
        project = self.gl.projects.get(project_id)
        data = {'ref': ref}
        if variables:
            data['variables'] = [{'key': k, 'value': v} for k, v in variables.items()]
        pipeline = project.pipelines.create(data)
        
        # Store build in DB
        platform = variables.get('PLATFORM', 'unknown') if variables else 'unknown'
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO builds (pipeline_id, project_id, ref, platform, web_url, username)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (pipeline.id, project_id, ref, platform, pipeline.web_url, username))
        conn.commit()
        conn.close()

        return {
            "id": pipeline.id,
            "status": pipeline.status,
            "ref": pipeline.ref,
            "web_url": pipeline.web_url,
        }

    def get_pipeline_status(self, project_id=63, pipeline_id=None):
        project = self.gl.projects.get(project_id)
        pipeline = project.pipelines.get(pipeline_id)
        return {
            "id": pipeline.id,
            "status": pipeline.status,
            "ref": pipeline.ref,
            "web_url": pipeline.web_url,
        }
    
    def get_job_by_name(self, project_id=63, pipeline_id=None, job_name="build_debug_android"):
        project = self.gl.projects.get(project_id)
        pipeline = project.pipelines.get(pipeline_id)
        jobs = pipeline.jobs.list()
        for job in jobs:
            if job.name == job_name:
                return job
        return None
    
    def download_and_extract_artifact(self, project_id, job_id, artifact_path_in_zip, output_filename):
        """
        Download job artifacts as ZIP and extract specific file (APK or IPA).
        
        Args:
            project_id: GitLab project ID
            job_id: GitLab job ID
            artifact_path_in_zip: Path to file inside the ZIP (e.g., 'build/app/outputs/flutter-apk/app-debug.apk')
            output_filename: Final filename to save (e.g., '12345_android.apk')
        
        Returns:
            Path to the extracted file
        """
        project = self.gl.projects.get(project_id)
        job = project.jobs.get(job_id)
        
        os.makedirs(ARTIFACTS_DIR, exist_ok=True)
        
        # Download full artifact ZIP to temporary location
        temp_zip = os.path.join(ARTIFACTS_DIR, f"temp_{job_id}.zip")
        final_path = os.path.join(ARTIFACTS_DIR, output_filename)
        
        try:
            # Download the full artifact ZIP
            with open(temp_zip, "wb") as f:
                job.artifacts(streamed=True, action=f.write)
            
            # Extract specific file from ZIP
            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                # Check if the file exists in the archive
                if artifact_path_in_zip not in zip_ref.namelist():
                    raise FileNotFoundError(f"File {artifact_path_in_zip} not found in artifact ZIP")
                
                # Extract the specific file
                with zip_ref.open(artifact_path_in_zip) as source:
                    with open(final_path, 'wb') as target:
                        shutil.copyfileobj(source, target)
            
            # Update artifact path in DB (for builds table)
            pipeline_id = job.pipeline['id']
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE builds SET artifact_path = ? WHERE pipeline_id = ?
            ''', (final_path, pipeline_id))
            conn.commit()
            conn.close()
            
            return final_path
            
        finally:
            # Clean up temporary ZIP file
            if os.path.exists(temp_zip):
                os.remove(temp_zip)

    def download_and_unzip_ios_app(self, project_id, job_id, artifact_path_in_zip, output_dir_name):
        """
        Download job artifacts ZIP and extract the iOS Runner.app directory.

        Args:
            project_id: GitLab project ID
            job_id: GitLab job ID
            artifact_path_in_zip: Path to Runner.app directory inside the job artifact
            output_dir_name: Directory name to create under ARTIFACTS_DIR (e.g., '12345.app')

        Returns:
            Path to the unzipped .app directory
        """
        project = self.gl.projects.get(project_id)
        job = project.jobs.get(job_id)

        os.makedirs(ARTIFACTS_DIR, exist_ok=True)

        temp_zip = os.path.join(ARTIFACTS_DIR, f"temp_{job_id}.zip")
        final_dir = os.path.join(ARTIFACTS_DIR, output_dir_name)

        try:
            # Download the full artifact ZIP
            with open(temp_zip, "wb") as f:
                job.artifacts(streamed=True, action=f.write)

            # Extract the directory from the ZIP
            if os.path.exists(final_dir):
                shutil.rmtree(final_dir)
            os.makedirs(final_dir, exist_ok=True)

            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                # Filter files that start with artifact_path_in_zip
                prefix = artifact_path_in_zip.rstrip('/') + '/'
                found = False
                for member in zip_ref.namelist():
                    if member.startswith(prefix):
                        found = True
                        # Remove the prefix to extract into final_dir
                        relative_path = member[len(prefix):]
                        if not relative_path:
                            continue
                        
                        target_path = os.path.join(final_dir, relative_path)
                        
                        # Handle directories
                        if member.endswith('/'):
                            os.makedirs(target_path, exist_ok=True)
                        else:
                            os.makedirs(os.path.dirname(target_path), exist_ok=True)
                            with zip_ref.open(member) as source, open(target_path, "wb") as target:
                                shutil.copyfileobj(source, target)
                
                if not found:
                    raise FileNotFoundError(f"Directory {artifact_path_in_zip} not found in artifact ZIP")

            # Update artifact path in DB (for builds table)
            pipeline_id = job.pipeline['id']
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE builds SET artifact_path = ? WHERE pipeline_id = ?
            ''', (final_dir, pipeline_id))
            conn.commit()
            conn.close()

            return final_dir
        finally:
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
    
    def download_job_artifact_generic(self, project_id, job_id, username):
        """
        Download full job artifact ZIP (for generic use).
        """
        project = self.gl.projects.get(project_id)
        job = project.jobs.get(job_id)
        
        # Create a unique filename
        artifact_name = f"{project.name}_{job.ref}_{job.id}.zip"
        artifact_path = os.path.join(ARTIFACTS_DIR, artifact_name)
        
        os.makedirs(ARTIFACTS_DIR, exist_ok=True)

        # Download and save the artifact
        with open(artifact_path, "wb") as f:
            job.artifacts(streamed=True, action=f.write)
            
        # Store in DB
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO artifacts (job_id, project_id, username, file_path, downloaded_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (job_id, project_id, username, artifact_path))
        conn.commit()
        conn.close()

        return artifact_path
    
    def get_pipeline_jobs(self, project_id, pipeline_id):
        project = self.gl.projects.get(project_id)
        pipeline = project.pipelines.get(pipeline_id)
        jobs = pipeline.jobs.list()
        return [{"id": job.id, "name": job.name, "status": job.status} for job in jobs]
    
    def list_builds(self, username=None):
        conn = get_connection()
        cursor = conn.cursor()
        if username:
            cursor.execute("SELECT * FROM builds WHERE username = ? ORDER BY created_at DESC", (username,))
        else:
            cursor.execute("SELECT * FROM builds ORDER BY created_at DESC")
        
        builds = cursor.fetchall()
        conn.close()
        return [dict(row) for row in builds]