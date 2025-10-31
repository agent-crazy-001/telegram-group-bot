import os
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    filters, 
    ContextTypes,
    CallbackQueryHandler,
    ChatJoinRequestHandler
)
import sqlite3
import logging
import re

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# دریافت توکن از Environment Variables
BOT_TOKEN = os.environ.get('7792704606:AAG6Ajd0XBX6SspJzXMQGijXzQoGd8ztnxk')

if not BOT_TOKEN:
    raise ValueError("لطفاً BOT_TOKEN را در Environment Variables تنظیم کنید")

# دیتابیس برای ذخیره اطلاعات کاربران در حال انتظار
def init_database():
    conn = sqlite3.connect('/tmp/group_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            photo_file_id TEXT,
            group_id INTEGER,
            status TEXT DEFAULT 'pending'
        )
    ''')
    conn.commit()
    conn.close()

init_database()

# دستور start
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 ربات مدیریت گروه فعال است!\n\n"
        "قابلیت‌ها:\n"
        "✅ تایید کاربران قبل از ورود به گروه\n"
        "❌ حذف خودکار لینک‌های ارسالی\n\n"
        "برای تنظیم ربات در گروه، آن را به عنوان ادمین اضافه کنید."
    )

# مدیریت کاربران جدیدی که می‌خواهند به گروه بپیوندند
async def handle_chat_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    join_request = update.chat_join_request
    user = join_request.from_user
    chat = join_request.chat
    
    # ذخیره اطلاعات کاربر در دیتابیس
    conn = sqlite3.connect('/tmp/group_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO pending_users 
        (user_id, username, first_name, group_id, status) 
        VALUES (?, ?, ?, ?, ?)
    ''', (user.id, user.username, user.first_name, chat.id, 'pending'))
    
    conn.commit()
    conn.close()
    
    # ایجاد کیبورد برای مالک
    keyboard = [
        [
            InlineKeyboardButton("✅ تایید کاربر", callback_data=f"approve_{user.id}"),
            InlineKeyboardButton("❌ رد کاربر", callback_data=f"reject_{user.id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # ارسال پیام به مالک گروه
    message_text = (
        "📥 درخواست جدید برای پیوستن به گروه:\n\n"
        f"👤 نام: {user.first_name}\n"
        f"🔗 آیدی: @{user.username if user.username else 'ندارد'}\n"
        f"🆔 عددی: {user.id}\n\n"
        "لطفاً کاربر را تایید یا رد کنید:"
    )
    
    # پیدا کردن ادمین‌های گروه
    admins = await context.bot.get_chat_administrators(chat.id)
    for admin in admins:
        if admin.status == 'creator':  # فقط مالک گروه
            try:
                await context.bot.send_message(
                    chat_id=admin.user.id,
                    text=message_text,
                    reply_markup=reply_markup
                )
                break
            except:
                continue
    
    # درخواست عکس از کاربر
    try:
        await context.bot.send_message(
            chat_id=user.id,
            text="📸 لطفاً یک عکس از خودتان ارسال کنید تا فرآیند تایید شما تکمیل شود."
        )
    except:
        pass

# مدیریت عکس ارسالی توسط کاربر
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    photo_file_id = update.message.photo[-1].file_id
    
    # آپدیت اطلاعات کاربر در دیتابیس
    conn = sqlite3.connect('/tmp/group_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE pending_users 
        SET photo_file_id = ?WHERE user_id = ? AND status = 'pending'
    ''', (photo_file_id, user.id))
    
    cursor.execute('SELECT group_id FROM pending_users WHERE user_id = ?', (user.id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        group_id = result[0]
        
        # ارسال عکس به مالک گروه
        admins = await context.bot.get_chat_administrators(group_id)
        for admin in admins:
            if admin.status == 'creator':
                try:
                    await context.bot.send_photo(
                        chat_id=admin.user.id,
                        photo=photo_file_id,
                        caption=f"📸 عکس ارسالی توسط کاربر:\n\n"
                               f"👤 نام: {user.first_name}\n"
                               f"🔗 آیدی: @{user.username if user.username else 'ندارد'}\n"
                               f"🆔 عددی: {user.id}"
                    )
                    break
                except:
                    continue
        
        await update.message.reply_text(
            "✅ عکس شما دریافت شد. منتظر تایید مالک گروه باشید."
        )

# مدیریت کلیک روی دکمه‌های کیبورد
async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = int(data.split('_')[1])
    action = data.split('_')[0]
    
    conn = sqlite3.connect('/tmp/group_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT group_id, first_name FROM pending_users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    
    if not result:
        await query.edit_message_text("❌ کاربر پیدا نشد.")
        return
    
    group_id, first_name = result
    
    if action == "approve":
        # تایید کاربر
        try:
            await context.bot.approve_chat_join_request(group_id, user_id)
            
            cursor.execute('DELETE FROM pending_users WHERE user_id = ?', (user_id,))
            conn.commit()
            
            await query.edit_message_text(f"✅ کاربر {first_name} با موفقیت تایید شد.")
            
            # اطلاع به کاربر
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="🎉 درخواست شما تایید شد! اکنون می‌توانید به گروه بپیوندید."
                )
            except:
                pass
                
        except Exception as e:
            await query.edit_message_text(f"❌ خطا در تایید کاربر: {str(e)}")
    
    elif action == "reject":
        # رد کاربر
        try:
            await context.bot.decline_chat_join_request(group_id, user_id)
            
            cursor.execute('DELETE FROM pending_users WHERE user_id = ?', (user_id,))
            conn.commit()
            
            await query.edit_message_text(f"❌ کاربر {first_name} رد شد.")
            
            # اطلاع به کاربر
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="❌ متأسفانه درخواست شما رد شد."
                )
            except:
                pass
                
        except Exception as e:
            await query.edit_message_text(f"❌ خطا در رد کاربر: {str(e)}")
    
    conn.close()

# تشخیص و حذف لینک‌ها
def contains_link(text):
    if not text:
        return False
    
    # الگوهای مختلف لینک
    link_patterns = [
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
        r'www\.[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        r't\.me/[a-zA-Z0-9_]+',
        r'@[a-zA-Z0-9_]+'
    ]
    
    for pattern in link_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    
    return False

# حذف پیام‌های حاوی لینک
async def delete_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    
    # اگر پیام حاوی لینک باشد
    if message.text and contains_link(message.text):
        try:
            await message.delete()
            
            # اخطار به کاربر
            warning_msg = await message.reply_text(
                f"⚠️ ارسال لینک در این گروه ممنوع است!\n"
                f"کاربر: {message.from_user.mention_markdown()}"
            )
            
        except Exception as e:
            print(f"خطا در حذف پیام: {e}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, delete_links))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(ChatJoinRequestHandler(handle_chat_join_request))
    application.add_handler(CallbackQueryHandler(handle_button_click))
    
    print("🤖 ربات مدیریت گروه فعال شد...")
    application.run_polling()

if os.name == '__main__':
    main()