import os
import re
import asyncio
import logging
import tempfile
import shutil
import threading
import sqlite3
import time

from pathlib import Path
from urllib.parse import urlparse
from html import escape
from http.server import HTTPServer, BaseHTTPRequestHandler

from dotenv import load_dotenv
import yt_dlp

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.constants import ChatAction

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    ""
).strip()


# ============================================================
# DEVELOPER
# ============================================================

DEVELOPER_USERNAME = os.getenv(
    "DEVELOPER_USERNAME",
    "superraizo7"
).strip().lstrip("@")


# ============================================================
# YOUTUBE COOKIES
# ============================================================

YOUTUBE_COOKIES_FILE = os.getenv(
    "YOUTUBE_COOKIES_FILE",
    "/etc/secrets/cookies.txt"
).strip()


YOUTUBE_USER_AGENT = os.getenv(
    "YOUTUBE_USER_AGENT",
    ""
).strip()


# ============================================================
# RENDER PORT
# ============================================================

PORT = int(
    os.getenv(
        "PORT",
        "10000"
    )
)


# ============================================================
# TELEGRAM FILE SIZE
# ============================================================

MAX_FILE_SIZE_MB = 49

MAX_FILE_SIZE_BYTES = (
    MAX_FILE_SIZE_MB
    * 1024
    * 1024
)


# ============================================================
# DOWNLOAD STORAGE SETTINGS
#
# Auto cleanup:
#
# 1. Successful downloads are deleted immediately.
# 2. Failed/incomplete files are deleted automatically.
# 3. Files older than 30 minutes are removed.
# 4. If total storage exceeds 400 MB,
#    oldest files are removed.
# ============================================================

DOWNLOAD_DIR = Path(
    "/tmp/mm_video_downloads"
)

DOWNLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True
)


AUTO_CLEANUP_INTERVAL_SECONDS = (
    10 * 60
)


FILE_MAX_AGE_SECONDS = (
    30 * 60
)


MAX_DOWNLOAD_STORAGE_MB = 400

MAX_DOWNLOAD_STORAGE_BYTES = (
    MAX_DOWNLOAD_STORAGE_MB
    * 1024
    * 1024
)


# ============================================================
# SQLITE DATABASE
#
# Render Free filesystem is ephemeral.
# Statistics can reset after restart/redeploy.
#
# This database is very small.
# ============================================================

DATABASE_DIR = Path(
    "/tmp/mm_video_bot"
)

DATABASE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


DATABASE_FILE = (
    DATABASE_DIR
    / "stats.db"
)


DB_LOCK = threading.Lock()


# ============================================================
# RUNTIME COOKIE FILE
# ============================================================

RUNTIME_COOKIE_FILE = Path(
    "/tmp/mm_youtube_cookies.txt"
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format=(
        "%(asctime)s - "
        "%(name)s - "
        "%(levelname)s - "
        "%(message)s"
    ),
    level=logging.INFO,
)


logger = logging.getLogger(
    "MM_Video_Downloader"
)


# ============================================================
# VALIDATION
# ============================================================

if not BOT_TOKEN:

    raise RuntimeError(
        "BOT_TOKEN is missing. "
        "Add BOT_TOKEN to Render Environment Variables."
    )


# ============================================================
# SUPPORTED HOSTS
# ============================================================

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


TIKTOK_HOSTS = {
    "tiktok.com",
    "www.tiktok.com",
    "m.tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
}


# ============================================================
# DATABASE
# ============================================================

def init_database():

    with DB_LOCK:

        connection = sqlite3.connect(
            DATABASE_FILE
        )

        try:

            cursor = connection.cursor()

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                )
                """
            )


            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    quality TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )


            connection.commit()

        finally:

            connection.close()


# ============================================================
# REGISTER USER
# ============================================================

def register_user_sync(
    user
):

    if not user:
        return

    user_id = int(
        user.id
    )

    username = (
        user.username
        or ""
    )

    first_name = (
        user.first_name
        or ""
    )

    last_name = (
        user.last_name
        or ""
    )

    now = time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )


    with DB_LOCK:

        connection = sqlite3.connect(
            DATABASE_FILE
        )

        try:

            connection.execute(
                """
                INSERT INTO users (
                    user_id,
                    username,
                    first_name,
                    last_name,
                    first_seen,
                    last_seen
                )
                VALUES (?, ?, ?, ?, ?, ?)

                ON CONFLICT(user_id)
                DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    last_seen = excluded.last_seen
                """,
                (
                    user_id,
                    username,
                    first_name,
                    last_name,
                    now,
                    now,
                )
            )

            connection.commit()

        finally:

            connection.close()


# ============================================================
# REGISTER DOWNLOAD
# ============================================================

def register_download_sync(
    user_id,
    platform,
    quality
):

    now = time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )


    with DB_LOCK:

        connection = sqlite3.connect(
            DATABASE_FILE
        )

        try:

            connection.execute(
                """
                INSERT INTO downloads (
                    user_id,
                    platform,
                    quality,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    int(user_id),
                    platform,
                    quality,
                    now,
                )
            )

            connection.commit()

        finally:

            connection.close()


# ============================================================
# STATISTICS
# ============================================================

