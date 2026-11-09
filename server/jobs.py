"""本地单用户任务队列；SQLite 仅存元数据，算法在独立进程中执行。"""
import json
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


class Jobs:
    def __init__(self, root=ROOT, execute=None):
        self.root = Path(root)
        self.data = self.root / 'data' / 'jobs'
        self.data.mkdir(parents=True, exist_ok=True)
        self.db = self.data / 'jobs.sqlite3'
        self.execute = execute or self.run
        self.queue = queue.Queue()
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, title TEXT, created TEXT, status TEXT, error TEXT, config TEXT, video TEXT)')
            db.execute("UPDATE jobs SET status='failed', error='服务上次退出时任务未完成，请重新提交' WHERE status IN ('queued','running')")
        self.thread = threading.Thread(target=self.work, daemon=True)
        self.thread.start()

    def connect(self):
        db = sqlite3.connect(self.db)
        db.row_factory = sqlite3.Row
        return db

    def get(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        result = dict(row)
        result['config'] = json.loads(result['config'])
        return result

    def all(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,title,created,status,error FROM jobs ORDER BY created DESC')]

    def create(self, path, title, config):
        job_id = uuid.uuid4().hex
        directory = self.data / job_id
        directory.mkdir()
        video = directory / ('video' + path.suffix.lower())
        path.replace(video)
        (directory / 'config.json').write_text(json.dumps(config), encoding='utf-8')
        with self.connect() as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)', (job_id, title, datetime.now(timezone.utc).isoformat(), 'queued', '', json.dumps(config), str(video.relative_to(self.root))))
        self.queue.put(job_id)
        return job_id

    def update(self, job_id, status, error=''):
        with self.connect() as db:
            db.execute('UPDATE jobs SET status=?,error=? WHERE id=?', (status, error, job_id))

    def run(self, job):
        directory = self.data / job['id']
        with (directory / 'worker.log').open('w') as log:
            process = subprocess.run([sys.executable, '-m', 'cv_engine', '--video', str(self.root / job['video']), '--config', str(directory / 'config.json'), '--run-id', job['id']], cwd=self.root, stdout=log, stderr=subprocess.STDOUT)
        if process.returncode:
            lines = (directory / 'worker.log').read_text(errors='replace').splitlines()
            raise RuntimeError('\n'.join(lines[-8:]) or '算法进程异常退出')

    def work(self):
        while True:
            job_id = self.queue.get()
            try:
                if job_id is None:
                    return
                self.update(job_id, 'running')
                self.execute(self.get(job_id))
                self.update(job_id, 'done')
            except Exception as exc:
                self.update(job_id, 'failed', str(exc))
            finally:
                self.queue.task_done()

    def close(self):
        self.queue.put(None)
        self.thread.join()
