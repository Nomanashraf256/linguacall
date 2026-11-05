# LinguaCall — Cloudflare Pages + Oracle Always Free (experimental)

This repository contains a real WebRTC peer-to-peer video calling frontend, FastAPI signaling server, segment-based Faster-Whisper transcription, NLLB translation and eSpeak NG voice synthesis. **It is NOT verified as production-ready**. Do not promise continuous simultaneous interpretation, unlimited users or a working Urdu voice until tested.

**Architecture:** Cloudflare Pages serves `web/`; Oracle Ubuntu ARM64 VM runs `ai-server/` behind Caddy HTTPS; WebSocket signaling and POST `/api/process` share the same origin. The web app uses `VITE_API_URL` at build time. No paid translation APIs.

## Oracle setup
1. Create an Oracle Cloud Free Tier account (valid payment card generally required for verification). Use **Always Free Eligible** VM.Standard.A1.Flex, Ubuntu ARM64. As of late 2026 Oracle docs list **2 OCPU and 12 GB RAM total**, subject to availability; pick 2 OCPU, 12 GB RAM and an Always Free eligible boot volume within your account's allowance. Never choose a paid shape or upgrade to PAYG.
2. Create/download SSH private key; assign a public IPv4 address. Allow inbound TCP 22 from YOUR IP only and TCP 80/443 from the internet in Oracle VCN security list or NSG; Ubuntu firewall must also allow these. Do not expose port 8000.
3. SSH: `ssh -i YOUR_KEY ubuntu@YOUR_PUBLIC_IP` (on Windows use PowerShell).
4. Install system packages: `sudo apt update && sudo apt install -y git python3-venv python3-pip ffmpeg espeak-ng curl`.
5. `sudo mkdir -p /opt/linguacall && sudo chown ubuntu:ubuntu /opt/linguacall`
6. `git clone https://github.com/YOUR_USERNAME/linguacall.git /opt/linguacall` (for private repos use GitHub SSH deploy key or short-lived fine-grained token; never embed token in URL or committed files).
7. `cd /opt/linguacall/ai-server && python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -r requirements.txt`. On ARM64 confirm wheels are available; large packages/models may take considerable memory and disk.
8. `cp .env.example .env` then edit `ALLOWED_ORIGINS` to include the EXACT Cloudflare Pages URL. Use `WHISPER_MODEL=tiny` initially. Models download from Hugging Face on first launch.
9. `sudo cp /opt/linguacall/deploy/linguacall.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now linguacall && sudo journalctl -u linguacall -f`. Model loading can take minutes; verify `curl http://127.0.0.1:8000/api/health`.
10. Install Caddy following official Ubuntu apt repository instructions: https://caddyserver.com/docs/install#debian-ubuntu-raspbian ; edit `/etc/caddy/Caddyfile` to contain `YOUR_PUBLIC_IP.sslip.io { reverse_proxy 127.0.0.1:8000 }`, then `sudo systemctl reload caddy`. Test `https://YOUR_PUBLIC_IP.sslip.io/api/health`. The sslip.io hostname resolves to your public IP and allows automated HTTPS certificates if DNS, ports, and CA rate limits permit. For production use your own domain.

## Cloudflare Pages setup
1. In Cloudflare Pages, connect private GitHub repo. Set root directory `web`, build command `npm run build`, output `dist`.
2. Set environment variable `VITE_API_URL=https://YOUR_PUBLIC_IP.sslip.io` (no trailing slash) in Production and Preview as appropriate; redeploy when changed.
3. Set server `.env` `ALLOWED_ORIGINS=https://YOUR-PROJECT.pages.dev,http://localhost:5173`, then `sudo systemctl restart linguacall`.
4. Open your Pages URL on two phones, select different languages, share room link. Grant camera/mic access and click Enable audio. Test on same Wi-Fi, then on cellular networks.

## Critical limitations
- Oracle currently lists 2 OCPU/12 GB Always Free A1 allocation; ARM availability varies. Model CPU inference can be slow. `faster-whisper` and PyTorch ARM64 wheels must be verified on the selected Ubuntu version.
- eSpeak NG may not include a usable Urdu voice. Check `espeak-ng --voices | grep -E 'ur|tr'`. If Urdu voice unavailable, translated captions still work but voice synthesis must be replaced with a verified Urdu TTS model. No fallback to fake or wrong-language voice.
- WebRTC uses public STUN only. Calls across some NATs/firewalls require TURN; an Always Free VM can run coturn but consumes bandwidth and requires extra firewall configuration. Without TURN, some real-world calls will fail.
- Segment length is about 4.5 seconds plus processing; not low-latency simultaneous translation. The remote original audio is intentionally muted in the frontend, so the experience depends on translated audio availability.
- Rooms are in-memory, there is no persistent login or rate limiting, and the backend is not hardened for arbitrary public traffic. Restrict to trusted testers until authenticated invitations, abuse prevention, size/time limits, monitoring, and production TURN are added.
- Oracle may require a credit/debit card for identity verification, reclaim idle instances, and show out-of-capacity errors. Cloudflare Pages has usage limits. **No unlimited free guarantee.**

## Troubleshooting
`sudo systemctl status linguacall`; `sudo journalctl -u linguacall -n 100 --no-pager`; `curl http://127.0.0.1:8000/api/health`; `sudo systemctl status caddy`; browser developer console and network tab.

## Local frontend
`cd web && npm install && npm run dev`. Set `VITE_API_URL` to your reachable backend HTTPS address.
