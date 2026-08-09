
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


PORT = int(os.getenv("PORT", "10000"))

RENDER_EXTERNAL_URL = os.getenv(
    "RENDER_EXTERNAL_URL"
)

if not RENDER_EXTERNAL_URL:
    raise RuntimeError(
        "RENDER_EXTERNAL_URL is missing"
    )


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
# URL REGEX
# =========================================================

YOUTUBE_REGEX = re.compile(
    r"https?://(www\.)?"
    r"(youtube\.com|youtu\.be)/.+",
    re.IGNORECASE,
)

TIKTOK_REGEX = re.compile(
    r"https?://(www\.)?"
    r"(tiktok\.com|vt\.tiktok\.com)/.+",
    re.IGNORECASE,
)


def is_supported_url(url: str) -> bool:

    return bool(
        YOUTUBE_REGEX.match(url)
        or TIKTOK_REGEX.match(url)
    )


# =========================================================
# MAIN MENU
# =========================================================

def main_menu():

    keyboard = [

        [
            InlineKeyboardButton(
                "📥 Download Video",
                callback_data="download",
            )
        ],

        [
            InlineKeyboardButton(
                "❓ Help",
                callback_data="help",
            ),
            InlineKeyboardButton(
                "ℹ️ About",
                callback_data="about",
            ),
        ],

        [
            InlineKeyboardButton(
                "👨‍💻 Contact Developer",
                url="https://t.me/superraizo7",
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

        "🔗 Download လုပ်ရန် "
        "Video Link ပို့ပါ။"
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
            "3️⃣ ရနိုင်တဲ့ Quality ကို ရွေးပါ\n"
            "4️⃣ Download ပြီးရင် File ပြန်ပို့ပေးပါမယ်။",

            parse_mode="HTML",
        )

    elif query.data == "about":

        await query.message.reply_text(
            "🎬 <b>MM Video Downloader</b>\n\n"

            "YouTube & TikTok Downloader\n\n"

            "⚡ Dynamic Quality Detection\n"
            "📥 Video Downloader\n"
            "🎵 MP3 Downloader\n\n"

            "👨‍💻 Developer: @superraizo7",

            parse_mode="HTML",
        )


# =========================================================
# GET VIDEO INFO
# =========================================================

def get_video_info(url: str):

    options = {

        "quiet": True,

        "no_warnings": True,

        "noplaylist": True,

        "extract_flat": False,

    }

    with yt_dlp.YoutubeDL(options) as ydl:

        return ydl.extract_info(
            url,
            download=False,
        )


# =========================================================
# QUALITY DETECTION
# =========================================================

def detect_available_qualities(info):

    formats = info.get(
        "formats",
        [],
    )

    available_heights = set()

    # Main video height
    main_height = info.get("height")

    if main_height:

        try:
            available_heights.add(
                int(main_height)
            )

        except Exception:
            pass

    # Formats height
    for fmt in formats:

        height = fmt.get("height")

        vcodec = fmt.get("vcodec")

        if (
            height
            and vcodec
            and vcodec != "none"
        ):

            try:

                available_heights.add(
                    int(height)
                )

            except Exception:
                pass

    target_qualities = [
        240,
        360,
        480,
        720,
        1080,
    ]

    available = {}

    for quality in target_qualities:

        available[quality] = any(
            height >= quality
            for height in available_heights
        )

    # If yt-dlp doesn't expose height,
    # but a downloadable video exists,
    # allow the qualities and let yt-dlp choose.
    if not available_heights:

        has_video = False

        for fmt in formats:

            vcodec = fmt.get("vcodec")

            if (
                vcodec
                and vcodec != "none"
            ):

                has_video = True
                break

        if has_video:

            available = {
                quality: True
                for quality in target_qualities
            }

    return available


# =========================================================
# QUALITY KEYBOARD
# =========================================================

def quality_keyboard(
    available_qualities,
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
            False,
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
        "⏳ ခဏစောင့်ပါ။",
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

        duration = (
            info.get("duration", 0)
            or 0
        )

        minutes = duration // 60

        seconds = duration % 60

        available = (
            detect_available_qualities(
                info
            )
        )

        context.user_data[
            "url"
        ] = url

        context.user_data[
            "available_qualities"
        ] = available

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
                False,
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
            "Link မှန်/မမှန် ပြန်စစ်ပြီး "
            "ထပ်ကြိုးစားပါ။",
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
            "",
        )
    )

    options = {

        "outtmpl": output,

        "noplaylist": True,

        "format":
            f"bestvideo[height<={height}]"
            f"+bestaudio/"
            f"best[height<={height}]"
            f"/best",

        "merge_output_format": "mp4",

        "quiet": True,

        "no_warnings": True,

        "restrictfilenames": True,

        "retries": 3,

        "fragment_retries": 3,

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

        possible_files = [

            Path(filename),

            Path(filename).with_suffix(
                ".mp4"
            ),

        ]

        for file_path in possible_files:

            if file_path.exists():

                return str(file_path)

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

        "retries": 3,

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

        if not mp3_file.exists():

            raise FileNotFoundError(
                "MP3 file not found"
            )

        return str(mp3_file)


# =========================================================
# QUALITY CALLBACK
# =========================================================

async def quality_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    if query.data == "unavailable":

        await query.answer(
            "❌ ဒီ Video မှာ ဒီ Quality မရှိပါ။",
            show_alert=True,
        )

        return

    _, quality = query.data.split(
        "|",
        1,
    )

    url = context.user_data.get(
        "url"
    )

    available = context.user_data.get(
        "available_qualities",
        {},
    )

    if not url:

        await query.message.reply_text(
            "❌ Download session မတွေ့ပါ။"
        )

        return

    if quality != "mp3":

        height = int(
            quality.replace(
                "p",
                "",
            )
        )

        if not available.get(
            height,
            False,
        ):

            await query.answer(
                f"❌ {quality} မရနိုင်ပါ။",
                show_alert=True,
            )

            return

    await query.message.edit_text(
        f"⏳ <b>{quality}</b> Download လုပ်နေပါတယ်...\n\n"
        "📥 Server မှာ Download လုပ်နေပါတယ်။\n"
        "ခဏစောင့်ပါ...",
        parse_mode="HTML",
    )

    user_id = (
        update.effective_user.id
    )

    file_path = None

    try:

        if quality == "mp3":

            file_path = await asyncio.to_thread(
                download_mp3,
                url,
                user_id,
            )

            await query.message.reply_audio(
                audio=file_path,
                caption=(
                    "🎵 <b>MP3 Download Complete</b>"
                ),
                parse_mode="HTML",
            )

        else:

            file_path = await asyncio.to_thread(
                download_video,
                url,
                quality,
                user_id,
            )

            await query.message.reply_video(
                video=file_path,
                caption=(
                    "🎬 <b>Download Complete</b>\n\n"
                    f"📥 Quality: {quality}"
                ),
                parse_mode="HTML",
                supports_streaming=True,
            )

    except Exception:

        logger.exception(
            "Download failed"
        )

        await query.message.reply_text(
            "❌ <b>Video Download မအောင်မြင်ပါ။</b>\n\n"
            "ဖြစ်နိုင်သောအကြောင်းရင်းများ:\n"
            "• Video format မရနိုင်ခြင်း\n"
            "• Video unavailable\n"
            "• File size ကြီးလွန်းခြင်း\n"
            "• FFmpeg error\n"
            "• Platform restriction\n\n"
            "နောက်တစ်ကြိမ် ပြန်ကြိုးစားပါ။",
            parse_mode="HTML",
        )

    finally:

        if file_path:

            try:

                path = Path(
                    file_path
                )

                if path.exists():

                    path.unlink()

            except Exception:

                logger.warning(
                    "File cleanup failed"
                )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.error(
        "Unhandled exception: %s",
        context.error,
    )


# =========================================================
# MAIN - WEBHOOK
# =========================================================

def main():

    print(
        "🤖 MM Video Downloader Bot Started"
    )

    webhook_url = (
        RENDER_EXTERNAL_URL.rstrip("/")
        + "/webhook"
    )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    # Main buttons
    app.add_handler(
        CallbackQueryHandler(
            button_handler,
            pattern="^(download|help|about)$",
        )
    )

    # Quality buttons
    app.add_handler(
        CallbackQueryHandler(
            quality_handler,
            pattern=r"^(quality\||unavailable)",
        )
    )

    # URLs
    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_url,
        )
    )

    app.add_error_handler(
        error_handler
    )

    print(
        f"🌐 Webhook URL: {webhook_url}"
    )

    print(
        f"🚀 Port: {PORT}"
    )

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=webhook_url,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
