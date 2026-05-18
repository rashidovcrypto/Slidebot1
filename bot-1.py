import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web
import aiosqlite
import json
from datetime import datetime

# ========== SOZLAMALAR ==========
BOT_TOKEN = "8780645614:AAFGwq1F-3phRaVkUJ4z1hi9NLtiqS-Jvqo"
CHANNEL_ID = "@taqdimot_slayd_yarat"
MINI_APP_URL = "https://your-miniapp.netlify.app"  # ← Netlify URL ni o'zgartiring
ADMIN_IDS = [7948876875]

CREDIT_PRICE = 2000
MIN_TOPUP = 6000
FREE_SLIDES = 1

# ========== LOGGING ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== BOT ==========
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========== HOLATLAR ==========
class PaymentStates(StatesGroup):
    waiting_receipt = State()

# ========== DATABASE ==========
async def init_db():
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                credits INTEGER DEFAULT 0,
                free_slides INTEGER DEFAULT 1,
                total_slides INTEGER DEFAULT 0,
                joined_at TEXT,
                is_banned INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                type TEXT,
                description TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS slides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                slide_url TEXT,
                created_at TEXT
            )
        """)
        await db.commit()

async def get_user(user_id: int):
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "user_id": row[0], "username": row[1], "full_name": row[2],
                    "credits": row[3], "free_slides": row[4], "total_slides": row[5],
                    "joined_at": row[6], "is_banned": row[7]
                }
            return None

async def create_user(user: types.User):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            INSERT OR IGNORE INTO users (user_id, username, full_name, credits, free_slides, joined_at)
            VALUES (?, ?, ?, 0, ?, ?)
        """, (user.id, user.username, user.full_name, FREE_SLIDES, datetime.now().isoformat()))
        await db.commit()

async def add_credits(user_id: int, amount: int, description: str = "To'ldirish"):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (amount, user_id))
        await db.execute("""
            INSERT INTO transactions (user_id, amount, type, description, created_at)
            VALUES (?, ?, 'topup', ?, ?)
        """, (user_id, amount, description, datetime.now().isoformat()))
        await db.commit()

async def use_slide_credit(user_id: int) -> bool:
    user = await get_user(user_id)
    if not user:
        return False
    async with aiosqlite.connect("bot.db") as db:
        if user["free_slides"] > 0:
            await db.execute(
                "UPDATE users SET free_slides = free_slides - 1, total_slides = total_slides + 1 WHERE user_id = ?",
                (user_id,)
            )
            await db.commit()
            return True
        elif user["credits"] >= CREDIT_PRICE:
            await db.execute(
                "UPDATE users SET credits = credits - ?, total_slides = total_slides + 1 WHERE user_id = ?",
                (CREDIT_PRICE, user_id)
            )
            await db.commit()
            return True
        return False

async def get_stats():
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            total_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE date(joined_at) = date('now')") as c:
            today_users = (await c.fetchone())[0]
        async with db.execute("SELECT SUM(total_slides) FROM users") as c:
            total_slides = (await c.fetchone())[0] or 0
        async with db.execute("SELECT SUM(amount) FROM transactions WHERE type='topup'") as c:
            total_income = (await c.fetchone())[0] or 0
    return total_users, today_users, total_slides, total_income

# ========== KANAL TEKSHIRISH ==========
async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status not in ["left", "kicked", "banned"]
    except Exception:
        return False

# ========== KLAVIATURALAR ==========
def main_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎨 Slayd yaratish"), KeyboardButton(text="📊 Hisobim")],
        [KeyboardButton(text="💰 Hisob to'ldirish"), KeyboardButton(text="📚 Slaydlarim")],
        [KeyboardButton(text="❓ Yordam"), KeyboardButton(text="📞 Bog'lanish")]
    ], resize_keyboard=True)

def subscribe_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📢 Kanalga obuna bo'lish",
            url=f"https://t.me/{CHANNEL_ID.lstrip('@')}"
        )],
        [InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_sub")]
    ])

def miniapp_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🎨 Slayd yaratish (Mini App)",
            web_app=WebAppInfo(url=MINI_APP_URL)
        )],
    ])

