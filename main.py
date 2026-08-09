import os
import re
import asyncio
import logging
from pathlib import Path

import yt_dlp
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")


BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"

DOWNLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
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
# SUPPORTED URL
# =========================================================

YOUTUBE_REGEX = re.compile(
    r"^https?://"
    r"(www\.)?"
    r"(youtube\.com|youtu\.be)/.+",
    re.IGNORECASE,
)

TIKTOK_REGEX = re.compile(
    r"^https?://"
    r"(www\.)?"
    r"(tiktok\.com|vt\.tiktok\.com)/.+",
    re.IGNORECASE,
)


def is_supported_url(url: str) -> bool:

    return bool(
        YOUTUBE_REGEX.match(url)
        or TIKTOK_REGEX.match(url)
    )


def is_tiktok_url(url: str) -> bool:

    return bool(
        TIKTOK_REGEX.match(url)
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
            ),
        ],

        [
            InlineKeyboardButton(
                "👨‍💻 Contact Developer",
                url="https://t.me/superraizo7"
            )
        ],

    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = (
        "🎬 <b>MM Video Downloader</b>\n\n"

        "YouTube / TikTok Downloader\n\n"

        "📥 Supported Quality\n"
        "• 240p\n"
        "• 360p\n"
        "• 480p\n"
        "• 720p\n"
        "• 1080p\n"
        "• 🎵 MP3\n\n"

        "🔗 Download လုပ်ရန်\n"
        "YouTube / TikTok Video Link ပို့ပါ။"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


# =========================================================
# BUTTON HANDLER
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    if query.data == "download":

        await query.message.reply_text(
            "🔗 YouTube သို့မဟုတ် TikTok Video Link ကို ပို့ပါ။"
        )

    elif query.data == "help":

        await query.message.reply_text(
            "❓ <b>အသုံးပြုနည်း</b>\n\n"

            "1️⃣ YouTube / TikTok Link ပို့ပါ\n"
            "2️⃣ Bot က Video Information စစ်ပါမယ်\n"
            "3️⃣ Quality ရွေးပါ\n"
            "4️⃣ Download ပြီးရင် File ပြန်ပို့ပေးပါမယ်။\n\n"

            "🎵 MP3 လည်း Download လုပ်နိုင်ပါတယ်။",

            parse_mode="HTML",
        )

    elif query.data == "about":

        await query.message.reply_text(
            "🎬 <b>MM Video Downloader</b>\n\n"

            "YouTube & TikTok Downloader\n\n"

            "⚡ Dynamic Format Detection\n"
            "📥 Video Downloader\n"
            "🎵 MP3 Downloader\n\n"

            "👨‍💻 Developer: @superraizo7",

            parse_mode="HTML",
        )


# =========================================================
# GET VIDEO INFORMATION
# =========================================================

def get_video_info(url: str):

    options = {

        "quiet": True,

        "no_warnings": True,

        "noplaylist": True,

        "skip_download": True,

    }

    with yt_dlp.YoutubeDL(options) as ydl:

        return ydl.extract_info(
            url,
            download=False,
        )


# =========================================================
# FORMAT ANALYSIS
# =========================================================

def analyze_formats(info):

    formats = info.get(
        "formats",
        []
    )

    video_formats = []

    heights = []

    for fmt in formats:

        vcodec = fmt.get(
            "vcodec"
        )

        if (
            not vcodec
            or vcodec == "none"
        ):
            continue

        height = fmt.get(
            "height"
        )

        if height:

            try:
                height = int(height)
                heights.append(height)

            except (
                TypeError,
                ValueError
            ):
                pass

        video_formats.append(fmt)

    max_height = (
        max(heights)
        if heights
        else None
    )

    return {
        "has_video": bool(video_formats),
        "max_height": max_height,
        "formats": video_formats,
    }


# =========================================================
# AVAILABLE QUALITY DETECTION
# =========================================================

def detect_available_qualities(
    info,
    url: str,
):

    analysis = analyze_formats(
        info
    )

    has_video = analysis[
        "has_video"
    ]

    max_height = analysis[
        "max_height"
    ]

    available = {}

    target_qualities = [
        240,
        360,
        480,
        720,
        1080,
    ]

    # -----------------------------------------------------
    # If yt-dlp cannot report height but video exists,
    # allow quality buttons.
    #
    # This is especially useful for some TikTok formats.
    # -----------------------------------------------------

    if has_video and max_height is None:

        for quality in target_qualities:
            available[quality] = True

        return available

    # -----------------------------------------------------
    # Normal YouTube / TikTok detection
    # -----------------------------------------------------

    for quality in target_qualities:

        available[quality] = bool(
            has_video
            and max_height
            and max_height >= quality
        )

    return available


# =========================================================
# QUALITY KEYBOARD
# =========================================================

def quality_keyboard(
    available_qualities
):

    keyboard = []

    row = []

    for quality in [
        240,
        360,
        480,
        720,
        1080,
    ]:

        if available_qualities.get(
            quality,
            False
        ):

            button_text = (
                f"✅ {quality}p"
            )

            callback = (
                f"quality|{quality}p"
            )

        else:

            button_text = (
                f"❌ {quality}p"
            )

            callback = "unavailable"

        row.append(
            InlineKeyboardButton(
                button_text,
                callback_data=callback,
            )
        )

        if len(row) == 2:

            keyboard.append(row)

            row = []

    if row:
        keyboard.append(row)

    keyboard.append(
        [
            InlineKeyboardButton(
                "🎵 MP3",
                callback_data="quality|mp3",
            )
        ]
    )

    keyboard.append(
        [
            InlineKeyboardButton(
                "👨‍💻 Contact Developer",
                url="https://t.me/superraizo7",
            )
        ]
    )

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# HANDLE URL
# =========================================================

async def handle_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    url = update.message.text.strip()

    if not is_supported_url(url):

        await update.message.reply_text(
            "❌ YouTube သို့မဟုတ် TikTok Link ပဲ ပို့ပါ။"
        )

        return

    status = await update.message.reply_text(
        "🔎 <b>Video Information စစ်နေပါတယ်...</b>\n\n"
        "⏳ Available formats တွေကို စစ်နေပါတယ်။",
        parse_mode="HTML",
    )

    try:

        info = await asyncio.to_thread(
            get_video_info,
            url,
        )

        title = info.get(
            "title",
            "Unknown",
        )

        duration = info.get(
            "duration",
            0,
        ) or 0

        minutes = duration // 60
        seconds = duration % 60

        available = detect_available_qualities(
            info,
            url,
        )

        context.user_data[
            "url"
        ] = url

        context.user_data[
            "available_qualities"
        ] = available

        context.user_data[
            "video_title"
        ] = title

        quality_status = []

        for quality in [
            240,
            360,
            480,
            720,
            1080,
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

        text = (
            "🎬 <b>Video Found</b>\n\n"

            f"📌 <b>Title:</b>\n"
            f"{title}\n\n"

            f"⏱ <b>Duration:</b> "
            f"{minutes}:{seconds:02d}\n\n"

            "📊 <b>Available Quality</b>\n"
            + "\n".join(
                quality_status
            )
            + "\n\n"

            "👇 <b>Download Quality ရွေးပါ။</b>"
        )

        await status.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=quality_keyboard(
                available
            ),
        )

    except Exception:

        logger.exception(
            "Information extraction failed"
        )

        await status.edit_text(
            "❌ <b>Video Information ရယူမရပါ။</b>\n\n"
            "Link မှန်/မမှန် ပြန်စစ်ပြီး ထပ်ကြိုးစားပါ။",
            parse_mode="HTML",
        )


# =========================================================
# DOWNLOAD VIDEO
# =========================================================

def download_video(
    url: str,
    quality: str,
    user_id: int,
):

    user_dir = (
        DOWNLOAD_DIR /
        str(user_id)
    )

    user_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = str(
        user_dir /
        "%(title).80s [%(id)s].%(ext)s"
    )

    height = int(
        quality.replace(
            "p",
            ""
        )
    )

    # -----------------------------------------------------
    # IMPORTANT
    #
    # bestvideo + bestaudio:
    # YouTube high quality
    #
    # best:
    # TikTok / single-file formats
    #
    # The fallback chain is important.
    # -----------------------------------------------------

    format_selector = (
        f"bestvideo[height<={height}]"
        f"+bestaudio/"
        f"best[height<={height}]/"
        f"best"
    )

    options = {

        "outtmpl": output,

        "noplaylist": True,

        "format": format_selector,

        "merge_output_format": "mp4",

        "quiet": True,

        "no_warnings": True,

        "restrictfilenames": True,

        "overwrites": True,

    }

    with yt_dlp.YoutubeDL(
        options
    ) as ydl:

        info = ydl.extract_info(
            url,
            download=True,
        )

        requested_downloads = (
            info.get(
                "requested_downloads"
            )
            or []
        )

        # -------------------------------------------------
        # Find actual downloaded file
        # -------------------------------------------------

        possible_files = []

        for item in requested_downloads:

            filepath = item.get(
                "filepath"
            )

            if filepath:

                possible_files.append(
                    Path(filepath)
                )

        filename = ydl.prepare_filename(
            info
        )

        possible_files.append(
            Path(filename)
        )

        possible_files.append(
            Path(filename).with_suffix(
                ".mp4"
            )
        )

        for path in possible_files:

            if path.exists():

                return str(path)

        # -------------------------------------------------
        # Search user directory as final fallback
        # -------------------------------------------------

        files = list(
            user_dir.glob("*")
        )

        if files:

            files.sort(
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

            return str(
                files[0]
            )

        raise FileNotFoundError(
            "Downloaded video file not found"
        )


# =========================================================
# DOWNLOAD MP3
# =========================================================

def download_mp3(
    url: str,
    user_id: int,
):

    user_dir = (
        DOWNLOAD_DIR /
        str(user_id)
    )

    user_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = str(
        user_dir /
        "%(title).80s [%(id)s].%(ext)s"
    )

    options = {

        "outtmpl": output,

        "noplaylist": True,

        "format":
            "bestaudio/best",

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

        "quiet": True,

        "no_warnings": True,

        "restrictfilenames": True,

        "overwrites": True,
    }

    with yt_dlp.YoutubeDL(
        options
    ) as ydl:

        info = ydl.extract_info(
            url,
            download=True,
        )

        filename = ydl.prepare_filename(
            info
        )

        mp3_file = Path(
            filename
        ).with_suffix(
            ".mp3"
        )

        if mp3_file.exists():

            return str(
                mp3_file
            )

        # Final fallback

        files = list(
            user_dir.glob("*.mp3")
        )

        if files:

            files.sort(
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

            return str(
                files[0]
            )

        raise FileNotFoundError(
            "MP3 file not found"
        )


# =========================================================
# QUALITY
