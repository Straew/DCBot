import discord
from discord import app_commands
from discord.ext import commands, tasks
import yt_dlp
import asyncio
import os
import re
import time
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from collections import deque

load_dotenv()

# Song queues per guild
SONG_QUEUES = {}

# Tracks last "activity" timestamp per guild (used for idle auto-leave)
LAST_ACTIVITY = {}

# Initialize Spotify
spotify = None
try:
    client_id = os.getenv('SPOTIFY_CLIENT_ID')
    client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
    if client_id and client_secret:
        auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
        spotify = spotipy.Spotify(auth_manager=auth_manager)
except Exception as e:
    print(f"Warning: Spotify not configured. YouTube only mode. Error: {e}")


# ---------------------------------------------------------------------------
# Helpers: URL detection for playlists
# ---------------------------------------------------------------------------

YOUTUBE_PLAYLIST_RE = re.compile(r"(?:youtube\.com|youtu\.be).*[?&]list=([\w-]+)", re.IGNORECASE)
SPOTIFY_PLAYLIST_RE = re.compile(r"open\.spotify\.com/playlist/([\w]+)", re.IGNORECASE)
SPOTIFY_ALBUM_RE = re.compile(r"open\.spotify\.com/album/([\w]+)", re.IGNORECASE)
SPOTIFY_TRACK_RE = re.compile(r"open\.spotify\.com/track/([\w]+)", re.IGNORECASE)


def is_youtube_playlist(query):
    return bool(YOUTUBE_PLAYLIST_RE.search(query))


def is_spotify_playlist_or_album(query):
    return bool(SPOTIFY_PLAYLIST_RE.search(query) or SPOTIFY_ALBUM_RE.search(query))


def is_spotify_track_link(query):
    return bool(SPOTIFY_TRACK_RE.search(query))