def payment_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 6,000 so'm — 3 slayd", callback_data="pay_6000")],
        [InlineKeyboardButton(text="💳 12,000 so'm — 6 slayd", callback_data="pay_12000")],
        [InlineKeyboardButton(text="💳 30,000 so'm — 15 slayd", callback_data="pay_30000")],
        [InlineKeyboardButton(text="💳 60,000 so'm — 30 slayd", callback_data="pay_60000")],
    ])

# ========== HANDLERLAR ==========

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await create_user(message.from_user)
    is_subscribed = await check_subscription(message.from_user.id)

    if not is_subscribed:
        await message.answer(
            "👋 Salom! <b>SlideBot</b> ga xush kelibsiz!\n\n"
            "🎨 Bu bot yordamida professional <b>taqdimot slaydlar</b> yaratishingiz mumkin!\n\n"
            "⚠️ Botdan foydalanish uchun avval kanalimizga obuna bo'ling:",
            reply_markup=subscribe_keyboard(),
            parse_mode="HTML"
        )
        return

    user = await get_user(message.from_user.id)
    await message.answer(
        f"👋 Xush kelibsiz, <b>{message.from_user.first_name}</b>!\n\n"
        f"🎨 <b>SlideBot</b> — professional slaydlar yaratish uchun bot\n\n"
        f"💰 Balansingiz: <b>{user['credits']:,} so'm</b>\n"
        f"🎁 Bepul slaydlar: <b>{user['free_slides']} ta</b>\n\n"
        f"Quyidagi tugmalardan birini tanlang:",
        reply_markup=main_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: types.CallbackQuery):
    is_subscribed = await check_subscription(callback.from_user.id)
    if is_subscribed:
        await callback.message.delete()
        await callback.message.answer(
            f"✅ <b>Obuna tasdiqlandi!</b>\n\n"
            f"🎁 Sizga 1 ta <b>bepul slayd</b> berildi!\n"
            f"💰 Keyingi slaydlar: <b>{CREDIT_PRICE:,} so'm</b>\n\n"
            f"Boshlash uchun tugma bosing:",
            reply_markup=main_keyboard(),
            parse_mode="HTML"
        )
    else:
        await callback.answer("❌ Siz hali obuna bo'lmagansiz!", show_alert=True)

@dp.message(F.text == "🎨 Slayd yaratish")
async def create_slide(message: types.Message):
    is_subscribed = await check_subscription(message.from_user.id)
    if not is_subscribed:
        await message.answer("⚠️ Avval kanalga obuna bo'ling!", reply_markup=subscribe_keyboard())
        return

    user = await get_user(message.from_user.id)
    can_create = user["free_slides"] > 0 or user["credits"] >= CREDIT_PRICE

    if not can_create:
        await message.answer(
            "❌ <b>Kredit yetarli emas!</b>\n\n"
            f"💰 1 ta slayd = <b>{CREDIT_PRICE:,} so'm</b>\n"
            f"📊 Balansingiz: <b>{user['credits']:,} so'm</b>\n\n"
            "Hisob to'ldiring:",
            reply_markup=payment_keyboard(),
            parse_mode="HTML"
        )
        return

    info = ""
    if user["free_slides"] > 0:
        info = f"🎁 Bepul slayd ishlatiladi (qoldi: {user['free_slides']} ta)"
    else:
        info = f"💰 {CREDIT_PRICE:,} so'm yechiladi"

    await message.answer(
        f"🎨 <b>Slayd yaratish</b>\n\n{info}\n\nMini App orqali yarating:",
        reply_markup=miniapp_keyboard(),
        parse_mode="HTML"
    )

