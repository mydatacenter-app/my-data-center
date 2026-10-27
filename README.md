# My Data Center

A desktop app that pools the computers in your house into one AI cluster. A model too big for any single PC gets split across all of them, and you chat with it right in the app.

Windows + macOS. Everything stays on your own network.

## What's in the app

| Page | What you do there |
|---|---|
| **Overview** | Live CPU/RAM/GPU graphs, response speed (tokens/sec), pooled memory, and start/stop the cluster |
| **Chat** | Talk to your model. Conversations are saved; every reply shows its speed |
| **Computers** | Every computer on your network with live usage. Turn sharing on/off for this one |
| **Models** | One-click downloads of recommended models, or paste any `.gguf` link |
| **Settings** | Performance mode, computer name, AI engine, logs |

**Performance modes** (also in the sidebar, per computer):
- **Eco** — ~25% of CPU cores, low priority. Computer stays usable.
- **Balanced** — 50% of cores, normal priority.
- **Max** — every core, high priority. For a dedicated machine.

## Download

Get it from the download page — one button, picks Windows or Mac automatically:
**https://OWNER.github.io/my-data-center/**

Windows: run `MyDataCenter-Setup.exe`. Mac: open the `.dmg` and drag the app into Applications.

## For developers

Every push to `main` builds the Windows installer and Mac disk images in GitHub Actions, publishes them as the latest release, and updates the download page (`site/`). To run from source: `dev/Start My Data Center (Windows).bat` or `dev/Start My Data Center (Mac).command`.

## First run

1. **Settings → Install engine** on every computer (downloads llama.cpp, ~30–80 MB).
2. On helper computers: **Computers → Share** on. It stays on next launch.
3. On the main computer: **Models** → download one.
4. **Overview** → tick the helper computers → **Start cluster** → **Open chat**.
5. When Windows Firewall asks, allow **Private networks**.

## Tips

- **Wired Ethernet** makes the first model load far faster. Later loads use a cache on each helper.
- **Same engine version everywhere.** A mismatch shows a warning; hit "Check for update" on each.
- **Computer not showing up?** Add it by IP on the Computers page (some routers block discovery).
- Pooling lets you run **bigger** models. It won't make small ones faster.
- Closing the window stops this computer's sharing. For an always-on helper, run `mydatacenter.py --headless`.

## Security

Shared computers accept work from any device on your local network (llama.cpp's RPC has no password). Only use it on a home network you trust, and never forward ports 8800–8802 or 50052 on your router. Controls only work from each computer's own app.

## Files

Everything lives in `MyDataCenter` in your user folder: `engine/`, `models/`, `chats.json`, `config.json`, `.venv/`. Delete it to fully reset.

Ports: 8800 app, 8801 discovery (UDP), 8802 model server (local only), 50052 sharing.
