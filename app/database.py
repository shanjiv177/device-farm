import sqlite3

DB_PATH = "device_manager.db"

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS emulators (
            avd_name TEXT PRIMARY KEY,
            serial TEXT,
            port INTEGER,
            pid INTEGER
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            access_token TEXT,
            refresh_token TEXT,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS builds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            ref TEXT NOT NULL,
            platform TEXT,
            web_url TEXT,
            artifact_path TEXT,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            username TEXT,
            file_path TEXT NOT NULL,
            downloaded_at TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def get_token_from_session(session_id: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT access_token FROM sessions WHERE session_id = ?', (session_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return row["access_token"]
    return None