@dp.message(F.text == "📊 Hisobim")
async def my_account(message: types.Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Xatolik. /start bosing.")
        return
    await message.answer(
        f"👤 <b>Mening hisobim</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"👤 Ism: {user['full_name']}\n"
        f"💰 Balans: <b>{user['credits']:,} so'm</b>\n"
        f"🎁 Bepul slaydlar: <b>{user['free_slides']} ta</b>\n"
        f"🎨 Jami yaratilgan: <b>{user['total_slides']} ta</b>\n"
        f"📅 Ro'yxatdan: {user['joined_at'][:10]}",
        parse_mode="HTML"
    )

@dp.message(F.text == "💰 Hisob to'ldirish")
async def topup_account(message: types.Message):
    await message.answer(
        f"💰 <b>Hisob to'ldirish</b>\n\n"
        f"📌 Minimal: <b>{MIN_TOPUP:,} so'm</b>\n"
        f"🎨 1 slayd = <b>{CREDIT_PRICE:,} so'm</b>\n\n"
        "Paket tanlang:",
        reply_markup=payment_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("pay_"))
async def payment_selected(callback: types.CallbackQuery, state: FSMContext):
    amount = int(callback.data.split("_")[1])
    slides_count = amount // CREDIT_PRICE

    await state.update_data(payment_amount=amount)
    await state.set_state(PaymentStates.waiting_receipt)

    await callback.message.edit_text(
        f"💳 <b>To'lov ma'lumotlari</b>\n\n"
        f"💰 Miqdor: <b>{amount:,} so'm</b>\n"
        f"🎨 Slaydlar soni: <b>{slides_count} ta</b>\n\n"
        f"📱 <b>Uzcard:</b> <code>8600 0000 0000 0000</code>\n"
        f"📱 <b>Humo:</b> <code>9860 0000 0000 0000</code>\n"
        f"👤 Karta egasi: <b>Ism Familiya</b>\n\n"
        f"✅ To'lov qilgach, <b>chek rasmini shu yerga yuboring</b>.\n"
        f"⏰ 5-15 daqiqa ichida aktivlanadi.",
        parse_mode="HTML"
    )

@dp.message(PaymentStates.waiting_receipt, F.photo)
async def receipt_received(message: types.Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("payment_amount", 0)
    slides_count = amount // CREDIT_PRICE
    await state.clear()

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                admin_id,
                message.photo[-1].file_id,
                caption=(
                    f"💰 <b>Yangi to'lov!</b>\n\n"
                    f"👤 {message.from_user.full_name}\n"
                    f"🆔 <code>{message.from_user.id}</code>\n"
                    f"💵 <b>{amount:,} so'm</b> ({slides_count} slayd)\n\n"
                    f"✅ Tasdiqlash:\n<code>/approve {message.from_user.id} {amount}</code>\n\n"
                    f"❌ Rad etish:\n<code>/reject {message.from_user.id}</code>"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Admin xabari xato: {e}")

    await message.answer(
        "✅ <b>Chek qabul qilindi!</b>\n\n"
        "⏰ Admin tekshirib, 5-15 daqiqa ichida kreditingizni aktivlashtiradi.\n"
        "📲 Tayyor bo'lganda xabar beriladi.",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "📚 Slaydlarim")
async def my_slides(message: types.Message):
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT title, created_at FROM slides WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
            (message.from_user.id,)
        ) as cursor:
            slides = await cursor.fetchall()

    if not slides:
        await message.answer(
            "📚 Hali slayd yaratmadingiz.\n🎨 Birinchi slaydingizni yarating!",
            parse_mode="HTML"
        )
        return

    text = "📚 <b>Mening slaydlarim:</b>\n\n"
    for i, slide in enumerate(slides, 1):
        text += f"{i}. {slide[0]} — {slide[1][:10]}\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "❓ Yordam")
async def help_cmd(message: types.Message):
    await message.answer(
        "❓ <b>Yordam</b>\n\n"
        "1️⃣ Kanalga obuna bo'ling\n"
        "2️⃣ 1 ta bepul slayddan foydalaning\n"
        "3️⃣ Keyingi slaydlar uchun hisob to'ldiring\n"
        "4️⃣ Mini App orqali slayd yarating\n\n"
        f"💰 Narx: <b>{CREDIT_PRICE:,} so'm / slayd</b>\n"
        f"📊 Minimal to'ldirish: <b>{MIN_TOPUP:,} so'm</b>\n\n"
        "📞 Savol bo'lsa: @admin_username",
        parse_mode="HTML"
    )

@dp.message(F.text == "📞 Bog'lanish")
async def contact_cmd(message: types.Message):
    await message.answer(
        "📞 <b>Bog'lanish</b>\n\n"
        "👤 Admin: @admin_username\n"
        f"📢 Kanal: {CHANNEL_ID}\n\n"
        "⏰ Ish vaqti: 9:00 — 22:00",
        parse_mode="HTML"
    )

# ========== ADMIN KOMANDALAR ==========

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    total_users, today_users, total_slides, total_income = await get_stats()
    await message.answer(
        f"🔧 <b>Admin Panel</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{total_users}</b>\n"
        f"📅 Bugun qo'shilgan: <b>{today_users}</b>\n"
        f"🎨 Jami slaydlar: <b>{total_slides}</b>\n"
        f"💰 Jami daromad: <b>{total_income:,} so'm</b>\n\n"
        f"📌 Buyruqlar:\n"
        f"/approve ID SUMMA — to'lovni tasdiqlash\n"
        f"/reject ID — to'lovni rad etish\n"
        f"/give ID SUMMA — kredit berish\n"
        f"/ban ID — foydalanuvchini bloklash",
        parse_mode="HTML"
    )

@dp.message(Command("approve"))
async def approve_payment(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        parts = message.text.split()
        user_id = int(parts[1])
        amount = int(parts[2])
        slides_count = amount // CREDIT_PRICE
        await add_credits(user_id, amount, f"To'lov tasdiqlandi")
        await bot.send_message(
            user_id,
            f"✅ <b>To'lovingiz tasdiqlandi!</b>\n\n"
            f"💰 Hisobingizga <b>{amount:,} so'm</b> qo'shildi\n"
            f"🎨 <b>{slides_count} ta slayd</b> yaratishingiz mumkin!",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )
        await message.answer(f"✅ {user_id} ga {amount:,} so'm berildi.")
    except Exception as e:
        await message.answer(f"❌ Xato. Format: /approve 123456 6000")

@dp.message(Command("reject"))
async def reject_payment(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        user_id = int(message.text.split()[1])
        await bot.send_message(
            user_id,
            "❌ <b>To'lovingiz rad etildi.</b>\n\nMuammo bo'lsa admin bilan bog'laning.",
            parse_mode="HTML"
        )
        await message.answer(f"❌ {user_id} to'lovi rad etildi.")
    except:
        await message.answer("Format: /reject 123456")

@dp.message(Command("give"))
async def give_credits(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        parts = message.text.split()
        user_id = int(parts[1])
        amount = int(parts[2])
        await add_credits(user_id, amount, "Admin sovg'asi")
        await bot.send_message(user_id, f"🎁 Hisobingizga <b>{amount:,} so'm</b> qo'shildi!", parse_mode="HTML")
        await message.answer(f"✅ {user_id} ga {amount:,} so'm berildi.")
    except:
        await message.answer("Format: /give 123456 6000")

# ========== WEB APP DAN MA'LUMOT ==========
@dp.message(F.web_app_data)
async def web_app_handler(message: types.Message):
    try:
        data = json.loads(message.web_app_data.data)
        if data.get("action") == "create_slide":
            success = await use_slide_credit(message.from_user.id)
            if success:
                title = data.get("title", "Yangi slayd")
                async with aiosqlite.connect("bot.db") as db:
                    await db.execute(
                        "INSERT INTO slides (user_id, title, slide_url, created_at) VALUES (?, ?, ?, ?)",
                        (message.from_user.id, title, "", datetime.now().isoformat())
                    )
                    await db.commit()
                user = await get_user(message.from_user.id)
                await message.answer(
                    f"✅ <b>Slayd yaratildi!</b>\n\n"
                    f"📌 {title}\n\n"
                    f"💰 Qolgan balans: <b>{user['credits']:,} so'm</b>",
                    parse_mode="HTML",
                    reply_markup=main_keyboard()
                )
            else:
                await message.answer(
                    "❌ Kredit yetarli emas!\nHisob to'ldiring.",
                    reply_markup=payment_keyboard()
                )
    except Exception as e:
        logger.error(f"WebApp xato: {e}")

# ========== HEALTH CHECK (Render uchun) ==========
async def health_check(request):
    return web.Response(text="✅ SlideBot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    logger.info("Web server ishga tushdi: port 8080")

# ========== MAIN ==========
async def main():
    await init_db()
    await start_web_server()
    logger.info("Bot ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
