"""FastAPI 同源 Web 服务；仅面向回环地址上的单用户。"""
from contextlib import asynccontextmanager
import json
from pathlib import Path
import tempfile

import cv2
from fastapi import FastAPI, UploadFile, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from cv_engine.config import PipelineConfig
from .jobs import Jobs, ROOT


def create_app(root=ROOT, execute=None):
    root = Path(root)

    @asynccontextmanager
    async def lifespan(app):
        app.state.jobs = Jobs(root, execute)
        yield
        app.state.jobs.close()

    app = FastAPI(title='板书拾记', lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        origin = request.headers.get('origin')
        if request.method not in ('GET', 'HEAD') and origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': '拒绝跨站请求'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        return response

    def job(job_id):
        try:
            return app.state.jobs.get(job_id)
        except KeyError:
            raise HTTPException(404, '任务不存在')

    def manifest(job_id):
        job(job_id)
        path = root / 'runs' / job_id / 'manifest.json'
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding='utf-8'))

    @app.get('/api/health')
    def health():
        return {'status': 'ok'}

    @app.get('/api/jobs')
    def listing():
        return app.state.jobs.all()

    @app.post('/api/jobs', status_code=201)
    def create(video: UploadFile, config: str = Form('{}')):
        suffix = Path(video.filename or '').suffix.lower()
        if suffix not in {'.mp4', '.mov', '.mkv', '.avi', '.webm'}:
            raise HTTPException(422, '请选择 MP4 / MOV / MKV / AVI / WebM 视频')
        try:
            settings = PipelineConfig(**json.loads(config)).validate()
            if settings.max_frames > 300:
                raise ValueError('本地单次任务最多采样 300 帧')
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc))
        upload_dir = root / 'data' / 'jobs'
        upload_dir.mkdir(parents=True, exist_ok=True)
        path = None
        try:
            with tempfile.NamedTemporaryFile(dir=upload_dir, suffix=suffix, delete=False) as stream:
                path = Path(stream.name)
                size = 0
                while block := video.file.read(1024 * 1024):
                    size += len(block)
                    if size > 2 * 1024**3:
                        raise HTTPException(413, '视频不得超过 2 GiB')
                    stream.write(block)
            cap = cv2.VideoCapture(str(path))
            try:
                ok, frame = cap.read()
                fps = cap.get(cv2.CAP_PROP_FPS)
                count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            finally:
                cap.release()
            if not ok or fps <= 0 or count <= 0:
                raise HTTPException(422, '视频无法解码')
            if settings.start_s >= count / fps:
                raise HTTPException(422, '处理起点超出视频时长')
            h, w = frame.shape[:2]
            if settings.roi is not None:
                roi = settings.roi
                if len(roi) != 4 or any(type(v) is not int for v in roi):
                    raise HTTPException(422, 'ROI 须为四个整数')
                x, y, rw, rh = roi
                if min(x, y) < 0 or min(rw, rh) <= 0 or x + rw > w or y + rh > h:
                    raise HTTPException(422, '白板选区超出视频范围')
            identifier = app.state.jobs.create(path, Path(video.filename).name, settings.to_dict())
            return {'job_id': identifier, 'run_id': identifier}
        finally:
            video.file.close()
            if path is not None:
                path.unlink(missing_ok=True)

    @app.get('/api/jobs/{job_id}')
    def detail(job_id: str):
        data = job(job_id)
        data.pop('video')
        data['manifest'] = manifest(job_id)
        return data

    @app.get('/api/jobs/{job_id}/video')
    def video_file(job_id: str):
        return FileResponse(root / job(job_id)['video'])

    @app.get('/api/runs/{job_id}/manifest')
    def get_manifest(job_id: str):
        return manifest(job_id)

    @app.get('/api/runs/{job_id}/files/{path:path}')
    def artifact(job_id: str, path: str, download: bool = False):
        data = manifest(job_id)
        allowed = {entry['path'] for entry in (data or {}).get('files', [])}
        directory = (root / 'runs' / job_id).resolve()
        target = (directory / path).resolve()
        if path not in allowed or not target.is_relative_to(directory) or not target.is_file():
            raise HTTPException(404, '产物不存在')
        return FileResponse(target, filename=target.name if download else None)

    app.mount('/', StaticFiles(directory=ROOT / 'web', html=True), name='web')
    return app


app = create_app()