def get_statistics_sync():

    today = time.strftime(
        "%Y-%m-%d"
    )


    with DB_LOCK:

        connection = sqlite3.connect(
            DATABASE_FILE
        )

        try:

            cursor = connection.cursor()


            # Total users

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM users
                """
            )

            total_users = (
                cursor.fetchone()[0]
            )


            # Today active users

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM users
                WHERE last_seen LIKE ?
                """,
                (
                    today + "%",
                )
            )

            today_users = (
                cursor.fetchone()[0]
            )


            # Total downloads

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM downloads
                """
            )

            total_downloads = (
                cursor.fetchone()[0]
            )


            # Today downloads

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM downloads
                WHERE created_at LIKE ?
                """,
                (
                    today + "%",
                )
            )

            today_downloads = (
                cursor.fetchone()[0]
            )


            # YouTube

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM downloads
                WHERE platform = 'youtube'
                """
            )

            youtube_downloads = (
                cursor.fetchone()[0]
            )


            # TikTok

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM downloads
                WHERE platform = 'tiktok'
                """
            )

            tiktok_downloads = (
                cursor.fetchone()[0]
            )


            # Quality statistics

            cursor.execute(
                """
                SELECT quality, COUNT(*)
                FROM downloads
                GROUP BY quality
                ORDER BY COUNT(*) DESC
                """
            )

            quality_rows = (
                cursor.fetchall()
            )


            return {
                "total_users":
                    total_users,

                "today_users":
                    today_users,

                "total_downloads":
                    total_downloads,

                "today_downloads":
                    today_downloads,

                "youtube":
                    youtube_downloads,

                "tiktok":
                    tiktok_downloads,

                "quality":
                    quality_rows,
            }


        finally:

            connection.close()


# ============================================================
# STORAGE SIZE
# ============================================================

def get_download_storage_bytes():

    total_size = 0


    try:

        for path in DOWNLOAD_DIR.rglob("*"):

            try:

                if path.is_file():

                    total_size += (
                        path.stat().st_size
                    )

            except (
                FileNotFoundError,
                PermissionError
            ):

                pass


    except Exception as error:

        logger.warning(
            "Storage size check failed: %s",
            error
        )


    return total_size


# ============================================================
# AUTO CLEANUP
# ============================================================

def cleanup_downloads():

    now = time.time()


    try:

        DOWNLOAD_DIR.mkdir(
            parents=True,
            exist_ok=True
        )


        # ====================================================
        # STEP 1
        # Remove files older than 30 minutes
        # ====================================================

        for path in list(
            DOWNLOAD_DIR.rglob("*")
        ):

            try:

                if not path.is_file():
                    continue


                age = (
                    now
                    - path.stat().st_mtime
                )


                if age > FILE_MAX_AGE_SECONDS:

                    logger.info(
                        "Auto cleanup old file: %s",
                        path
                    )

                    try:

                        path.unlink(
                            missing_ok=True
                        )

                    except Exception as error:

                        logger.warning(
                            "Could not remove file %s: %s",
                            path,
                            error
                        )


            except (
                FileNotFoundError,
                PermissionError
            ):

                continue


        # ====================================================
        # STEP 2
        # Remove empty directories
        # ====================================================

        directories = sorted(
            [
                p
                for p in DOWNLOAD_DIR.rglob("*")
                if p.is_dir()
            ],
            key=lambda p: len(p.parts),
            reverse=True
        )


        for directory in directories:

            try:

                if not any(
                    directory.iterdir()
                ):

                    directory.rmdir()

            except (
                FileNotFoundError,
                OSError
            ):

                pass


        # ====================================================
        # STEP 3
        # Storage limit protection
        # ====================================================

        total_size = (
            get_download_storage_bytes()
        )


        if total_size <= (
            MAX_DOWNLOAD_STORAGE_BYTES
        ):

            return


        logger.warning(
            "Download storage exceeded: %.2f MB",
            total_size / (
                1024 * 1024
            )
        )


        files = []


        for path in DOWNLOAD_DIR.rglob("*"):

            try:

                if path.is_file():

                    files.append(
                        (
                            path.stat().st_mtime,
                            path.stat().st_size,
                            path
                        )
                    )

            except (
                FileNotFoundError,
                PermissionError
            ):

                pass


        files.sort(
            key=lambda item: item[0]
        )


        for (
            modified_time,
            file_size,
            path
        ) in files:

            if total_size <= (
                MAX_DOWNLOAD_STORAGE_BYTES
            ):

                break


            try:

                path.unlink(
                    missing_ok=True
                )


                total_size -= file_size


                logger.info(
                    "Storage cleanup removed: %s",
                    path
                )


            except Exception as error:

                logger.warning(
                    "Storage cleanup failed: %s",
                    error
                )


        # ====================================================
        # Remove empty directories again
        # ====================================================

        directories = sorted(
            [
                p
                for p in DOWNLOAD_DIR.rglob("*")
                if p.is_dir()
            ],
            key=lambda p: len(p.parts),
            reverse=True
        )


        for directory in directories:

            try:

                if not any(
                    directory.iterdir()
                ):

                    directory.rmdir()

            except (
                FileNotFoundError,
                OSError
            ):

                pass


    except Exception as error:

        logger.error(
            "Auto cleanup error: %s",
            error,
            exc_info=True
        )


