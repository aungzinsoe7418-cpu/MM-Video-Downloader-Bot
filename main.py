import os
import re
import asyncio
import logging
import tempfile
import shutil
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from dotenv import load_dotenv

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


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

DEVELOPER_USERNAME = os.getenv(
    "DEVELOPER_USERNAME",
    "superraizo7"
).strip().lstrip("@")


# Render Secret File / Environment Variable
YOUTUBE_COOKIES_FILE = os.getenv(
    "YOUTUBE_COOKIES_FILE",
    "/etc/secrets/cookies.txt"
).strip()


MAX_FILE_SIZE_MB = 49
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


DOWNLOAD_DIR = Path("/tmp/mm_video_downloads")

DOWNLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# VALIDATION
# =========================================================

if not BOT_TOKEN:

    raise RuntimeError(
        "BOT_TOKEN is missing. "
        "Please add BOT_TOKEN in Render Environment Variables."
    )


# =========================================================
# SUPPORTED HOSTS
# =========================================================

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


# =========================================================
# URL HELPERS
# =========================================================

def get_platform(url: str):

    try:

        parsed = urlparse(url)

        host = parsed.netloc.lower()

        host = host.split(":")[0]

    except Exception:

        return None


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


# =========================================================
# FILENAME
# =========================================================

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


# =========================================================
# COOKIES
# =========================================================

def get_cookie_file():

    candidates = []


    # 1. Environment variable

    if YOUTUBE_COOKIES_FILE:

        candidates.append(
            Path(YOUTUBE_COOKIES_FILE)
        )


    # 2. Render Secret File

    candidates.append(
        Path("/etc/secrets/cookies.txt")
    )


    # 3. Local development

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
                "Could not check cookie file %s: %s",
                path,
                e
            )


    logger.warning(
        "YouTube cookies file NOT found."
    )

    return None


# =========================================================
# BASE YT-DLP OPTIONS
# =========================================================

def base_ydl_options():

    return {

        "quiet": True,

        "no_warnings": True,

        "noprogress": True,

        "noplaylist": True,

        "nocheckcertificate": True,

        "socket_timeout": 30,

        "retries": 3,

        "fragment_retries": 3,

        "http_chunk_size": 10 * 1024 * 1024,

        "concurrent_fragment_downloads": 4,

    }


# =========================================================
# YOUTUBE OPTIONS
# =========================================================

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
            "YouTube cookies are not available."
        )


    # Modern YouTube extractor configuration.

    options["extractor_args"] = {

        "youtube": {

            "player_client": [
                "web",
                "web_safari",
                "web_embedded"
            ]

        }

    }


    if download:

        options.update({

            "continuedl": True,

            "overwrites": True,

        })


    return options


# =========================================================
# TIKTOK OPTIONS
# =========================================================

def tiktok_ydl_options(download=False):

    options = base_ydl_options()


    if download:

        options.update({

            "continuedl": True,

            "overwrites": True,

        })


    return options


# =========================================================
# GET VIDEO INFO
# =========================================================

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


# =========================================================
# AVAILABLE QUALITY
# =========================================================

def get_available_qualities(info):

    formats = info.get(
        "formats",
        []
    )


    heights = set()


    for fmt in formats:

        height = fmt.get("height")

        vcodec = fmt.get(
            "vcodec"
        )


        if (
            height
            and vcodec
            and vcodec != "none"
        ):

            try:

                heights.add(
                    int(height)
                )

            except Exception:

                pass


    result = {}


    for quality in [
        240,
        360,
        480,
        720,
        1080
    ]:

        result[quality] = any(
            h >= quality
            for h in heights
        )


    return result


# =========================================================
# DOWNLOAD
# =========================================================