async def search_ytdlp_async(query, ydl_opts):
    """Run yt-dlp in executor to avoid blocking"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _extract(query, ydl_opts))


def _extract(query, ydl_opts):
    """Extract info from YouTube"""
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(query, download=False)


def search_spotify(query):
    """Search for a single song on Spotify and return 'title artist' search term"""
    try:
        if not spotify:
            return None

        results = spotify.search(q=query, type='track', limit=1)
        if results['tracks']['items']:
            track = results['tracks']['items'][0]
            artist = track['artists'][0]['name']
            title = track['name']
            return f"{title} {artist}"
        return None
    except Exception as e:
        print(f"Spotify search error: {e}")
        return None


def get_spotify_playlist_tracks(url):
    """
    Returns a list of 'title artist' search strings for every track in a
    Spotify playlist or album URL. Returns [] if Spotify isn't configured
    or the link can't be resolved.
    """
    if not spotify:
        return []

    try:
        playlist_match = SPOTIFY_PLAYLIST_RE.search(url)
        album_match = SPOTIFY_ALBUM_RE.search(url)

        search_terms = []

        if playlist_match:
            playlist_id = playlist_match.group(1)
            results = spotify.playlist_items(playlist_id, additional_types=['track'])
            items = results['items']
            while results['next']:
                results = spotify.next(results)
                items.extend(results['items'])

            for item in items:
                track = item.get('track')
                if not track:
                    continue
                artist = track['artists'][0]['name']
                title = track['name']
                search_terms.append(f"{title} {artist}")

        elif album_match:
            album_id = album_match.group(1)
            results = spotify.album_tracks(album_id)
            items = results['items']
            while results['next']:
                results = spotify.next(results)
                items.extend(results['items'])

            for track in items:
                artist = track['artists'][0]['name']
                title = track['name']
                search_terms.append(f"{title} {artist}")

        return search_terms

    except Exception as e:
        print(f"Spotify playlist fetch error: {e}")
        return []


def get_queue_for_guild(guild_id):
    """Get or create queue for guild"""
    guild_id_str = str(guild_id)
    if guild_id_str not in SONG_QUEUES:
        SONG_QUEUES[guild_id_str] = deque()
    return SONG_QUEUES[guild_id_str]


def touch_activity(guild_id):
    """Mark this guild as recently active (used to reset the idle timer)"""
    LAST_ACTIVITY[str(guild_id)] = time.time()


class MusicError(Exception):
    """Raised for any user-facing music command failure (no voice channel, nothing playing, etc)."""
    pass


# ---------------------------------------------------------------------------

YDL_FORMAT_OPTIONS = {
    "format": "bestaudio[abr<=48000]/bestaudio",
    "noplaylist": True,
    "youtube_include_dash_manifest": False,
    "youtube_include_hls_manifest": False,
    "socket_timeout": 30,
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",

    "options": "-vn -b:a 160k -ar 48000",
}


async def play_next_song(voice_client, guild_id, channel, bot, retry_count=0):
    """Play next song in queue"""
    queue = get_queue_for_guild(guild_id)

    if not queue or not voice_client or not voice_client.is_connected():
        return

    if retry_count >= 3:
        await channel.send("❌ Too many songs failed in a row, stopping.")
        return

    audio_url, title = queue.popleft()

    try:
        source = discord.FFmpegPCMAudio(audio_url, **FFMPEG_OPTIONS)

        def after_play(error):
            if error:
                print(f"Error playing {title}: {error}")

            touch_activity(guild_id)
            asyncio.run_coroutine_threadsafe(
                play_next_song(voice_client, guild_id, channel, bot),
                bot.loop
            )

        voice_client.play(source, after=after_play)
        touch_activity(guild_id)

        embed = discord.Embed(title="Now Playing 🎵", description=title, color=discord.Color.green())
        embed.set_footer(text=f"Queue: {len(queue)} songs remaining")
        await channel.send(embed=embed)

    except Exception as e:
        print(f"Error playing song: {e}")
        await play_next_song(voice_client, guild_id, channel, bot, retry_count + 1)


async def resolve_track(query, source="youtube"):
    """
    Resolves a single search term (not a playlist) into (audio_url, title).
    Raises MusicError if nothing is found.
    """
    search_query = query
    if source.lower() == "spotify" and not is_spotify_track_link(query):
        spotify_result = search_spotify(query)
        if spotify_result:
            search_query = spotify_result

    ytdlp_query = "ytsearch1:" + search_query
    results = await search_ytdlp_async(ytdlp_query, YDL_FORMAT_OPTIONS)
    tracks = results.get("entries", [])

    if not tracks:
        raise MusicError(f"❌ No results found for: {query}")

    first_track = tracks[0]
    return first_track["url"], first_track.get("title", "Untitled")


# ---------------------------------------------------------------------------
# CORE LOGIC — shared between slash commands and prefix (!) commands.
# ---------------------------------------------------------------------------

async def ensure_voice_connection(guild, author_voice_state):
    """Connects to (or moves to) the author's voice channel. Returns the voice_client."""
    if author_voice_state is None or author_voice_state.channel is None:
        raise MusicError("❌ You must be in a voice channel.")

    voice_channel = author_voice_state.channel
    voice_client = guild.voice_client

    if voice_client is None:
        try:
            voice_client = await voice_channel.connect()
        except Exception as e:
            raise MusicError(f"❌ Couldn't join voice channel: {str(e)}")
    elif voice_channel != voice_client.channel:
        await voice_client.move_to(voice_channel)

    return voice_client


async def core_join(guild, author_voice_state):
    """Handles /join and !join — connect without playing anything."""
    await ensure_voice_connection(guild, author_voice_state)
    touch_activity(guild.id)
    return "👋 Joined the voice channel!"