# ============================================================
# AUTO CLEANUP LOOP
# ============================================================

def cleanup_loop():

    logger.info(
        "Auto cleanup service started."
    )


    while True:

        try:

            cleanup_downloads()

        except Exception as error:

            logger.error(
                "Cleanup loop error: %s",
                error,
                exc_info=True
            )


        time.sleep(
            AUTO_CLEANUP_INTERVAL_SECONDS
        )


# ============================================================
# URL HELPERS
# ============================================================

def get_platform(
    url: str
):

    try:

        parsed = urlparse(
            url
        )

        host = parsed.netloc.lower()

    except Exception:

        return None


    host = host.split(":")[0]


    if (
        host in YOUTUBE_HOSTS
        or host.endswith(
            ".youtube.com"
        )
    ):

        return "youtube"


    if (
        host in TIKTOK_HOSTS
        or host.endswith(
            ".tiktok.com"
        )
    ):

        return "tiktok"


    return None


def is_supported_url(
    url: str
):

    return (
        get_platform(url)
        is not None
    )


# ============================================================
# FILENAME
# ============================================================

def clean_filename(
    name: str
):

    name = re.sub(
        r'[\\/*?:"<>|]',
        "_",
        name
    )


    name = re.sub(
        r"\s+",
        " ",
        name
    ).strip()


    if not name:

        name = "video"


    return name[:150]


# ============================================================
# COOKIE FILE
# ============================================================

def get_cookie_file():

    source_candidates = []


    if YOUTUBE_COOKIES_FILE:

        source_candidates.append(
            Path(
                YOUTUBE_COOKIES_FILE
            )
        )


    source_candidates.extend(
        [
            Path(
                "/etc/secrets/cookies.txt"
            ),

            Path(
                "cookies.txt"
            ),
        ]
    )


    checked = set()

    source_file = None


    for path in source_candidates:

        try:

            path = path.resolve()

        except Exception:

            continue


        if path in checked:

            continue


        checked.add(path)


        try:

            if (
                path.exists()
                and path.is_file()
                and path.stat().st_size > 0
            ):

                source_file = path

                break


        except Exception as error:

            logger.warning(
                "Cookie check error: %s",
                error
            )


    if not source_file:

        logger.warning(
            "YouTube cookies file not found."
        )

        return None


    # ========================================================
    # Existing runtime cookie
    # ========================================================

    try:

        if (
            RUNTIME_COOKIE_FILE.exists()
            and RUNTIME_COOKIE_FILE.is_file()
            and RUNTIME_COOKIE_FILE.stat().st_size > 0
        ):

            return str(
                RUNTIME_COOKIE_FILE
            )


    except Exception:

        pass


    # ========================================================
    # Copy Secret File -> writable /tmp
    # ========================================================

    try:

        shutil.copyfile(
            source_file,
            RUNTIME_COOKIE_FILE
        )


        try:

            os.chmod(
                RUNTIME_COOKIE_FILE,
                0o600
            )

        except Exception:

            pass


        logger.info(
            "YouTube cookies copied to writable file: %s",
            RUNTIME_COOKIE_FILE
        )


        return str(
            RUNTIME_COOKIE_FILE
        )


    except Exception as error:

        logger.error(
            "Failed to copy YouTube cookies: %s",
            error,
            exc_info=True
        )

        return None


# ============================================================
# BASE YT-DLP OPTIONS
# ============================================================

def base_ydl_options():

    return {

        "quiet": True,

        "no_warnings": True,

        "noprogress": True,

        "socket_timeout": 30,

        "retries": 3,

        "fragment_retries": 3,

        "http_chunk_size":
            10 * 1024 * 1024,

        "noplaylist": True,

        "continuedl": True,

        "overwrites": True,

        "ignore_no_formats_error":
            True,
    }


# ============================================================
# YOUTUBE OPTIONS
# ============================================================

def youtube_ydl_options(
    download=False
):

    options = (
        base_ydl_options()
    )


    cookie_file = (
        get_cookie_file()
    )


    if cookie_file:

        options[
            "cookiefile"
        ] = cookie_file


        logger.info(
            "YouTube cookies enabled: %s",
            cookie_file
        )


    else:

        logger.warning(
            "YouTube cookies unavailable."
        )


    if YOUTUBE_USER_AGENT:

        options[
            "http_headers"
        ] = {
            "User-Agent":
                YOUTUBE_USER_AGENT
        }


    if download:

        options[
            "continuedl"
        ] = True

        options[
            "overwrites"
        ] = True


    return options


# ============================================================
# TIKTOK OPTIONS
# ============================================================

def tiktok_ydl_options(
    download=False
):

    options = (
        base_ydl_options()
    )


    if download:

        options[
            "continuedl"
        ] = True

        options[
            "overwrites"
        ] = True


    return options


# ============================================================
# VIDEO INFO
# ============================================================

def get_video_info_sync(
    url: str
):

    platform = (
        get_platform(url)
    )


    if platform == "youtube":

        options = (
            youtube_ydl_options(
                download=False
            )
        )


    elif platform == "tiktok":

        options = (
            tiktok_ydl_options(
                download=False
            )
        )


    else:

        raise ValueError(
            "Unsupported URL"
        )


    with yt_dlp.YoutubeDL(
        options
    ) as ydl:

        return ydl.extract_info(
            url,
            download=False
        )