def download_media_sync(
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


    temp_dir = tempfile.mkdtemp(
        prefix="mm_video_",
        dir=str(DOWNLOAD_DIR)
    )


    output_template = os.path.join(
        temp_dir,
        "%(title).120s [%(id)s].%(ext)s"
    )


    # =====================================================
    # MP3
    # =====================================================

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


    # =====================================================
    # VIDEO
    # =====================================================

    else:

        height = int(quality)


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


    try:

        with yt_dlp.YoutubeDL(options) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )


        title = clean_filename(
            info.get(
                "title",
                "video"
            )
        )


        files = [

            f

            for f in Path(temp_dir).glob("*")

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
                "Download finished but "
                "output file was not found."
            )


        preferred_extensions = {

            ".mp4",
            ".mp3",
            ".m4a",
            ".webm",
            ".mkv"

        }


        preferred = [

            f

            for f in files

            if f.suffix.lower()
            in preferred_extensions

        ]


        if preferred:

            file_path = max(
                preferred,
                key=lambda f: f.stat().st_size
            )

        else:

            file_path = max(
                files,
                key=lambda f: f.stat().st_size
            )


        if not file_path.exists():

            raise RuntimeError(
                "Downloaded file does not exist."
            )


        size = file_path.stat().st_size


        logger.info(
            "Downloaded %s - %.2f MB",
            file_path,
            size / (1024 * 1024)
        )


        if size > MAX_FILE_SIZE_BYTES:

            raise RuntimeError(
                f"FILE_TOO_LARGE:{size}"
            )


        return str(
            file_path
        ), title


    except Exception:

        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )

        raise


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = (

        "🎬 <b>MM Video Downloader</b>\n\n"

        "YouTube / TikTok Video Downloader\n\n"

        "📥 <b>Supported Quality</b>\n"

        "• 240p\n"
        "• 360p\n"
        "• 480p\n"
        "• 720p\n"
        "• 1080p\n"
        "• 🎵 MP3\n\n"

        "🔗 YouTube သို့မဟုတ် TikTok "
        "Video Link ပို့ပါ။"

    )


    await update.message.reply_text(

        text,

        parse_mode="HTML",

        reply_markup=main_menu()

    )


# =========================================================
# MAIN MENU
# =========================================================

def main_menu():

    keyboard = [

        [

            InlineKeyboardButton(
                "📥 Download Video",
                callback_data="download"
            )

        ],

        [

            InlineKeyboardButton(
                "❓ Help",
                callback_data="help"
            ),

            InlineKeyboardButton(
                "ℹ️ About",
                callback_data="about"
            )

        ],

        [

            InlineKeyboardButton(
                "👨‍💻 Contact Developer",
                url=f"https://t.me/{DEVELOPER_USERNAME}"
            )

        ]

    ]


    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# BUTTON HANDLER
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()


    if query.data == "download":

        await query.message.reply_text(

            "🔗 YouTube သို့မဟုတ် TikTok "
            "Video Link ကို ပို့ပါ။"

        )


    elif query.data == "help":

        await query.message.reply_text(

            "❓ <b>အသုံးပြုနည်း</b>\n\n"

            "1️⃣ YouTube / TikTok Link ပို့ပါ\n"
            "2️⃣ Video Information စစ်ပါမယ်\n"
            "3️⃣ Quality ရွေးပါ\n"
            "4️⃣ Download ပြီးရင် File ပြန်ပို့ပါမယ်။",

            parse_mode="HTML"

        )


    elif query.data == "about":

        await query.message.reply_text(

            "🎬 <b>MM Video Downloader</b>\n\n"

            "YouTube & TikTok Downloader\n\n"

            "⚡ Dynamic Quality Detection\n"
            "📥 Video Downloader\n"
            "🎵 MP3 Downloader\n\n"

            f"👨‍💻 Developer: @{DEVELOPER_USERNAME}",

            parse_mode="HTML"

        )


# =========================================================
# QUALITY KEYBOARD
# =========================================================

def quality_keyboard(
    available
):

    keyboard = []


    row = []


    for quality in [
        240,
        360,
        480,
        720,
        1080
    ]:


        if available.get(
            quality,
            False
        ):

            row.append(

                InlineKeyboardButton(

                    f"✅ {quality}p",

                    callback_data=
                        f"quality|{quality}"

                )

            )

        else:

            row.append(

                InlineKeyboardButton(

                    f"❌ {quality}p",

                    callback_data=
                        "unavailable"

                )

            )


        if len(row) == 2:

            keyboard.append(row)

            row = []


    if row:

        keyboard.append(row)


    keyboard.append([

        InlineKeyboardButton(

            "🎵 MP3",

            callback_data=
                "quality|mp3"

        )

    ])


    keyboard.append([

        InlineKeyboardButton(

            "👨‍💻 Contact Developer",

            url=
                f"https://t.me/{DEVELOPER_USERNAME}"

        )

    ])


    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# HANDLE URL
