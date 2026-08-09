import os
import re
import asyncio
import logging
import tempfile
import shutil
from pathlib import Path
from urllib.parse import urlparse

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
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

DEVELOPER_USERNAME = os.getenv(
    "DEVELOPER_USERNAME",
    "superraiz07"
).strip()

# Render Secret File
# Example:
# /etc/secrets/cookies.txt
YOUTUBE_COOKIES_FILE = os.getenv(
    "YOUTUBE_COOKIES_FILE",
    "/etc/secrets/cookies.txt"
).strip()

# Optional User-Agent
YOUTUBE_USER_AGENT = os.getenv(
    "YOUTUBE_USER_AGENT",
    ""
).strip()

# Telegram Bot API practical upload limit
MAX_FILE_SIZE_MB = 49
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

DOWNLOAD_DIR = Path("/tmp/mm_video_downloads")
DOWNLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# VALIDATION
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is missing. "
        "Add BOT_TOKEN to Render Environment Variables."
    )


# ============================================================
# URL HELPERS
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
    "vm.tiktok.com",
    "vt.tiktok.com",
}


def get_platform(url: str):

    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return None

    host = host.split(":")[0]

    if (
        host in YOUTUBE_HOSTS
        or host.endswith(".youtube.com")
    ):
        return "youtube"

    if (
        host in TIKTOK_HOSTS
        or host.endswith(".tiktok.com")
    ):
        return "tiktok"

    return None


def is_supported_url(url: str):

    return get_platform(url) is not None


def clean_filename(name: str):

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

    candidates = []

    if YOUTUBE_COOKIES_FILE:
        candidates.append(
            Path(YOUTUBE_COOKIES_FILE)
        )

    candidates.append(
        Path("/etc/secrets/cookies.txt")
    )

    candidates.append(
        Path("cookies.txt")
    )

    for path in candidates:

        try:

            if (
                path.exists()
                and path.is_file()
                and path.stat().st_size > 0
            ):

                logger.info(
                    "YouTube cookies found: %s",
                    path
                )

                return str(path)

        except Exception as e:

            logger.warning(
                "Could not inspect cookie file %s: %s",
                path,
                e
            )

    logger.warning(
        "YouTube cookies file not found."
    )

    return None


# ============================================================
# COMMON YT-DLP OPTIONS
# ============================================================

def base_ydl_options():

    options = {

        # Output
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,

        # Network
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,

        # YouTube recommends keeping chunk size <= 10 MB
        "http_chunk_size": 10 * 1024 * 1024,

        # Single video only
        "noplaylist": True,

        # Certificate
        "nocheckcertificate": True,

        # Continue downloads
        "continuedl": True,

        # Don't overwrite existing files
        "overwrites": True,

        # Use Deno for yt-dlp JS challenges
        "js_runtimes": {
            "deno": {}
        },
    }

    return options


# ============================================================
# YOUTUBE OPTIONS
# ============================================================

def youtube_ydl_options(download=False):

    options = base_ydl_options()

    cookie_file = get_cookie_file()

    if cookie_file:

        options["cookiefile"] = cookie_file

        logger.info(
            "YouTube cookies enabled."
        )

    else:

        logger.warning(
            "No YouTube cookies available."
        )

    # --------------------------------------------------------
    # Optional User-Agent
    # --------------------------------------------------------

    if YOUTUBE_USER_AGENT:

        options["http_headers"] = {
            "User-Agent": YOUTUBE_USER_AGENT
        }

    # --------------------------------------------------------
    # YouTube clients
    #
    # web_safari:
    #   Useful for HLS formats.
    #
    # web_embedded:
    #   Only works for embeddable videos.
    #
    # tv:
    #   Some public videos may work through TV client.
    # --------------------------------------------------------

    options["extractor_args"] = {
        "youtube": {
            "player_client": [
                "web_safari",
                "tv",
                "web_embedded"
            ]
        }
    }

    if download:

        options["continuedl"] = True
        options["overwrites"] = True

    return options


# ============================================================
# TIKTOK OPTIONS
# ============================================================

def tiktok_ydl_options(download=False):

    options = base_ydl_options()

    if download:

        options["continuedl"] = True
        options["overwrites"] = True

    return options


# ============================================================
# VIDEO INFORMATION
# ============================================================