# ============================================================
# DOWNLOAD
# ============================================================

def download_video_sync(
    url: str,
    quality: str
):

    platform = (
        get_platform(url)
    )


    if platform == "youtube":

        options = (
            youtube_ydl_options(
                download=True
            )
        )


    elif platform == "tiktok":

        options = (
            tiktok_ydl_options(
                download=True
            )
        )


    else:

        raise ValueError(
            "Unsupported URL"
        )


    unique_dir = tempfile.mkdtemp(
        prefix="mm_video_",
        dir=str(
            DOWNLOAD_DIR
        )
    )


    output_template = os.path.join(
        unique_dir,
        "%(title).150s.%(ext)s"
    )


    # ========================================================
    # MP3
    # ========================================================

    if quality == "mp3":

        options.update(
            {

                "format":
                    (
                        "bestaudio[ext=m4a]"
                        "/bestaudio"
                        "/best"
                    ),

                "outtmpl":
                    output_template,

                "postprocessors":
                    [
                        {
                            "key":
                                "FFmpegExtractAudio",

                            "preferredcodec":
                                "mp3",

                            "preferredquality":
                                "192",
                        }
                    ],
            }
        )


    # ========================================================
    # VIDEO
    # ========================================================

    else:

        try:

            height = int(
                quality
            )

        except ValueError:

            shutil.rmtree(
                unique_dir,
                ignore_errors=True
            )


            raise ValueError(
                "Invalid video quality."
            )


        format_string = (

            f"bestvideo"
            f"[height<={height}]"
            f"+bestaudio/"
            f"best"
            f"[height<={height}]/"
            f"best"

        )


        options.update(
            {

                "format":
                    format_string,

                "outtmpl":
                    output_template,

                "merge_output_format":
                    "mp4",

                "postprocessor_args":
                    {
                        "Merger":
                            [
                                "-movflags",
                                "+faststart"
                            ]
                    },
            }
        )


    # ========================================================
    # DOWNLOAD
    # ========================================================

    try:

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )


            requested_title = (
                clean_filename(
                    info.get(
                        "title",
                        "video"
                    )
                )
            )


        files = [

            f

            for f in Path(
                unique_dir
            ).glob("*")

            if (
                f.is_file()
                and f.suffix.lower()
                not in {
                    ".part",
                    ".ytdl"
                }
            )
        ]


        if not files:

            raise RuntimeError(
                "Download completed but "
                "output file was not found."
            )


        preferred = [

            f

            for f in files

            if f.suffix.lower()
            in {
                ".mp4",
                ".mp3",
                ".m4a",
                ".webm",
                ".mkv",
            }
        ]


        if preferred:

            file_path = max(
                preferred,
                key=lambda p:
                    p.stat().st_size
            )

        else:

            file_path = max(
                files,
                key=lambda p:
                    p.stat().st_size
            )


        if not file_path.exists():

            raise RuntimeError(
                "Downloaded file does not exist."
            )


        file_size = (
            file_path.stat().st_size
        )


        logger.info(
            "Downloaded: %s | %.2f MB",
            file_path,
            file_size / (
                1024 * 1024
            )
        )


        if file_size > (
            MAX_FILE_SIZE_BYTES
        ):

            raise RuntimeError(
                "FILE_TOO_LARGE:"
                f"{file_size / (1024 * 1024):.1f}"
            )


        return (
            str(file_path),
            requested_title
        )


    except Exception:

        shutil.rmtree(
            unique_dir,
            ignore_errors=True
        )

        raise


# ============================================================
# CONTACT DEVELOPER BUTTON
# ============================================================

def developer_button():

    return InlineKeyboardButton(
        "👨‍💻 Contact Developer",
        url=(
            f"https://t.me/"
            f"{DEVELOPER_USERNAME}"
        )
    )


# ============================================================
# START KEYBOARD
# ============================================================

def build_start_keyboard():

    keyboard = [

        [
            developer_button()
        ]

    ]


    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return


    await asyncio.to_thread(
        register_user_sync,
        update.effective_user
    )


    text = (

        "👋 မင်္ဂလာပါ!\n\n"

        "🎬 YouTube / TikTok "
        "Video Downloader Bot ဖြစ်ပါတယ်။\n\n"

        "🔗 YouTube သို့မဟုတ် TikTok "
        "Video Link ပို့ပါ။\n\n"

        "📥 ရနိုင်သော Quality များ\n\n"

        "• 240p\n"
        "• 360p\n"
        "• 480p\n"
        "• 720p\n"
        "• 1080p\n"
        "• 🎵 MP3\n\n"

        "👇 Video Link ပို့လိုက်ပါ။"

    )


    await update.message.reply_text(

        text,

        reply_markup=(
            build_start_keyboard()
        )
    )