# =========================================================

async def handle_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if (
        not update.message
        or not update.message.text
    ):

        return


    url = update.message.text.strip()


    # If user pasted text around URL,
    # take the first URL-like token.

    match = re.search(
        r"https?://\S+",
        url
    )


    if match:

        url = match.group(0)

        url = url.rstrip(
            ".,!?)]}"
        )


    if not is_supported_url(url):

        await update.message.reply_text(

            "❌ YouTube သို့မဟုတ် TikTok "
            "Link ပဲ ပို့ပါ။"

        )

        return


    platform = get_platform(url)


    status = await update.message.reply_text(

        "🔎 <b>Video Information "
        "စစ်နေပါတယ်...</b>\n\n"
        "⏳ ခဏစောင့်ပေးပါ။",

        parse_mode="HTML"

    )


    try:

        info = await asyncio.to_thread(

            get_video_info_sync,

            url

        )


        title = info.get(
            "title",
            "Unknown"
        )


        duration = (
            info.get(
                "duration"
            )
            or 0
        )


        minutes = int(
            duration // 60
        )

        seconds = int(
            duration % 60
        )


        available = (
            get_available_qualities(
                info
            )
        )


        context.user_data[
            "video_url"
        ] = url


        context.user_data[
            "video_title"
        ] = title


        quality_status = []


        for quality in [
            240,
            360,
            480,
            720,
            1080
        ]:


            if available.get(
                quality,
                False
            ):

                quality_status.append(
                    f"✅ {quality}p"
                )

            else:

                quality_status.append(
                    f"❌ {quality}p"
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
            f"{minutes}:{seconds:02d}\n\n"

            "📊 <b>Available Quality</b>\n"

            + "\n".join(
                quality_status
            )

            + "\n\n"

            "👇 <b>Download Quality "
            "ရွေးပါ။</b>"

        )


        await status.edit_text(

            text,

            parse_mode="HTML",

            reply_markup=
                quality_keyboard(
                    available
                )

        )


    except yt_dlp.utils.DownloadError as e:

        error_text = str(e)


        logger.error(
            "Information extraction failed: %s",
            error_text,
            exc_info=True
        )


        if (
            "Sign in to confirm" in error_text
            or "not a bot" in error_text
            or "confirm you're not a bot" in error_text
        ):

            await status.edit_text(

                "❌ <b>YouTube Access Error</b>\n\n"

                "YouTube က ဒီ server request ကို "
                "bot traffic လို့ သတ်မှတ်ထားပါတယ်။\n\n"

                "🔐 Render မှာ YouTube "
                "<b>cookies.txt</b> Secret File "
                "ထည့်ထားဖို့လိုပါတယ်။",

                parse_mode="HTML"

            )

        else:

            await status.edit_text(

                "❌ Video Information "
                "ရယူလို့မရပါဘူး။\n\n"
                "Link မှန်/မမှန် ပြန်စစ်ပြီး "
                "ထပ်စမ်းပါ။"

            )


    except Exception as e:

        logger.error(
            "Information extraction failed: %s",
            e,
            exc_info=True
        )


        await status.edit_text(

            "❌ Video Information "
            "ရယူရာမှာ Error ဖြစ်သွားပါတယ်။\n\n"
            "ခဏနေပြီး ပြန်စမ်းပါ။"

        )


# =========================================================
# QUALITY CALLBACK
# =========================================================