def get_video_info_sync(url: str):

    platform = get_platform(url)

    if platform == "youtube":

        options = youtube_ydl_options(
            download=False
        )

    elif platform == "tiktok":

        options = tiktok_ydl_options(
            download=False
        )

    else:

        raise ValueError(
            "Unsupported URL"
        )

    with yt_dlp.YoutubeDL(options) as ydl:

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

    platform = get_platform(url)

    if platform == "youtube":

        options = youtube_ydl_options(
            download=True
        )

    elif platform == "tiktok":

        options = tiktok_ydl_options(
            download=True
        )

    else:

        raise ValueError(
            "Unsupported URL"
        )

    unique_dir = tempfile.mkdtemp(
        prefix="mm_video_",
        dir=str(DOWNLOAD_DIR)
    )

    output_template = os.path.join(
        unique_dir,
        "%(title).150s.%(ext)s"
    )

    # ========================================================
    # MP3
    # ========================================================

    if quality == "mp3":

        options.update({

            "format": (
                "bestaudio/best"
            ),

            "outtmpl": output_template,

            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        })

    # ========================================================
    # VIDEO
    # ========================================================

    else:

        height = int(quality)

        format_string = (
            f"bestvideo[height<={height}]"
            f"+bestaudio/"
            f"best[height<={height}]/"
            f"best"
        )

        options.update({

            "format": format_string,

            "outtmpl": output_template,

            "merge_output_format": "mp4",
        })

    try:

        with yt_dlp.YoutubeDL(options) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )

            requested_title = clean_filename(
                info.get(
                    "title",
                    "video"
                )
            )

        files = list(
            Path(unique_dir).glob("*")
        )

        files = [
            f
            for f in files
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
                ".mkv"
            }
        ]

        if preferred:

            file_path = max(
                preferred,
                key=lambda p: p.stat().st_size
            )

        else:

            file_path = max(
                files,
                key=lambda p: p.stat().st_size
            )

        if not file_path.exists():

            raise RuntimeError(
                "Downloaded file does not exist."
            )

        file_size = file_path.stat().st_size

        logger.info(
            "Downloaded: %s | %.2f MB",
            file_path,
            file_size / (
                1024 * 1024
            )
        )

        if file_size > MAX_FILE_SIZE_BYTES:

            raise RuntimeError(
                "File is too large for Telegram. "
                f"Size: "
                f"{file_size / (1024 * 1024):.1f} MB"
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
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    text = (
        "👋 မင်္ဂလာပါ!\n\n"

        "🎬 YouTube / TikTok "
        "Video Downloader Bot ဖြစ်ပါတယ်။\n\n"

        "🔗 YouTube သို့မဟုတ် TikTok "
        "Video Link ပို့ပါ။\n\n"

        "📥 ရနိုင်သော Quality များ\n"
        "• 240p\n"
        "• 360p\n"
        "• 480p\n"
        "• 720p\n"
        "• 1080p\n"
        "• MP3\n\n"

        "👇 Video Link ပို့လိုက်ပါ။"
    )

    await update.message.reply_text(
        text
    )


# ============================================================
# CONTACT DEVELOPER
# ============================================================

async def contact_developer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    username = (
        DEVELOPER_USERNAME
        .lstrip("@")
    )

    text = (
        "👨‍💻 Developer ကို ဆက်သွယ်ရန်\n\n"

        f"Telegram: @{username}\n\n"

        "Bot Development / Custom Bot အတွက်\n"
        "Developer ကို တိုက်ရိုက်ဆက်သွယ်နိုင်ပါတယ်။"
    )

    keyboard = [

        [
            InlineKeyboardButton(
                "👨‍💻 Contact Developer",
                url=f"https://t.me/{username}"
            )
        ]

    ]

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
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

        [
            InlineKeyboardButton(
                "👨‍💻 Contact Developer",
                callback_data="developer"
            )
        ],
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# HANDLE URL
# ============================================================

async def handle_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message

    if (
        not message
        or not message.text
    ):
        return

    url = message.text.strip()

    # Take first token only
    url = url.split()[0]

    if not is_supported_url(url):

        await message.reply_text(
            "❌ ဒီ Link ကို support မလုပ်ပါဘူး။\n\n"
            "YouTube သို့မဟုတ် TikTok Link ပဲ ပို့ပေးပါ။"
        )

        return

    platform = get_platform(url)

    status_message = await message.reply_text(
        "🔎 Video Information ရှာနေပါတယ်...\n\n"
        "⏳ ခဏစောင့်ပေးပါ။"
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

        # ====================================================
        # DURATION
        # ====================================================

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

            duration_text = "Unknown"

        # ====================================================
        # AVAILABLE QUALITIES
        # ====================================================

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

                except Exception:

                    pass

        quality_lines = []

        for q in [
            240,
            360,
            480,
            720,
            1080
        ]:

            if any(
                h >= q
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

        text = (
            "🎬 <b>Video Found</b>\n\n"

            f"📌 <b>Title:</b>\n"
            f"{title[:500]}\n\n"

            f"🌐 <b>Platform:</b> "
            f"{platform_name}\n"

            f"⏱ <b>Duration:</b> "
            f"{duration_text}\n\n"

            "📊 <b>Available Quality</b>\n"

            + "\n".join(
                quality_lines
            )

            + "\n\n"

            "👇 <b>Download Quality ရွေးပါ</b>"
        )

        # Save session
        context.user_data[
            "video_url"
        ] = url

        context.user_data[
            "video_title"
        ] = title

        # ====================================================
        # THUMBNAIL
        # ====================================================

        if thumbnail:

            try:

                await message.reply_photo(
                    photo=thumbnail,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=build_quality_keyboard()
                )

                await status_message.delete()

                return

            except Exception as thumbnail_error:

                logger.warning(
                    "Thumbnail send failed: %s",
                    thumbnail_error
                )

        # ====================================================
        # TEXT FALLBACK
        # ====================================================

        await status_message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=build_quality_keyboard()
        )

    except yt_dlp.utils.DownloadError as e:

        error_text = str(e)

        logger.error(
            "yt-dlp information extraction failed:\n%s",
            error_text,
            exc_info=True
        )

        if (
            "Sign in to confirm" in error_text
            or "not a bot" in error_text
            or "confirm you're not a bot"
            in error_text
        ):

            await status_message.edit_text(
                "❌ <b>YouTube Access Error</b>\n\n"

                "YouTube က ဒီ server request ကို "
                "bot traffic လို့ သတ်မှတ်ထားပါတယ်။\n\n"

                "🔐 YouTube cookies မရှိတာ၊ "
                "သက်တမ်းကုန်တာ၊ သို့မဟုတ် "
                "YouTube server-side verification "
                "ဖြစ်နေတာ ဖြစ်နိုင်ပါတယ်။\n\n"

                "⚙️ Render မှာ valid "
                "<b>cookies.txt</b> Secret File "
                "ရှိ/မရှိ စစ်ပေးပါ။",

                parse_mode="HTML"
            )

        else:

            await status_message.edit_text(
                "❌ Video Information ရယူလို့ မရပါဘူး။\n\n"
                "ခဏနေပြီး Link တစ်ခုနဲ့ ထပ်စမ်းကြည့်ပါ။"
            )

    except Exception as e:

        logger.error(
            "Information extraction failed: %s",
            e,
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

    query = update.callback_query

    await query.answer()

    data = query.data

    if not data.startswith(
        "download|"
    ):
        return

    quality = data.split(
        "|",
        1
    )[1]

    url = context.user_data.get(
        "video_url"
    )

    if not url:

        await query.edit_message_text(
            "❌ Download session မတွေ့တော့ပါဘူး။\n\n"
            "Link ကို ပြန်ပို့ပြီး ထပ်စမ်းပါ။"
        )

        return

    quality_label = (
        "MP3"
        if quality == "mp3"
        else f"{quality}p"
    )

    await query.edit_message_text(
        f"⏳ <b>{quality_label}</b> "
        "Download လုပ်နေပါတယ်...\n\n"

        "📥 Server က file ပြင်ဆင်နေပါတယ်။\n"
        "ခဏစောင့်ပေးပါ...",

        parse_mode="HTML"
    )

    file_path = None

    try:

        await context.bot.send_chat_action(
            chat_id=query.message.chat_id,

            action=(
                ChatAction.UPLOAD_VIDEO
                if quality != "mp3"
                else ChatAction.UPLOAD_DOCUMENT
            )
        )

        file_path, title = await asyncio.to_thread(
            download_video_sync,
            url,
            quality
        )

        if (
            not file_path
            or not os.path.exists(file_path)
        ):

            raise RuntimeError(
                "Downloaded file not found."
            )

        file_size = os.path.getsize(
            file_path
        )

        if file_size > MAX_FILE_SIZE_BYTES:

            await query.edit_message_text(
                "❌ File Size အရမ်းကြီးနေပါတယ်။\n\n"

                f"📦 Size: "
                f"{file_size / (1024 * 1024):.1f} MB\n"

                f"⚠️ ဒီ Bot က "
                f"{MAX_FILE_SIZE_MB} MB အထိပဲ "
                "ပို့ပေးပါတယ်။\n\n"

                "အနိမ့် Quality တစ်ခုကို ရွေးပြီး "
                "ထပ်စမ်းကြည့်ပါ။"
            )

            return

        # ====================================================
        # SEND MP3
        # ====================================================

        if quality == "mp3":

            await context.bot.send_chat_action(
                chat_id=query.message.chat_id,
                action=ChatAction.UPLOAD_DOCUMENT
            )

            with open(
                file_path,
                "rb"
            ) as audio_file:

                await context.bot.send_audio(
                    chat_id=query.message.chat_id,
                    audio=audio_file,

                    caption=(
                        f"🎵 <b>{title[:500]}</b>\n\n"
                        "✅ MP3 Download Complete"
                    ),

                    parse_mode="HTML",

                    title=title[:100]
                )

        # ====================================================
        # SEND VIDEO
        # ====================================================

        else:

            await context.bot.send_chat_action(
                chat_id=query.message.chat_id,
                action=ChatAction.UPLOAD_VIDEO
            )

            with open(
                file_path,
                "rb"
            ) as video_file:

                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=video_file,

                    caption=(
                        f"🎬 <b>{title[:500]}</b>\n\n"

                        f"📺 Quality: "
                        f"{quality_label}\n"

                        "✅ Download Complete"
                    ),

                    parse_mode="HTML",

                    supports_streaming=True
                )

        await query.message.delete()

    except yt_dlp.utils.DownloadError as e:

        error_text = str(e)

        logger.error(
            "Download failed:\n%s",
            error_text,
            exc_info=True
        )

        if (
            "Sign in to confirm" in error_text
            or "not a bot" in error_text
            or "confirm you're not a bot"
            in error_text
        ):

            await query.edit_message_text(
                "❌ <b>YouTube Verification Error</b>\n\n"

                "YouTube က ဒီ server ကို "
                "bot traffic လို့ သတ်မှတ်ထားပါတယ်။\n\n"

                "🔐 Valid YouTube cookies ကို "
                "Render Secret File အဖြစ် "
                "ထည့်ထားရပါမယ်။",

                parse_mode="HTML"
            )

        else:

            await query.edit_message_text(
                "❌ Download မအောင်မြင်ပါဘူး။\n\n"

                "အခြား Quality တစ်ခုကို ရွေးပြီး "
                "ထပ်စမ်းကြည့်ပါ။"
            )

    except Exception as e:

        logger.error(
            "Download error: %s",
            e,
            exc_info=True
        )

        await query.edit_message_text(
            "❌ Download မအောင်မြင်ပါဘူး။\n\n"

            "အနိမ့် Quality တစ်ခုကို ရွေးပြီး "
            "ထပ်စမ်းကြည့်ပါ။"
        )

    finally:

        if file_path:

            try:

                parent = Path(
                    file_path
                ).parent

                if parent.exists():

                    shutil.rmtree(
                        parent,
                        ignore_errors=True
                    )

            except Exception as cleanup_error:

                logger.warning(
                    "Cleanup error: %s",
                    cleanup_error
                )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Unhandled exception",
        exc_info=context.error
    )


# ============================================================
# MAIN
# ============================================================

def main():

    logger.info(
        "======================================"
    )

    logger.info(
        "Starting MM Video Downloader Bot..."
    )

    logger.info(
        "yt-dlp version: %s",
        yt_dlp.version.__version__
    )

    logger.info(
        "YouTube cookies path: %s",
        YOUTUBE_COOKIES_FILE
    )

    logger.info(
        "YouTube cookies available: %s",
        bool(get_cookie_file())
    )

    logger.info(
        "======================================"
    )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # /start
    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # Download buttons
    application.add_handler(
        CallbackQueryHandler(
            download_callback,
            pattern=r"^download\|"
        )
    )

    # Developer
    application.add_handler(
        CallbackQueryHandler(
            contact_developer,
            pattern=r"^developer$"
        )
    )

    # URL messages
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_url
        )
    )

    # Errors
    application.add_error_handler(
        error_handler
    )

    logger.info(
        "Bot is starting with polling..."
    )

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()
