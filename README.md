# Discord Music Bot Setup Guide

## Installation

### 1. Install Dependencies
```bash
pip install -r requirement.txt
```

### 2. Configure Environment Variables

Create a `.env` file in your project root with:

```env
DISCORD_TOKEN=...
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
```

## Getting Credentials

### Discord Bot Token
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application"
3. Go to "Bot" tab → "Add Bot"
4. Copy the token and paste in `.env`

### Spotify API Credentials
1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Log in or create account
3. Create a new application
4. Accept the terms and create
5. Copy **Client ID** and **Client Secret**
6. Paste both in `.env`

## Bot Permissions

Enable these permissions in Discord Developer Portal:
- `Send Messages`
- `Send Messages in Threads`
- `Connect` (Voice)
- `Speak` (Voice)
- `Use Slash Commands`

## Commands

### Music Commands
- `/play <song_query> [source]` - Play or queue a song (default: YouTube)
  - Examples: `/play never gonna give you up`
  - `/play never gonna give you up source:spotify`
  - `/play https://open.spotify.com/track/...`

- `/skip` - Skip current song
- `/pause` - Pause playback
- `/resume` - Resume playback
- `/queue` - View song queue
- `/stop` - Stop playback and leave voice channel

## Features

✅ **YouTube Search** - Automatic YouTube search via yt-dlp
✅ **Spotify Search** - Search Spotify catalog (requires API credentials)
✅ **Queue System** - Multiple songs queued per server
✅ **Auto-Play** - Automatically plays next song when current finishes
✅ **Per-Guild Queues** - Each server has independent music queue
✅ **FFmpeg Streaming** - Stable audio streaming with reconnection

## Troubleshooting

### "Spotify not configured"
- Ensure `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` are in `.env`
- Bot will work with YouTube-only mode if Spotify isn't set

### Audio quality issues
- Ensure FFmpeg is installed: `ffmpeg-python` should handle this
- Check internet connection for buffering

### Bot doesn't connect to voice
- Verify bot has "Connect" and "Speak" permissions
- Check if user is in a voice channel

### Songs won't play
- Try `/skip` to move to next song
- Check bot has permissions in the voice channel

## Notes

- Audio streams are 96kbps or for stability
- Queue persists until bot leaves the voice channel
- Each server has separate music queue
- Bot will auto-disconnect after inactivity (configurable)