# ============================================================
# /STATS
# ============================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return


    user = (
        update.effective_user
    )


    await asyncio.to_thread(
        register_user_sync,
        user
    )


    username = (
        user.username
        or ""
    ).lower()


    developer_username = (
        DEVELOPER_USERNAME
        or ""
    ).lower()


    # ========================================================
    # Developer only
    # ========================================================

    if username != developer_username:

        await update.message.reply_text(

            "❌ ဒီ command ကို "
            "Developer သာ အသုံးပြုနိုင်ပါတယ်။"

        )

        return


    statistics = (
        await asyncio.to_thread(
            get_statistics_sync
        )
    )


    total_users = (
        statistics[
            "total_users"
        ]
    )


    today_users = (
        statistics[
            "today_users"
        ]
    )


    total_downloads = (
        statistics[
            "total_downloads"
        ]
    )


    today_downloads = (
        statistics[
            "today_downloads"
        ]
    )


    youtube_downloads = (
        statistics[
            "youtube"
        ]
    )


    tiktok_downloads = (
        statistics[
            "tiktok"
        ]
    )


    quality_rows = (
        statistics[
            "quality"
        ]
    )


    quality_text = ""


    quality_names = {

        "mp3":
            "🎵 MP3",

        "240":
            "240p",

        "360":
            "360p",

        "480":
            "480p",

        "720":
            "720p",

        "1080":
            "1080p",

    }


    for quality, count in quality_rows:

        label = (
            quality_names.get(
                str(quality),
                str(quality)
            )
        )


        quality_text += (
            f"• {label}: "
            f"{count}\n"
        )


    if not quality_text:

        quality_text = (
            "• No downloads yet\n"
        )


    storage_bytes = (
        get_download_storage_bytes()
    )


    storage_mb = (
        storage_bytes
        / (1024 * 1024)
    )


    text = (

        "📊 <b>MM Video Downloader "
        "Statistics</b>\n\n"

        "👥 <b>Users</b>\n"

        f"• Total Users: "
        f"<b>{total_users}</b>\n"

        f"• Active Today: "
        f"<b>{today_users}</b>\n\n"

        "📥 <b>Downloads</b>\n"

        f"• Total Downloads: "
        f"<b>{total_downloads}</b>\n"

        f"• Today Downloads: "
        f"<b>{today_downloads}</b>\n\n"

        "🌐 <b>Platform</b>\n"

        f"• YouTube: "
        f"<b>{youtube_downloads}</b>\n"

        f"• TikTok: "
        f"<b>{tiktok_downloads}</b>\n\n"

        "🎬 <b>Quality</b>\n"

        f"{quality_text}\n"

        "💾 <b>Temporary Storage</b>\n"

        f"• Current: "
        f"<b>{storage_mb:.2f} MB</b>\n"

        f"• Limit: "
        f"<b>{MAX_DOWNLOAD_STORAGE_MB} MB</b>\n\n"

        "🧹 Auto Cleanup: "
        "<b>ON</b>\n"

        "⏱ Cleanup Interval: "
        "<b>10 minutes</b>\n"

        "🗑 File Max Age: "
        "<b>30 minutes</b>"

    )


    await update.message.reply_text(

        text,

        parse_mode="HTML"

    )


# ============================================================
# CONTACT DEVELOPER
# ============================================================

async def contact_developer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = (
        update.callback_query
    )


    if not query:
        return


    await query.answer()


    text = (

        "👨‍💻 <b>Developer</b>\n\n"

        "Telegram: "
        f"@{DEVELOPER_USERNAME}\n\n"

        "Bot Development / Custom Bot "
        "အတွက် Developer ကို "
        "တိုက်ရိုက်ဆက်သွယ်နိုင်ပါတယ်။"

    )


    keyboard = [

        [
            developer_button()
        ]

    ]


    if (
        query.message
        and query.message.photo
    ):

        try:

            await query.edit_message_caption(

                caption=text,

                parse_mode="HTML",

                reply_markup=(
                    InlineKeyboardMarkup(
                        keyboard
                    )
                )
            )


        except Exception as error:

            logger.warning(
                "Photo caption edit failed: %s",
                error
            )


    else:

        try:

            await query.edit_message_text(

                text=text,

                parse_mode="HTML",

                reply_markup=(
                    InlineKeyboardMarkup(
                        keyboard
                    )
                )
            )


        except Exception as error:

            logger.warning(
                "Developer message edit failed: %s",
                error
            )


# ============================================================
# QUALITY KEYBOARD
# ============================================================

def build_quality_keyboard():

    keyboard = [

        [

            InlineKeyboardButton(
                "240p",
                callback_data="download|240"
            ),

            InlineKeyboardButton(
                "360p",
                callback_data="download|360"
            ),

        ],

        [

            InlineKeyboardButton(
                "480p",
                callback_data="download|480"
            ),

            InlineKeyboardButton(
                "720p",
                callback_data="download|720"
            ),

        ],

        [

            InlineKeyboardButton(
                "1080p",
                callback_data="download|1080"
            )

        ],

        [

            InlineKeyboardButton(
                "🎵 MP3",
                callback_data="download|mp3"
            )

        ],

        # ====================================================
        # Separate Contact Developer Button
        # ====================================================

        [

            developer_button()

        ],

    ]


    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# EDIT CALLBACK MESSAGE
# ============================================================