async def core_play(bot, guild, channel, author_voice_state, song_query, source="youtube"):
    """
    Handles the full /play and !play flow, including playlist expansion.
    Returns a tuple: (message_text_or_None, embed_or_None, is_now_playing: bool)
    Raises MusicError on any expected failure.
    """
    voice_client = await ensure_voice_connection(guild, author_voice_state)
    guild_id = str(guild.id)
    queue = get_queue_for_guild(guild_id)
    touch_activity(guild.id)

    try:
        # --- Playlist detection ---
        if is_youtube_playlist(song_query):
            return await _queue_youtube_playlist(bot, voice_client, guild_id, channel, queue, song_query)

        if is_spotify_playlist_or_album(song_query):
            return await _queue_spotify_playlist(bot, voice_client, guild_id, channel, queue, song_query)

        # --- Single track ---
        audio_url, title = await resolve_track(song_query, source)
        queue.append((audio_url, title))

        if voice_client.is_playing() or voice_client.is_paused():
            embed = discord.Embed(title="Added to Queue ✅", description=title, color=discord.Color.blue())
            embed.set_footer(text=f"Position: {len(queue)}")
            return None, embed, False
        else:
            await play_next_song(voice_client, guild_id, channel, bot)
            return f"Now playing: **{title}**", None, True

    except MusicError:
        raise
    except Exception as e:
        raise MusicError(f"❌ Error playing song: {str(e)}")


async def _queue_youtube_playlist(bot, voice_client, guild_id, channel, queue, playlist_url):
    """Expands a YouTube playlist URL into individual tracks and queues them all."""
    ydl_options = dict(YDL_FORMAT_OPTIONS)
    ydl_options["noplaylist"] = False
    ydl_options["extract_flat"] = "in_playlist"  # fast metadata-only pass first

    results = await search_ytdlp_async(playlist_url, ydl_options)
    entries = results.get("entries", [])

    if not entries:
        raise MusicError("❌ Couldn't find any tracks in that playlist.")

    was_idle = not (voice_client.is_playing() or voice_client.is_paused())
    added = 0
    failed = 0

    for entry in entries:
        if entry is None:
            failed += 1
            continue
        video_url = entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id')}"
        try:
            audio_url, title = await resolve_track(video_url, "youtube")
            queue.append((audio_url, title))
            added += 1
        except Exception:
            failed += 1

    embed = discord.Embed(
        title="Playlist Queued 📀",
        description=f"Added **{added}** songs to the queue.",
        color=discord.Color.purple()
    )
    if failed:
        embed.set_footer(text=f"{failed} track(s) couldn't be added.")

    if was_idle and queue:
        await channel.send(embed=embed)
        await play_next_song(voice_client, guild_id, channel, bot)
        return None, None, True

    return None, embed, False


async def _queue_spotify_playlist(bot, voice_client, guild_id, channel, queue, playlist_url):
    """Expands a Spotify playlist/album URL into individual tracks and queues them all."""
    search_terms = get_spotify_playlist_tracks(playlist_url)

    if not search_terms:
        raise MusicError("❌ Couldn't read that Spotify playlist (check it's public, and Spotify credentials are set).")

    was_idle = not (voice_client.is_playing() or voice_client.is_paused())
    added = 0
    failed = 0

    for term in search_terms:
        try:
            audio_url, title = await resolve_track(term, "youtube")
            queue.append((audio_url, title))
            added += 1
        except Exception:
            failed += 1

    embed = discord.Embed(
        title="Spotify Playlist Queued 📀",
        description=f"Added **{added}** songs to the queue.",
        color=discord.Color.green()
    )
    if failed:
        embed.set_footer(text=f"{failed} track(s) couldn't be found on YouTube.")

    if was_idle and queue:
        await channel.send(embed=embed)
        await play_next_song(voice_client, guild_id, channel, bot)
        return None, None, True

    return None, embed, False


def core_skip(guild):
    voice_client = guild.voice_client
    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        voice_client.stop()
        touch_activity(guild.id)
        return "⏭️ Skipped the current song."
    raise MusicError("❌ Nothing is playing to skip.")


