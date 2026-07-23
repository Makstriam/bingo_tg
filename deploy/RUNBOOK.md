# Runbook: reviving the bot if it goes down

Quick reference for operating the bot on the Oracle Cloud server.

## Connect

```powershell
ssh -i "C:\Users\Maksim\Downloads\ssh-key-2026-07-23.key" opc@92.5.124.135
```

If the IP address ever changes (e.g. after stopping/starting the instance),
get the new one from the OCI console: **Compute → Instances → bingo-bot →
Public IP Address**.

## Check if the bot is running

```bash
sudo systemctl status bingo-bot
```

Look for `Active: active (running)`. Press `q` to exit the status view.

## View logs

```bash
journalctl -u bingo-bot -f
```

Shows live logs (Ctrl+C to stop watching). Drop `-f` to just see recent
history instead of following it.

## Restart the bot

```bash
sudo systemctl restart bingo-bot
```

Safe to run any time — systemd stops the old process and starts a fresh one.

## Stop / start manually

```bash
sudo systemctl stop bingo-bot
sudo systemctl start bingo-bot
```

## Update the code after making changes locally

On your own machine: commit and `git push` as usual. Then on the server:

```bash
cd ~/bingo
git pull
source .venv/bin/activate
pip install -r requirements.txt   # only needed if requirements.txt changed
sudo systemctl restart bingo-bot
```

## Common problems

**Bot doesn't respond in Telegram, but `systemctl status` shows it running**
- Check the logs (`journalctl -u bingo-bot -n 100`) for errors.
- Make sure no other copy of the bot is running elsewhere (e.g. on your own
  PC) with the same token — Telegram only allows one active poller per bot
  token; a second one causes `TelegramConflictError`.

**`systemctl status` shows `Active: failed`**
- Check `journalctl -u bingo-bot -n 50` for the actual exception.
- Common cause: `.env` missing or `BOT_TOKEN` empty/wrong — check with
  `cat ~/bingo/.env` (don't paste the token anywhere public).
- After fixing, `sudo systemctl restart bingo-bot`.

**Server feels slow / commands hang**
- Check memory and swap: `free -h`.
- Check disk space: `df -h`.
- Check what's using CPU/memory: `top`.
- If genuinely stuck (not just slow), reboot from the OCI console:
  **Compute → Instances → bingo-bot → Actions → Reboot** (or **Reset** for a
  hard power-cycle if Reboot doesn't help).

**Server unreachable via SSH entirely**
- Try from a fresh terminal window first (rules out a stuck local session).
- If that also hangs, reboot/reset the instance from the OCI console (see
  above). The bot restarts automatically after boot since the service is
  enabled (`systemctl enable`).

**Ran out of disk space (`df -h` shows 100% on `/`)**
- Very unlikely at this project's scale (SQLite data is a few KB per game),
  but if it happens: `sudo dnf clean all` frees cached package downloads,
  and `journalctl --vacuum-time=7d` trims old logs.

**Need to rotate the bot token** (e.g. it leaked)
1. Get a new token from [@BotFather](https://t.me/BotFather) with
   `/revoke` then `/token`, or `/newbot` for a fresh bot.
2. `nano ~/bingo/.env`, update `BOT_TOKEN`, save (Ctrl+O, Enter, Ctrl+X).
3. `sudo systemctl restart bingo-bot`.

## Adding a second, separate bot on the same server

1. Create a new folder, e.g. `~/other-bot`, clone/copy its code there.
2. Set up its own venv and `.env` inside that folder — completely
   independent from this bot's.
3. Copy `deploy/bingo-bot.service` to `/etc/systemd/system/other-bot.service`,
   edit `WorkingDirectory` and `ExecStart` to point at the new folder, and
   pick a different service name.
4. `sudo systemctl daemon-reload && sudo systemctl enable --now other-bot`.

The 1 GB (498 MB usable) RAM + swap on this shape comfortably fits a couple
of small aiogram bots like this one.