async def quality_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()


    if query.data == "unavailable":

        await query.answer(

            "❌ ဒီ Quality မရနိုင်ပါ။",

            show_alert=True

        )

        return


    _, quality = query.data.split(
        "|",
        1
    )


    url = context.user_data.get(
        "video_url"
    )


    if not url:

        await query.edit_message_text(

            "❌ Download session "
            "မတွေ့တော့ပါဘူး။\n\n"
            "Link ကို ပြန်ပို့ပါ။"

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
        "ခဏစောင့်ပေးပါ။",

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


        file_path, title = (
            await asyncio.to_thread(

                download_media_sync,

                url,

                quality

            )
        )


        if not file_path:

            raise RuntimeError(
                "File path is empty."
            )


        if not os.path.exists(
            file_path
        ):

            raise RuntimeError(
                "Downloaded file not found."
            )


        file_size = os.path.getsize(
            file_path
        )


        if (
            file_size
            > MAX_FILE_SIZE_BYTES
        ):

            await query.edit_message_text(

                "❌ File Size အရမ်းကြီးနေပါတယ်။\n\n"

                f"📦 Size: "
                f"{file_size / (1024 * 1024):.1f} MB\n"

                f"⚠️ Bot limit: "
                f"{MAX_FILE_SIZE_MB} MB\n\n"

                "⬇️ Quality နိမ့်တာကို "
                "ရွေးပြီး ထပ်စမ်းပါ။"

            )

            return


        # =================================================
        # MP3
        # =================================================

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


        # =================================================
        # VIDEO
        # =================================================

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


        try:

            await query.message.delete()

        except Exception:

            pass


    except yt_dlp.utils.DownloadError as e:

        error_text = str(e)


        logger.error(
            "Download failed: %s",
            error_text,
            exc_info=True
        )


        if (
            "Sign in to confirm" in error_text
            or "not a bot" in error_text
            or "confirm you're not a bot" in error_text
        ):

            await query.edit_message_text(

                "❌ <b>YouTube Verification Error</b>\n\n"

                "YouTube က server request ကို "
                "bot traffic လို့ သတ်မှတ်ထားပါတယ်။\n\n"

                "🔐 Render Secret File မှာ "
                "<b>cookies.txt</b> ထည့်ထားပြီး "
                "Deploy ပြန်လုပ်ပါ။",

                parse_mode="HTML"

            )

        else:

            await query.edit_message_text(

                "❌ Download မအောင်မြင်ပါဘူး။\n\n"

                "အခြား Quality တစ်ခုကို ရွေးပြီး "
                "ထပ်စမ်းကြည့်ပါ။"

            )


    except Exception as e:

        error_text = str(e)


        logger.error(
            "Download error: %s",
            error_text,
            exc_info=True
        )


        if error_text.startswith(
            "FILE_TOO_LARGE:"
        ):

            await query.edit_message_text(

                "❌ File Size အရမ်းကြီးနေပါတယ်။\n\n"
                "Quality နိမ့်တာကို "
                "ရွေးပြီး ထပ်စမ်းကြည့်ပါ။"

            )

        else:

            await query.edit_message_text(

                "❌ Download မအောင်မြင်ပါဘူး။\n\n"
                "ခဏနေပြီး ပြန်စမ်းကြည့်ပါ။"

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

            except Exception as e:

                logger.warning(
                    "Cleanup failed: %s",
                    e
                )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Unhandled exception",
        exc_info=context.error
    )


# =========================================================
# MAIN
# =========================================================

def main():

    logger.info(
        "Starting MM Video Downloader Bot..."
    )


    logger.info(
        "YouTube cookies path: %s",
        YOUTUBE_COOKIES_FILE
    )


    cookie_file = get_cookie_file()


    if cookie_file:

        logger.info(
            "YouTube cookies: ENABLED"
        )

    else:

        logger.warning(
            "YouTube cookies: NOT FOUND"
        )


    app = (

        Application.builder()

        .token(BOT_TOKEN)

        .build()

    )


    app.add_handler(

        CommandHandler(
            "start",
            start
        )

    )


    app.add_handler(

        CallbackQueryHandler(

            button_handler,

            pattern=r"^(download|help|about)$"

        )

    )


    app.add_handler(

        CallbackQueryHandler(

            quality_handler,

            pattern=r"^(quality\||unavailable)"

        )

    )


    app.add_handler(

        MessageHandler(

            filters.TEXT
            & ~filters.COMMAND,

            handle_url

        )

    )


    app.add_error_handler(
        error_handler
    )


    logger.info(
        "Bot is starting with polling..."
    )


    app.run_polling(

        drop_pending_updates=True,

        allowed_updates=Update.ALL_TYPES

    )


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    main()
