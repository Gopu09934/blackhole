# Black Hole Live Stream

Code-generated black hole visualization that streams live to YouTube via GitHub Actions.

## Files
- `black_hole_sim.py` — renders a static 10s seamless-loop mp4 of the black hole animation
- `stream_live.py` — real-time version: renders frames on the fly with live YouTube chat + real space data (ISS position, near-Earth asteroid count) burned in, streamed directly via ffmpeg/RTMP
- `generate_space_ambient.py` — generates a fully synthesized, seamless ambient space-drone soundtrack (no copyrighted audio) used as the stream's background audio
- `.github/workflows/youtube-live.yml` — GitHub Actions workflow that runs stream_live.py and pushes to YouTube Live

## Setup
1. Create a live broadcast in YouTube Studio > Go Live > Stream. Copy the **Stream Key** and **Video ID**.
2. Get a YouTube Data API v3 key at console.cloud.google.com (enable "YouTube Data API v3").
3. (Optional) Get a free NASA API key at api.nasa.gov for higher rate limits.
4. In your GitHub repo: Settings > Secrets and variables > Actions, add:
   - `YOUTUBE_STREAM_KEY`
   - `YOUTUBE_API_KEY`
   - `YOUTUBE_VIDEO_ID`
   - `NASA_API_KEY` (optional)
5. Push this repo, then run the workflow manually (Actions tab > YouTube Live - Black Hole Stream (reactive) > Run workflow) or let the daily cron trigger it.

## Notes
- GitHub Actions jobs cap at 6 hours — this workflow stops at 5h50m to stay under the limit. For true 24/7 streaming, run the same ffmpeg command on a small always-on VPS instead.
- If frames stutter on GitHub's shared runners, lower `FPS` or `WIDTH/HEIGHT` in `stream_live.py`.
- Local test of the static loop: `pip install -r requirements.txt`, then `python black_hole_sim.py`.
