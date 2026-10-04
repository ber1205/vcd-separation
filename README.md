# vcd-separation

RunPod serverless worker: vocal/BGM separation (Mel-Band-Roformer) for the VCD pipeline fallback channel.

Contract: POST input `{ jobId, videoUrl, vocalKey, bgmKey, mode: "v2" }` → downloads video, extracts 24kHz mono audio, separates (audio-separator), writes stems directly to Cloudflare R2 (S3 API), returns `{ ok, vocalKey, bgmKey, tookMs }`.

Credentials are injected per-endpoint via env (never baked into the image).
