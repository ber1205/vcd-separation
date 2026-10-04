import runpod, os, subprocess, time, requests

MAX_MEDIA_BYTES = int(os.environ.get("MAX_MEDIA_BYTES", str(4 * 1024 * 1024 * 1024)))
MODEL_NAME = os.environ.get("MODEL_NAME", "vocals_mel_band_roformer.ckpt")
MODEL_FILE_DIR = os.environ.get("MODEL_FILE_DIR", "/app/models")

R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.environ.get("R2_BUCKET", "")


def _s3_client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def _download(url: str, dst: str) -> int:
    total = 0
    with requests.get(url, stream=True, timeout=(20, 600)) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                total += len(chunk)
                if total > MAX_MEDIA_BYTES:
                    raise ValueError(f"media exceeds MAX_MEDIA_BYTES ({MAX_MEDIA_BYTES})")
                f.write(chunk)
    if total < 1024:
        raise ValueError(f"downloaded too small ({total}B)")
    return total


def _ffmpeg(args: list, label: str = "ffmpeg") -> None:
    p = subprocess.run(["ffmpeg", "-y", *args], capture_output=True, text=True)
    if p.returncode != 0:
        tail = (p.stderr or "")[-300:].replace(chr(10), " | ")
        raise RuntimeError(f"{label} exit {p.returncode}: {tail}")


def _separate(audio_path: str, out_dir: str):
    from audio_separator.separator import Separator
    sep = Separator(model_file_dir=MODEL_FILE_DIR, output_dir=out_dir)
    sep.load_model(model_filename=MODEL_NAME)
    files = sep.separate(audio_path)
    vocal = bgm = None
    for f in files:
        low = f.lower()
        if ("no_vocals" in low or "instrumental" in low or "accompaniment" in low or "off_vocal" in low or "bgm" in low or "(other)" in low) and not bgm:
            bgm = os.path.join(out_dir, f)
        elif "vocal" in low and not vocal:
            vocal = os.path.join(out_dir, f)
    if not vocal:
        raise RuntimeError(f"separation produced no vocal stem: {files}")
    return vocal, bgm, files


def handler(job):
    t0 = time.time()
    inp = (job or {}).get("input") or {}
    job_id = str(inp.get("jobId") or "unknown")
    video_url = inp.get("videoUrl") or ""
    vocal_key = inp.get("vocalKey") or ""
    bgm_key = inp.get("bgmKey") or ""
    work = f"/tmp/work/{job_id}"
    try:
        if not video_url or not vocal_key:
            return {"ok": False, "error": "missing videoUrl/vocalKey", "jobId": job_id}
        os.makedirs(work + "/out", exist_ok=True)
        src = f"{work}/src.bin"
        size = _download(video_url, src)
        audio = f"{work}/audio_24k.wav"
        _ffmpeg(["-i", src, "-vn", "-ac", "1", "-ar", "24000", audio], "extract-audio")
        vocal, bgm, sep_files = _separate(audio, work + "/out")
        v24 = f"{work}/vocal_24k.wav"
        _ffmpeg(["-i", vocal, "-ac", "1", "-ar", "24000", v24], "resample-vocal")
        s3 = _s3_client()
        vocal_bytes = os.path.getsize(v24)
        s3.upload_file(v24, R2_BUCKET, vocal_key, ExtraArgs={"ContentType": "audio/wav"})
        bgm_bytes = 0
        if bgm and bgm_key:
            b24 = f"{work}/bgm_24k.wav"
            _ffmpeg(["-i", bgm, "-ac", "1", "-ar", "24000", b24], "resample-bgm")
            bgm_bytes = os.path.getsize(b24)
            s3.upload_file(b24, R2_BUCKET, bgm_key, ExtraArgs={"ContentType": "audio/wav"})
        took = int((time.time() - t0) * 1000)
        return {
            "ok": True, "jobId": job_id,
            "vocalKey": vocal_key,
            "bgmKey": bgm_key if (bgm and bgm_key) else None,
            "vocalBytes": vocal_bytes, "bgmBytes": bgm_bytes,
            "mediaBytes": size, "tookMs": took, "sepFiles": sep_files,
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:500], "jobId": job_id}
    finally:
        subprocess.run(["rm", "-rf", work])


runpod.serverless.start({"handler": handler})