async def edit_callback_message(
    query,
    text,
    parse_mode="HTML",
    reply_markup=None
):

    message = (
        query.message
    )


    # ========================================================
    # PHOTO MESSAGE
    # ========================================================

    if (
        message
        and message.photo
    ):

        try:

            return await query.edit_message_caption(

                caption=text,

                parse_mode=parse_mode,

                reply_markup=reply_markup

            )


        except Exception as error:

            logger.warning(
                "Photo caption edit failed: %s",
                error
            )


            try:

                return await message.reply_text(

                    text=text,

                    parse_mode=parse_mode,

                    reply_markup=reply_markup

                )


            except Exception as fallback_error:

                logger.error(
                    "Fallback message failed: %s",
                    fallback_error
                )


                return None


    # ========================================================
    # TEXT MESSAGE
    # ========================================================

    try:

        return await query.edit_message_text(

            text=text,

            parse_mode=parse_mode,

            reply_markup=reply_markup

        )


    except Exception as error:

        logger.warning(
            "Text edit failed: %s",
            error
        )


        try:

            if message:

                return await message.reply_text(

                    text=text,

                    parse_mode=parse_mode,

                    reply_markup=reply_markup

                )


        except Exception as fallback_error:

            logger.error(
                "Fallback message failed: %s",
                fallback_error
            )


        return None


# ============================================================
# HANDLE URL
# ============================================================

async def handle_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = (
        update.message
    )


    if (
        not message
        or not message.text
    ):

        return


    # ========================================================
    # Register user
    # ========================================================

    await asyncio.to_thread(
        register_user_sync,
        update.effective_user
    )


    url = (
        message.text.strip()
    )


    if not url:
        return


    url = (
        url.split()[0]
    )


    if not is_supported_url(
        url
    ):

        await message.reply_text(

            "❌ ဒီ Link ကို support "
            "မလုပ်ပါဘူး။\n\n"

            "YouTube သို့မဟုတ် TikTok "
            "Link ပဲ ပို့ပေးပါ။"

        )

        return


    platform = (
        get_platform(url)
    )


    status_message = (
        await message.reply_text(

            "🔎 Video Information "
            "ရှာနေပါတယ်...\n\n"

            "⏳ ခဏစောင့်ပေးပါ။"

        )
    )


    try:

        await message.chat.send_action(
            ChatAction.TYPING
        )


        info = await asyncio.to_thread(

            get_video_info_sync,

            url

        )


        title = info.get(
            "title",
            "Unknown"
        )


        duration = info.get(
            "duration"
        )


        thumbnail = info.get(
            "thumbnail"
        )


        if duration:

            minutes = int(
                duration // 60
            )


            seconds = int(
                duration % 60
            )


            duration_text = (
                f"{minutes}:{seconds:02d}"
            )


        else:

            duration_text = (
                "Unknown"
            )


        available_heights = set()


        for fmt in info.get(
            "formats",
            []
        ):

            height = fmt.get(
                "height"
            )


            if height:

                try:

                    available_heights.add(
                        int(height)
                    )

                except (
                    ValueError,
                    TypeError
                ):

                    pass


        quality_lines = []


        for q in [
            240,
            360,
            480,
            720,
            1080,
        ]:

            if any(
                h <= q
                for h in available_heights
            ):

                quality_lines.append(
                    f"✅ {q}p"
                )

            else:

                quality_lines.append(
                    f"❌ {q}p"
                )


        platform_name = (

            "YouTube"

            if platform == "youtube"

            else "TikTok"

        )


        safe_title = escape(
            str(title)[:500]
        )


        text = (

            "🎬 <b>Video Found</b>\n\n"

            f"📌 <b>Title:</b>\n"
            f"{safe_title}\n\n"

            f"🌐 <b>Platform:</b> "
            f"{platform_name}\n"

            f"⏱ <b>Duration:</b> "
            f"{duration_text}\n\n"

            "📊 <b>Available Quality</b>\n"

            + "\n".join(
                quality_lines
            )

            + "\n\n"

            "👇 <b>Download Quality "
            "ရွေးပါ</b>"

        )


        context.user_data[
            "video_url"
        ] = url


        context.user_data[
            "video_title"
        ] = title


        if thumbnail:

            try:

                await message.reply_photo(

                    photo=thumbnail,

                    caption=text,

                    parse_mode="HTML",

                    reply_markup=(
                        build_quality_keyboard()
                    )

                )


                await status_message.delete()

                return


            except Exception as error:

                logger.warning(
                    "Thumbnail send failed: %s",
                    error
                )


        await status_message.edit_text(

            text=text,

            parse_mode="HTML",

            reply_markup=(
                build_quality_keyboard()
            )

        )


    except yt_dlp.utils.DownloadError as error:

        error_text = str(
            error
        )


        logger.error(

            "yt-dlp extraction failed:\n%s",

            error_text,

            exc_info=True

        )


        if (

            "Sign in to confirm"
            in error_text

            or "not a bot"
            in error_text

            or "confirm you're not a bot"
            in error_text

        ):

            await status_message.edit_text(

                "❌ <b>YouTube Access Error</b>\n\n"

                "YouTube က ဒီ server request ကို "
                "bot traffic လို့ သတ်မှတ်ထားပါတယ်။\n\n"

                "🔐 Render Secret File ထဲမှာ "
                "<b>cookies.txt</b> ရှိ/မရှိ စစ်ပါ။\n\n"

                "⚠️ Cookies သက်တမ်းကုန်ခြင်း၊ "
                "YouTube verification သို့မဟုတ် "
                "server-side restriction ဖြစ်နိုင်ပါတယ်။",

                parse_mode="HTML"

            )


        else:

            await status_message.edit_text(

                "❌ Video Information ရယူလို့ "
                "မရပါဘူး။\n\n"

                "ခဏနေပြီး Link တစ်ခုနဲ့ "
                "ထပ်စမ်းကြည့်ပါ။"

            )


    except Exception as error:

        logger.error(

            "Information extraction failed: %s",

            error,

            exc_info=True

        )


        await status_message.edit_text(

            "❌ Video Information ရယူရာမှာ "
            "Error ဖြစ်သွားပါတယ်။\n\n"

            "ခဏနေပြီး ပြန်စမ်းကြည့်ပါ။"

        )