def core_pause(guild):
    voice_client = guild.voice_client
    if voice_client is None:
        raise MusicError("❌ I'm not in a voice channel.")
    if not voice_client.is_playing():
        raise MusicError("❌ Nothing is currently playing.")
    voice_client.pause()
    return "⏸️ Playback paused!"


def core_resume(guild):
    voice_client = guild.voice_client
    if voice_client is None:
        raise MusicError("❌ I'm not in a voice channel.")
    if not voice_client.is_paused():
        raise MusicError("❌ I'm not paused right now.")
    voice_client.resume()
    touch_activity(guild.id)
    return "▶️ Playback resumed!"


async def core_stop(guild):
    voice_client = guild.voice_client
    if not voice_client or not voice_client.is_connected():
        raise MusicError("❌ I'm not connected to any voice channel.")

    guild_id_str = str(guild.id)
    if guild_id_str in SONG_QUEUES:
        SONG_QUEUES[guild_id_str].clear()

    if voice_client.is_playing() or voice_client.is_paused():
        voice_client.stop()

    await voice_client.disconnect()
    LAST_ACTIVITY.pop(guild_id_str, None)
    return "⏹️ Stopped playback and disconnected!"


def core_show_queue(guild_id):
    queue = get_queue_for_guild(guild_id)

    if not queue:
        return discord.Embed(title="Queue 📋", description="The queue is empty!", color=discord.Color.blue())

    queue_list = "\n".join([f"**{i+1}.** {song[1][:60]}" for i, song in enumerate(list(queue)[:10])])
    embed = discord.Embed(title="Queue 📋", description=queue_list, color=discord.Color.blue())
    if len(queue) > 10:
        embed.set_footer(text=f"... and {len(queue) - 10} more")
    return embed


# ---------------------------------------------------------------------------
# Idle auto-leave background task
# ---------------------------------------------------------------------------

IDLE_TIMEOUT_SECONDS = 5 * 60  # 5 minutes


def setup_idle_checker(bot):
    @tasks.loop(seconds=60)
    async def idle_checker():
        for guild in bot.guilds:
            voice_client = guild.voice_client
            if not voice_client or not voice_client.is_connected():
                continue

            guild_id_str = str(guild.id)

            # Alone in the channel (just the bot) -> leave immediately
            non_bot_members = [m for m in voice_client.channel.members if not m.bot]
            if not non_bot_members:
                await voice_client.disconnect()
                LAST_ACTIVITY.pop(guild_id_str, None)
                continue

            # Idle (not playing/paused) for too long -> leave
            if not voice_client.is_playing() and not voice_client.is_paused():
                last_active = LAST_ACTIVITY.get(guild_id_str, time.time())
                if time.time() - last_active > IDLE_TIMEOUT_SECONDS:
                    await voice_client.disconnect()
                    LAST_ACTIVITY.pop(guild_id_str, None)

    async def start_once():
        # on_ready can fire more than once (e.g. after a reconnect), so guard
        # against starting the loop twice.
        if not idle_checker.is_running():
            idle_checker.start()

    bot.add_listener(start_once, "on_ready")
    return idle_checker


# ---------------------------------------------------------------------------
# WIRING — slash commands + prefix commands, both calling the core_* funcs
# ---------------------------------------------------------------------------

