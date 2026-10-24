"""A dependency-free, loopback-only video speed-curve application."""
import argparse
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from curve import audio_commands, output_time, validate, video_expression

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
JOBS = {}
LOCK = threading.RLock()
RENDER_SLOT = threading.Semaphore(1)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def probe(path):
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=NO_WINDOW, timeout=90,
    )
    if result.returncode:
        raise ValueError("영상을 읽을 수 없습니다. MP4·MOV·WebM 등의 영상 파일을 선택해 주세요.")
    info = json.loads(result.stdout)
    video = next((s for s in info.get("streams", [])
                  if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    if not video:
        raise ValueError("영상 트랙이 없는 파일입니다.")
    duration = float(video.get("duration") or info.get("format", {}).get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("영상 길이를 확인할 수 없습니다.")
    try:
        numerator, denominator = map(float, video.get("avg_frame_rate", "30/1").split("/"))
        fps = numerator / denominator
    except (ValueError, ZeroDivisionError):
        fps = 30
    if not math.isfinite(fps) or fps < 1:
        fps = 30
    return {"duration": duration, "width": video["width"], "height": video["height"],
            "fps": min(60.0, fps), "audio": any(s.get("codec_type") == "audio" for s in info["streams"])}


def public_job(job):
    keys = ("id", "name", "duration", "width", "height", "fps", "audio", "status", "progress",
            "error", "expected_duration", "output_name", "output_url", "preview_url")
    return {k: job[k] for k in keys if k in job}


def render(job, settings):
    with RENDER_SLOT:
        if job.get("cancel"):
            job["status"] = "cancelled"
            return
        job["status"] = "rendering"
        folder = job["folder"]
        start, end, easing = settings["start"], settings["end"], settings["easing"]
        duration = job["duration"]
        target = output_time(1, duration, start, end, easing)
        job["expected_duration"] = target
        output = folder / f"result-{uuid.uuid4().hex[:8]}.mp4"
        expr = video_expression(duration, start, end, easing)
        graph = (f"[0:v:0]settb=AVTB,setpts='{expr}',fps={job['fps']:.9f},"
                 "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,format=yuv420p[v]")
        keep_audio = settings["audio"] and job["audio"]
        if keep_audio:
            (folder / "tempo.txt").write_text(audio_commands(duration, start, end, easing), encoding="utf-8")
            stretcher = f"rubberband@curve=tempo={start:.12f}:pitch=1:transients=mixed:window=short"
            graph += (f";[0:a:0]asetpts=PTS-STARTPTS,asendcmd=f=tempo.txt,{stretcher},"
                      f"apad,atrim=duration={target:.12f},asetpts=PTS-STARTPTS[a]")
        (folder / "graph.txt").write_text(graph, encoding="utf-8")
        command = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                   "-i", str(job["source"]), "-filter_complex_script", "graph.txt", "-map", "[v]"]
        if keep_audio:
            command += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
        else:
            command += ["-an"]
        command += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-threads", "4",
                    "-t", f"{target:.12f}", "-movflags", "+faststart", "-progress", "pipe:1",
                    "-nostats", str(output)]
        try:
            with (folder / "render.log").open("w", encoding="utf-8") as errors:
                process = subprocess.Popen(command, cwd=folder, stdout=subprocess.PIPE, stderr=errors,
                                           text=True, encoding="utf-8", creationflags=NO_WINDOW)
                with LOCK:
                    job["process"] = process
                    if job.get("cancel"):
                        process.terminate()
                for line in process.stdout:
                    if line.startswith("out_time_us="):
                        try:
                            job["progress"] = min(.995, max(0, int(line.split("=")[1]) / 1e6 / target))
                        except ValueError:
                            pass
                result = process.wait()
            if job.get("cancel"):
                job["status"] = "cancelled"
                output.unlink(missing_ok=True)
            elif result:
                detail = (folder / "render.log").read_text(encoding="utf-8")[-2500:]
                raise RuntimeError(detail or "FFmpeg 변환 실패")
            else:
                stem = Path(job["name"]).stem
                job.update(status="done", progress=1, output=output,
                           output_name=f"{stem}_{easing}_{start:g}x-{end:g}x.mp4",
                           output_url=f"/api/download/{job['id']}?v={output.stem}",
                           preview_url=f"/api/result/{job['id']}?v={output.stem}")
        except Exception as exc:
            job.update(status="error", error=str(exc))
        finally:
            job.pop("process", None)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        if self.path.startswith("/api/jobs/"):
            return
        super().log_message(format, *args)

    def allowed(self):
        host = self.headers.get("Host", "")
        if host not in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"):
            self.send_json({"error": "로컬 접속만 허용됩니다."}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"):
            self.send_json({"error": "다른 사이트에서는 이 도구를 호출할 수 없습니다."}, 403)
            return False
        return True

    def send_json(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path, download_name=None):
        size = path.stat().st_size
        start, end, partial = 0, size - 1, False
        header = self.headers.get("Range")
        if header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
            if not match:
                self.send_json({"error": "지원하지 않는 범위입니다."}, 416)
                return
            left, right = match.groups()
            if left:
                start, end = int(left), min(int(right) if right else end, end)
            elif right:
                start = max(0, size - int(right))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            partial = True
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download_name:
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(download_name)}")
        self.end_headers()
        try:
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self.allowed():
            return
        route = urlparse(self.path).path
        if route == "/api/health":
            self.send_json({"app": "speed-curve", "ready": bool(FFMPEG and FFPROBE)})
        elif route.startswith("/api/"):
            parts = route.strip("/").split("/")
            if len(parts) != 3 or parts[2] not in JOBS:
                self.send_json({"error": "영상을 다시 선택해 주세요."}, 404)
                return
            job = JOBS[parts[2]]
            if parts[1] == "jobs":
                self.send_json(public_job(job))
            elif parts[1] == "source":
                self.send_file(job["source"])
            elif parts[1] in ("download", "result") and job.get("status") == "done":
                self.send_file(job["output"], job["output_name"] if parts[1] == "download" else None)
            else:
                self.send_json({"error": "결과가 아직 준비되지 않았습니다."}, 404)
        else:
            names = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
            if route not in names:
                self.send_json({"error": "페이지를 찾을 수 없습니다."}, 404)
                return
            self.send_file(ROOT / "web" / names[route])

    def read_json(self):
        size = int(self.headers.get("Content-Length", 0))
        if not 0 < size <= 16384:
            raise ValueError("요청 크기를 확인해 주세요.")
        return json.loads(self.rfile.read(size))

    def do_POST(self):
        if not self.allowed():
            return
        route = urlparse(self.path).path
        try:
            if not FFMPEG or not FFPROBE:
                raise ValueError("FFmpeg를 찾을 수 없습니다. 실행 안내를 확인해 주세요.")
            if route == "/api/upload":
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 8 * 1024 ** 3:
                    raise ValueError("0바이트보다 크고 8GB 이하인 파일을 선택해 주세요.")
                name = parse_qs(urlparse(self.path).query).get("name", ["video.mp4"])[0]
                name = name.replace("\\", "/").split("/")[-1][:200]
                ext = Path(name).suffix.lower()
                if ext not in (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".mts", ".m2ts"):
                    raise ValueError("MP4·MOV·MKV·WebM 등의 영상 파일을 선택해 주세요.")
                identifier = uuid.uuid4().hex
                folder = DATA / identifier
                folder.mkdir()
                source = folder / ("source" + ext)
                with source.open("wb") as stream:
                    remaining = length
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError("파일 전송이 중단되었습니다.")
                        stream.write(chunk)
                        remaining -= len(chunk)
                try:
                    metadata = probe(source)
                except Exception:
                    source.unlink(missing_ok=True)
                    raise
                job = dict(id=identifier, name=name, folder=folder, source=source,
                           status="ready", progress=0, **metadata)
                with LOCK:
                    JOBS[identifier] = job
                self.send_json(public_job(job), 201)
            elif route == "/api/render":
                body = self.read_json()
                start, end, easing = validate(body.get("start"), body.get("end"), body.get("easing"))
                with LOCK:
                    job = JOBS.get(body.get("job_id"))
                    if not job:
                        raise ValueError("영상을 먼저 선택해 주세요.")
                    if job["status"] in ("queued", "rendering"):
                        raise ValueError("이미 내보내는 중입니다.")
                    job.update(status="queued", progress=0, error="", cancel=False,
                               expected_duration=output_time(1, job["duration"], start, end, easing))
                thread = threading.Thread(target=render, args=(job, dict(start=start, end=end, easing=easing,
                                                                         audio=body.get("audio") is True)), daemon=True)
                thread.start()
                self.send_json(public_job(job), 202)
            elif route == "/api/cancel":
                body = self.read_json()
                with LOCK:
                    job = JOBS.get(body.get("job_id"))
                    if not job:
                        raise ValueError("작업을 찾을 수 없습니다.")
                    job["cancel"] = True
                    process = job.get("process")
                    if process and process.poll() is None:
                        process.terminate()
                self.send_json({"ok": True})
            else:
                self.send_json({"error": "지원하지 않는 요청입니다."}, 404)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.close_connection = True
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.close_connection = True
            self.send_json({"error": f"처리 중 오류가 발생했습니다: {exc}"}, 500)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    print(f"Speed Curve: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for job in list(JOBS.values()):
            process = job.get("process")
            if process and process.poll() is None:
                process.terminate()
        server.server_close()