# ============================================================
# DOWNLOAD CALLBACK
# ============================================================

async def download_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = (
        update.callback_query
    )


    if not query:
        return


    await query.answer()


    data = (
        query.data
        or ""
    )


    if not data.startswith(
        "download|"
    ):

        return


    quality = data.split(
        "|",
        1
    )[1]


    url = (
        context.user_data.get(
            "video_url"
        )
    )


    if not url:

        await edit_callback_message(

            query,

            "❌ Download session "
            "မတွေ့တော့ပါဘူး။\n\n"

            "Link ကို ပြန်ပို့ပြီး "
            "ထပ်စမ်းပါ။",

            parse_mode=None

        )

        return


    # ========================================================
    # Prevent duplicate clicks
    # ========================================================

    if context.user_data.get(
        "download_busy"
    ):

        await query.answer(

            "⏳ Download တစ်ခု "
            "လုပ်နေပြီးသားပါ။",

            show_alert=False

        )

        return


    context.user_data[
        "download_busy"
    ] = True


    quality_label = (

        "MP3"

        if quality == "mp3"

        else f"{quality}p"

    )


    file_path = None


    try:

        await edit_callback_message(

            query,

            f"⏳ <b>{quality_label}</b> "
            "Download လုပ်နေပါတယ်...\n\n"

            "📥 Server က file ပြင်ဆင်နေပါတယ်။\n"

            "ခဏစောင့်ပေးပါ။"

        )


        if query.message:

            await query.message.chat.send_action(

                ChatAction.UPLOAD_DOCUMENT

            )


        file_path, title = (
            await asyncio.to_thread(

                download_video_sync,

                url,

                quality

            )
        )


        file_path_obj = Path(
            file_path
        )


        if not file_path_obj.exists():

            raise RuntimeError(
                "Downloaded file not found."
            )


        file_size = (
            file_path_obj.stat().st_size
        )


        logger.info(

            "Sending file: %s | %.2f MB",

            file_path,

            file_size / (
                1024 * 1024
            )

        )


        caption = (

            "✅ <b>Download ပြီးပါပြီ!</b>\n\n"

            f"🎬 <b>"
            f"{escape(str(title)[:500])}"
            f"</b>\n"

            f"📥 Quality: "
            f"<b>{quality_label}</b>\n\n"

            "🤖 MM Video Downloader"

        )


        await query.message.reply_document(

            document=file_path,

            caption=caption,

            parse_mode="HTML"

        )


        # ====================================================
        # Register successful download
        # ====================================================

        await asyncio.to_thread(

            register_download_sync,

            update.effective_user.id,

            get_platform(url),

            quality

        )


        await edit_callback_message(

            query,

            f"✅ <b>{quality_label}</b> "
            "Download ပြီးပါပြီ။\n\n"

            "📤 File ကို အပေါ်မှာ "
            "ပို့ပေးထားပါတယ်။"

        )


    except RuntimeError as error:

        error_text = str(
            error
        )


        logger.error(

            "Download runtime error: %s",

            error_text,

            exc_info=True

        )


        if error_text.startswith(
            "FILE_TOO_LARGE:"
        ):

            size_text = (
                error_text.split(
                    ":",
                    1
                )[1]
            )


            await edit_callback_message(

                query,

                "❌ <b>File Size "
                "ကြီးလွန်းပါတယ်။</b>\n\n"

                f"📦 File Size: "
                f"{size_text} MB\n"

                f"📌 Maximum: "
                f"{MAX_FILE_SIZE_MB} MB\n\n"

                "Quality နိမ့်တဲ့ option "
                "တစ်ခုကို ရွေးပြီး "
                "ထပ်စမ်းကြည့်ပါ။"

            )


        else:

            await edit_callback_message(

                query,

                "❌ Download "
                "မအောင်မြင်ပါဘူး။\n\n"

                "ခဏနေပြီး ပြန်စမ်းကြည့်ပါ။"

            )


    except yt_dlp.utils.DownloadError as error:

        error_text = str(
            error
        )


        logger.error(

            "yt-dlp download failed:\n%s",

            error_text,

            exc_info=True

        )


        if (

            "Sign in to confirm"
            in error_text

            or "not a bot"
            in error_text

            or "confirm you're not a bot"
            in error_text

        ):

            await edit_callback_message(

                query,

                "❌ <b>YouTube Access Error</b>\n\n"

                "YouTube က server request ကို "
                "bot traffic လို့ သတ်မှတ်ထားပါတယ်။\n\n"

                "🔐 cookies.txt ကို Render "
                "Secret File ထဲမှာ မှန်မှန်ထည့်ထားကြောင်း "
                "စစ်ပါ။"

            )


        else:

            await edit_callback_message(

                query,

                "❌ <b>Download Error</b>\n\n"

                "Video ကို download လုပ်လို့ "
                "မရပါဘူး။\n\n"

                "ခဏနေပြီး ပြန်စမ်းကြည့်ပါ။"

            )


    except Exception as error:

        logger.error(

            "Unexpected download error: %s",

            error,

            exc_info=True

        )


        await edit_callback_message(

            query,

            "❌ <b>Download လုပ်ရာမှာ "
            "Error ဖြစ်သွားပါတယ်။</b>\n\n"

            "Quality နိမ့်တဲ့ option တစ်ခုနဲ့ "
            "ထပ်စမ်းကြည့်ပါ။"

        )


    finally:

        # ====================================================
        # IMPORTANT:
        # Delete downloaded directory immediately
        # after sending / error.
        # ====================================================

        try:

            if file_path:

                file_path_obj = Path(
                    file_path
                )


                shutil.rmtree(

                    file_path_obj.parent,

                    ignore_errors=True

                )


        except Exception as cleanup_error:

            logger.warning(

                "Immediate cleanup failed: %s",

                cleanup_error

            )


        context.user_data[
            "download_busy"
        ] = False


