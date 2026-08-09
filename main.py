import os
import re
import asyncio
import logging
import tempfile
import shutil
import threading

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


DEVELOPER_USERNAME = os.getenv(
    "DEVELOPER_USERNAME",
    "superraiz07"
).strip()


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
# FILE SIZE
# ============================================================

MAX_FILE_SIZE_MB = 49

MAX_FILE_SIZE_BYTES = (
    MAX_FILE_SIZE_MB
    * 1024
    * 1024
)


# ============================================================
# DOWNLOAD DIRECTORY
# ============================================================

DOWNLOAD_DIR = Path(
    "/tmp/mm_video_downloads"
)

DOWNLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True
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
# URL HELPERS
# ============================================================

def get_platform(url: str):

    try:

        parsed = urlparse(url)

        host = parsed.netloc.lower()

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


# ============================================================
# FILENAME
# ============================================================

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
            Path(
                YOUTUBE_COOKIES_FILE
            )
        )

    candidates.extend(
        [
            Path("/etc/secrets/cookies.txt"),
            Path("cookies.txt"),
        ]
    )

    checked = set()

    for path in candidates:

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

                logger.info(
                    "YouTube cookies found: %s",
                    path
                )

                return str(path)

        except Exception as error:

            logger.warning(
                "Cookie check error: %s",
                error
            )

    logger.warning(
        "YouTube cookies file not found."
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

        "js_runtimes": {
            "deno": {}
        },
    }


# ============================================================
# YOUTUBE OPTIONS
# ============================================================

def youtube_ydl_options(
    download=False
):

    options = base_ydl_options()

    cookie_file = get_cookie_file()

    if cookie_file:

        options["cookiefile"] = (
            cookie_file
        )

        logger.info(
            "YouTube cookies enabled."
        )

    else:

        logger.warning(
            "YouTube cookies unavailable."
        )

    if YOUTUBE_USER_AGENT:

        options["http_headers"] = {
            "User-Agent":
                YOUTUBE_USER_AGENT
        }

    if download:

        options["continuedl"] = True

        options["overwrites"] = True

    return options


# ============================================================
# TIKTOK OPTIONS
# ============================================================

def tiktok_ydl_options(
    download=False
):

    options = base_ydl_options()

    if download:

        options["continuedl"] = True

        options["overwrites"] = True

    return options


# ============================================================
# VIDEO INFO
# ============================================================

def get_video_info_sync(
    url: str
):

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

            "format":
                "bestaudio/best",

            "outtmpl":
                output_template,

            "postprocessors": [
                {
                    "key":
                        "FFmpegExtractAudio",

                    "preferredcodec":
                        "mp3",

                    "preferredquality":
                        "192",
                }
            ],
        })


    # ========================================================
    # VIDEO
    # ========================================================

    else:

        try:

            height = int(
                quality
            )

        except ValueError:

            raise ValueError(
                "Invalid video quality."
            )

        format_string = (
            f"bestvideo[height<={height}]"
            f"+bestaudio/"
            f"best[height<={height}]/"
            f"best"
        )

        options.update({

            "format":
                format_string,

            "outtmpl":
                output_template,

            "merge_output_format":
                "mp4",
        })


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
                ".mkv"
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


        if file_size > MAX_FILE_SIZE_BYTES:

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
        "• 🎵 MP3\n\n"

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
                url=(
                    f"https://t.me/"
                    f"{username}"
                )
            )

        ]

    ]


    await query.edit_message_text(
        text=text,
        reply_markup=(
            InlineKeyboardMarkup(
                keyboard
            )
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

    url = url.split()[0]


    if not is_supported_url(url):

        await message.reply_text(
            "❌ ဒီ Link ကို support မလုပ်ပါဘူး။\n\n"
            "YouTube သို့မဟုတ် TikTok Link ပဲ ပို့ပေးပါ။"
        )

        return


    platform = get_platform(url)


    status_message = (
        await message.reply_text(
            "🔎 Video Information ရှာနေပါတယ်...\n\n"
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

            duration_text = "Unknown"


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

            "👇 <b>Download Quality ရွေးပါ</b>"
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

        error_text = str(error)


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
        "⏳ ခဏစောင့်ပေးပါ..."

        ,
        parse_mode="HTML"
    )