def setup_music_commands(bot):

    setup_idle_checker(bot)

    # ---------- /join and !join ----------

    @bot.tree.command(name="join", description="Join your current voice channel")
    async def join(interaction: discord.Interaction):
        try:
            msg = await core_join(interaction.guild, interaction.user.voice)
            await interaction.response.send_message(msg)
        except MusicError as e:
            await interaction.response.send_message(str(e))

    @bot.command(name="join")
    async def join_prefix(ctx):
        try:
            msg = await core_join(ctx.guild, ctx.author.voice)
            await ctx.send(msg)
        except MusicError as e:
            await ctx.send(str(e))

    # ---------- /play and !play ----------

    @bot.tree.command(name="play", description="Play a song or playlist from YouTube or Spotify")
    @app_commands.describe(
        song_query="Search query, song link, or playlist link",
        source="youtube or spotify (default: youtube)"
    )
    async def play(interaction: discord.Interaction, song_query: str, source: str = "youtube"):
        await interaction.response.defer()
        try:
            text, embed, _ = await core_play(
                bot, interaction.guild, interaction.channel,
                interaction.user.voice, song_query, source
            )
            if embed:
                await interaction.followup.send(embed=embed)
            elif text:
                await interaction.followup.send(text)
        except MusicError as e:
            await interaction.followup.send(str(e))

    @bot.command(name="play")
    async def play_prefix(ctx, *, song_query: str):
        try:
            text, embed, _ = await core_play(
                bot, ctx.guild, ctx.channel,
                ctx.author.voice, song_query, "youtube"
            )
            if embed:
                await ctx.send(embed=embed)
            elif text:
                await ctx.send(text)
        except MusicError as e:
            await ctx.send(str(e))

    # ---------- !playspotify (convenience prefix wrapper) ----------

    @bot.command(name="playspotify")
    async def play_spotify_prefix(ctx, *, song_query: str):
        try:
            text, embed, _ = await core_play(
                bot, ctx.guild, ctx.channel,
                ctx.author.voice, song_query, "spotify"
            )
            if embed:
                await ctx.send(embed=embed)
            elif text:
                await ctx.send(text)
        except MusicError as e:
            await ctx.send(str(e))

    # ---------- /skip and !skip ----------

    @bot.tree.command(name="skip", description="Skip the current song")
    async def skip(interaction: discord.Interaction):
        try:
            await interaction.response.send_message(core_skip(interaction.guild))
        except MusicError as e:
            await interaction.response.send_message(str(e))

    @bot.command(name="skip")
    async def skip_prefix(ctx):
        try:
            await ctx.send(core_skip(ctx.guild))
        except MusicError as e:
            await ctx.send(str(e))

    # ---------- /pause and !pause ----------

    @bot.tree.command(name="pause", description="Pause the current song")
    async def pause(interaction: discord.Interaction):
        try:
            await interaction.response.send_message(core_pause(interaction.guild))
        except MusicError as e:
            await interaction.response.send_message(str(e))

    @bot.command(name="pause")
    async def pause_prefix(ctx):
        try:
            await ctx.send(core_pause(ctx.guild))
        except MusicError as e:
            await ctx.send(str(e))

    # ---------- /resume and !resume ----------

    @bot.tree.command(name="resume", description="Resume the paused song")
    async def resume(interaction: discord.Interaction):
        try:
            await interaction.response.send_message(core_resume(interaction.guild))
        except MusicError as e:
            await interaction.response.send_message(str(e))

    @bot.command(name="resume")
    async def resume_prefix(ctx):
        try:
            await ctx.send(core_resume(ctx.guild))
        except MusicError as e:
            await ctx.send(str(e))

    # ---------- /stop and !stop ----------

    @bot.tree.command(name="stop", description="Stop playback and clear queue")
    async def stop(interaction: discord.Interaction):
        try:
            await interaction.response.send_message(await core_stop(interaction.guild))
        except MusicError as e:
            await interaction.response.send_message(str(e))

    @bot.command(name="stop")
    async def stop_prefix(ctx):
        try:
            await ctx.send(await core_stop(ctx.guild))
        except MusicError as e:
            await ctx.send(str(e))

    # ---------- /queue and !queue ----------

    @bot.tree.command(name="queue", description="Show the current queue")
    async def show_queue(interaction: discord.Interaction):
        await interaction.response.send_message(embed=core_show_queue(interaction.guild_id))

    @bot.command(name="queue")
    async def show_queue_prefix(ctx):
        await ctx.send(embed=core_show_queue(ctx.guild.id))