# ============================================================
# CALLBACK ROUTER
# ============================================================

async def callback_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = (
        update.callback_query
    )


    if not query:
        return


    # ========================================================
    # Register user
    # ========================================================

    await asyncio.to_thread(

        register_user_sync,

        update.effective_user

    )


    data = (
        query.data
        or ""
    )


    logger.info(
        "Callback received: %s",
        data
    )


    if data.startswith(
        "download|"
    ):

        await download_callback(

            update,

            context

        )

        return


    if data == "developer":

        await contact_developer(

            update,

            context

        )

        return


    await query.answer()


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(

        "Unhandled exception:",

        exc_info=context.error

    )


# ============================================================
# HEALTH CHECK SERVER
# ============================================================

class HealthHandler(
    BaseHTTPRequestHandler
):

    def do_GET(self):

        self.send_response(
            200
        )


        self.send_header(

            "Content-Type",

            "text/plain; "
            "charset=utf-8"

        )


        self.end_headers()


        self.wfile.write(

            b"MM Video Downloader "
            b"Bot is running."

        )


    def log_message(
        self,
        format,
        *args
    ):

        return


def run_health_server():

    server = HTTPServer(

        (
            "0.0.0.0",
            PORT
        ),

        HealthHandler

    )


    logger.info(

        "Health server running "
        "on port %s",

        PORT

    )


    server.serve_forever()


# ============================================================
# MAIN
# ============================================================

def main():

    # ========================================================
    # Initialize database
    # ========================================================

    try:

        init_database()

        logger.info(
            "Statistics database initialized."
        )

    except Exception as error:

        logger.error(

            "Database initialization failed: %s",

            error,

            exc_info=True

        )

        raise


    # ========================================================
    # Prepare cookies
    # ========================================================

    try:

        cookie_file = (
            get_cookie_file()
        )


        if cookie_file:

            logger.info(

                "Runtime YouTube cookie "
                "file ready: %s",

                cookie_file

            )


    except Exception as error:

        logger.warning(

            "Cookie preparation failed: %s",

            error

        )


    # ========================================================
    # Initial cleanup
    # ========================================================

    try:

        cleanup_downloads()

    except Exception as error:

        logger.warning(

            "Initial cleanup failed: %s",

            error

        )


    # ========================================================
    # Auto cleanup thread
    # ========================================================

    cleanup_thread = threading.Thread(

        target=cleanup_loop,

        daemon=True

    )


    cleanup_thread.start()


    # ========================================================
    # Health server
    # ========================================================

    health_thread = threading.Thread(

        target=run_health_server,

        daemon=True

    )


    health_thread.start()


    # ========================================================
    # Telegram Application
    # ========================================================

    application = (

        Application.builder()

        .token(BOT_TOKEN)

        .build()

    )


    # ========================================================
    # Handlers
    # ========================================================

    application.add_handler(

        CommandHandler(

            "start",

            start

        )

    )


    application.add_handler(

        CommandHandler(

            "stats",

            stats

        )

    )


    application.add_handler(

        MessageHandler(

            filters.TEXT
            & ~filters.COMMAND,

            handle_url

        )

    )


    application.add_handler(

        CallbackQueryHandler(

            callback_router

        )

    )


    application.add_error_handler(

        error_handler

    )


    logger.info(

        "MM Video Downloader Bot "
        "starting..."

    )


    logger.info(

        "Developer: @%s",

        DEVELOPER_USERNAME

    )


    logger.info(

        "Auto cleanup: ON"

    )


    logger.info(

        "Statistics: ON"

    )


    application.run_polling(

        allowed_updates=(
            Update.ALL_TYPES
        )

    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()
