import telebot
import time
from datetime import datetime
from telebot.types import ReplyKeyboardMarkup
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

# ===== ADMIN SOZLAMALAR =====
ADMIN_ID = 8335295626
ADMIN_IDS = [ADMIN_ID]

# ===== GLOBAL HOLATLAR =====
admin_step = {}
selected_driver = {}
admin_broadcast_wait = {}
TEMP_BLOCK_FILE = "temp_blocks.json"


def register_admin_handlers(bot, load_json, save_json,
                            DRIVER_FILE, ORDERS_FILE, FINISHED_ORDERS_FILE):

    # ===== ADMIN TEKSHIRISH =====
    def is_admin(uid):
        return uid in ADMIN_IDS

    # ================= STATISTIKA =================
    def generate_statistics():
        drivers = load_json(DRIVER_FILE)
        orders = load_json(ORDERS_FILE)
        finished = load_json(FINISHED_ORDERS_FILE)

        today = datetime.now().strftime("%Y-%m-%d")

        total_orders = len(orders) + len(finished)
        today_orders = sum(1 for o in orders.values() if o.get("date") == today)
        cancelled = sum(1 for o in orders.values() if o.get("status") == "cancelled")
        taken = sum(1 for o in orders.values() if o.get("status") == "taken")

        total_drivers = len(drivers)
        online = busy = free = zero_balance = 0

        for d in drivers.values():
            if d.get("online"):
                online += 1
                busy += 1 if d.get("busy") else 0
                free += 0 if d.get("busy") else 1
            if float(d.get("balance", 0)) <= 0:
                zero_balance += 1

        turnover = sum(float(o.get("total", 0)) for o in finished.values())
        admin_income = sum(float(o.get("admin_fee", 0)) for o in finished.values())

        return (
            "📊 *To'liq statistika*\n\n"
            f"📦 Buyurtmalar soni: {total_orders} ta\n"
            f"📅 Bugungi buyurtmalar: {today_orders} ta\n"
            f"❌ Bekor qilinganlar: {cancelled} ta\n"
            f"✅ Haydovchi tomonidan olinganlar: {taken} ta\n\n"
            f"🚕 Ro'yxatdan o'tgan haydovchilar: {total_drivers} nafar\n"
            f"🟢 Onlayn haydovchilar: {online} nafar\n"
            f"🔴 Band haydovchilar: {busy} nafar\n"
            f"⚪ Bo'sh haydovchilar: {free} nafar\n"
            f"💸 Balansi 0 yoki minus haydovchilar: {zero_balance} nafar\n\n"
            f"💰 Umumiy aylanma: {int(turnover):,} so'm\n"
            f"🧾 Admin daromadi: {int(admin_income):,} so'm"
        )

    # ================= /admin =================
    @bot.message_handler(commands=['admin'])
    def admin_panel(message):
        if not is_admin(message.chat.id):
            return bot.send_message(message.chat.id, "❌ Siz admin emassiz!")

        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("📊 Statistika", "📤 Xabar yuborish","/send")
        kb.add("/find_finished", "/block_driver", "/unblock_driver")
        kb.add("/add_balance", "/remove_balance", "/driver_info")
        kb.add("/start","/broadcast")

        bot.send_message(
            message.chat.id,
            "🛠 *Admin paneli*",
            parse_mode="Markdown",
            reply_markup=kb
        )

    # ================= STATISTIKA =================
    @bot.message_handler(func=lambda m: m.text == "📊 Statistika")
    def admin_stats(message):
        if is_admin(message.chat.id):
            bot.send_message(message.chat.id, generate_statistics(), parse_mode="Markdown")

    # ================= BROADCAST =================
    @bot.message_handler(func=lambda m: m.text == "📤 Xabar yuborish")
    def start_broadcast(message):
        if not is_admin(message.chat.id):
            return
        admin_broadcast_wait[message.chat.id] = True
        bot.send_message(message.chat.id, "✍️ Barcha haydovchilarga yuboriladigan xabarni yozing (matn, rasm, video, fayl yoki ovozli xabar bo'lishi mumkin)")

    @bot.message_handler(func=lambda m: admin_broadcast_wait.get(m.chat.id),
                         content_types=['text','photo','video','document','voice'])
    def send_broadcast(message):
        admin_broadcast_wait[message.chat.id] = False
        drivers = load_json(DRIVER_FILE)

        sent = 0
        for did in drivers:
            try:
                if message.content_type == "text":
                    bot.send_message(did, message.text)
                else:
                    bot.copy_message(did, message.chat.id, message.message_id)
                sent += 1
            except:
                pass

        bot.send_message(message.chat.id, f"✅ {sent} ta haydovchiga muvaffaqiyatli yuborildi")

    # ========== ADMIN: HAYDOVCHINI VAQTINChALIK YOKI BUTUNLAY BLOKLASH ==========
    @bot.message_handler(commands=['block_driver'])
    def admin_block_driver(message):
        if not is_admin(message.from_user.id):
            bot.send_message(message.chat.id, "❌ Sizda bu buyruqni ishlatish huquqi yo‘q!")
            return
    
        parts = message.text.split()
        if len(parts) < 2:
            bot.send_message(
                message.chat.id,
                "❗ Foydalanish:\n"
                "/block_driver <haydovchi_id> [soat_soni yoki 'permanent']\n\n"
                "Masalan:\n"
                "/block_driver 123456789 24  → 24 soatga blok\n"
                "/block_driver 123456789 permanent  → butunlay blok\n"
                "/block_driver 123456789  → oddiy blok (butunlay)"
            )
            return
    
        try:
            driver_id = int(parts[1])
            duration = parts[2] if len(parts) > 2 else "permanent"
            
            if duration != "permanent":
                hours = int(duration)
                if hours <= 0 or hours > 720:
                    raise ValueError
            else:
                hours = None
        except:
            bot.send_message(message.chat.id, "❌ ID va soat soni (yoki 'permanent') to‘g‘ri bo‘lishi kerak!")
            return
    
        driver_str_id = str(driver_id)
        drivers = load_json(DRIVER_FILE)
        orders = load_json(ORDERS_FILE)
    
        if driver_str_id not in drivers:
            bot.send_message(message.chat.id, "❌ Bunday haydovchi topilmadi!")
            return
    
        was_busy = drivers[driver_str_id].get("busy", False)
        order_reset = False
    
        if was_busy:
            for order_id, order in orders.items():
                if str(order.get("driver_id")) == driver_str_id and order.get("status") == "taken":
                    order["status"] = "open"
                    order.pop("driver_id", None)
                    order.pop("taken_time", None)
                    save_json(ORDERS_FILE, orders)
                    order_reset = True
    
                    try:
                        user_id = order.get("user_id")
                        if user_id:
                            bot.send_message(
                                user_id,
                                "⚠️ Haydovchi admin tomonidan bloklandi.\n\n"
                                "🔄 Buyurtmangiz qayta haydovchilarga taklif qilinmoqda.\n"
                                "Tez orada yangi haydovchi topiladi, iltimos kuting.",
                                parse_mode="Markdown"
                            )
                    except:
                        pass
                    break
    
        # Blok ma'lumotlarini saqlash (temp_blocks.json ga)
        blocked_data = load_json(TEMP_BLOCK_FILE)
        until_time = None if hours is None else time.time() + (hours * 3600)
        until_str = "Doimiy (butunlay)" if hours is None else datetime.fromtimestamp(until_time).strftime('%d.%m.%Y %H:%M')
    
        blocked_data[driver_str_id] = {
            "blocked_until": until_time,  # None = butunlay
            "blocked_at": time.time(),
            "admin_id": message.from_user.id,
            "hours": hours
        }
        save_json(TEMP_BLOCK_FILE, blocked_data)
    
        # Haydovchini bloklash
        drivers[driver_str_id]["blocked"] = True
        drivers[driver_str_id]["online"] = False
        drivers[driver_str_id]["busy"] = False
        save_json(DRIVER_FILE, drivers)
    
        # Haydovchiga xabar
        try:
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("📞 Admin bilan bog‘lanish")
    
            text = f"🚫 Siz admin tomonidan bloklandingiz!\n\n"
            text += f"⏳ Muddat: {until_str}\n\n"
            text += "❌ Buyurtma qabul qilish va ishni boshlash cheklangan.\n"
            text += "🔴 Siz majburan oflayn holatga o‘tkazildingiz.\n"
            if was_busy:
                text += "⚠️ Faol buyurtmangiz olib tashlandi va boshqa haydovchilarga berildi.\n"
            text += "\n📞 Savollar bo‘lsa admin bilan bog‘laning."
    
            bot.send_message(driver_id, text, reply_markup=markup)
        except Exception as e:
            print(f"Blok xabari yuborilmadi: {e}")
    
        result = f"✅ Haydovchi *{driver_id}* bloklandi.\n🕐 Muddat: {until_str}"
        if order_reset:
            result += "\n🔄 Faol buyurtmasi qayta tarqatildi."
    
        bot.send_message(message.chat.id, result, parse_mode="Markdown")


    @bot.message_handler(commands=['unblock_driver'])
    def admin_unblock_driver(message):
        if not is_admin(message.from_user.id):
            return bot.send_message(message.chat.id, "❌ Huquq yo‘q!")
    
        try:
            driver_id = int(message.text.split()[1])
        except:
            return bot.send_message(message.chat.id, "❗ /unblock_driver <haydovchi_id>")
    
        driver_str_id = str(driver_id)
        drivers = load_json(DRIVER_FILE)
        blocked_data = load_json(TEMP_BLOCK_FILE)
    
        if driver_str_id not in drivers:
            return bot.send_message(message.chat.id, "❌ Haydovchi topilmadi!")
    
        # Blokni ochish
        if "blocked" in drivers[driver_str_id]:
            del drivers[driver_str_id]["blocked"]
        
        # temp_blocks dan ham o‘chirish
        if driver_str_id in blocked_data:
            del blocked_data[driver_str_id]
            save_json(TEMP_BLOCK_FILE, blocked_data)
    
        save_json(DRIVER_FILE, drivers)
    
        try:
            bot.send_message(
                driver_id,
                "✅ Siz blokdan chiqarildingiz!\n🚀 Endi ishni boshlashingiz mumkin.\n/start buyrug‘ini bosing."
            )
        except:
            pass
    
        bot.send_message(message.chat.id, f"✅ Haydovchi *{driver_id}* blokdan chiqarildi.", parse_mode="Markdown")
    
    # ================= TUGALLANGAN BUYURTMANI QIDIRISH =================
    @bot.message_handler(commands=['find_finished'])
    def find_finished(message):
        if not is_admin(message.chat.id):
            bot.send_message(message.chat.id, "❌ Siz admin emassiz!")
            return

        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.send_message(
                message.chat.id,
                "❗ Foydalanish:\n"
                "/find_finished <buyurtma_id>\n\n"
                "Masalan: /find_finished 123"
            )
            return

        order_id = parts[1].strip()
        finished = load_json(FINISHED_ORDERS_FILE)

        if order_id not in finished:
            bot.send_message(message.chat.id, f"❌ {order_id} ID li tugallangan buyurtma topilmadi.")
            return

        order = finished[order_id]

        # Vaqtni chiroyli formatda
        finish_time = order.get("finish_time", "Noma'lum")
        try:
            dt = datetime.fromtimestamp(int(finish_time))
            finish_time_str = dt.strftime("%d.%m.%Y %H:%M")
        except:
            finish_time_str = finish_time

        # Manzillar
        from_addr = order.get("from_address", "Noma'lum")
        to_addr = order.get("to_address", "Noma'lum")

        # Buyurtmachi ma'lumotlari
        user_id = order.get("user_id", "Noma'lum")
        user_phone = order.get("phone", "Telefon kiritilmagan")

        # Haydovchi ma'lumotlari
        driver_id = order.get("driver_id", "Noma'lum")
        drivers = load_json(DRIVER_FILE)
        driver_info = drivers.get(driver_id, {})
        driver_name = driver_info.get("fullname", "Ism kiritilmagan")
        driver_phone = driver_info.get("phone", "Telefon yo‘q")
        car_info = f"{driver_info.get('car_model', '')} {driver_info.get('car_color', '')} {driver_info.get('car_number', '')}".strip()

        # Narxlar
        total_price = int(order.get("total", 0))
        commission = int(order.get("commission", 0))
        driver_earned = total_price - commission

        text = (
            f"✅ <b>Tugallangan buyurtma topildi!</b>\n\n"
            f"🆔 <b>ID:</b> {order_id}\n\n"
            
            f"👤 <b>Buyurtmachi</b>\n"
            f"   • ID: {user_id}\n"
            f"   • 📞 Telefon: <code>{user_phone}</code>\n\n"
            
            f"🚖 <b>Haydovchi</b>\n"
            f"   • Ism: {driver_name}\n"
            f"   • ID: {driver_id}\n"
            f"   • 📞 Telefon: <code>{driver_phone}</code>\n"
            f"   • 🚘 Mashina: {car_info or 'Ma’lumot yo‘q'}\n\n"
            
            f"📍 <b>Yuk olish joyi:</b>\n{from_addr}\n\n"
            f"📍 <b>Yetkazish joyi:</b>\n{to_addr}\n\n"
            
            f"📏 Masofa: {order.get('distance', '-')} km\n"
            f"⚖️ Og‘irlik: {order.get('weight', '-')} kg\n"
            f"📝 Izoh: {order.get('comment', '-')}\n\n"
            
            f"💰 Umumiy narx: {total_price:,} so‘m\n"
            f"📉 Komissiya (5%): {commission:,} so‘m\n"
            f"💳 Haydovchiga tushgan: {driver_earned:,} so‘m\n\n"
            
            f"🕒 Tugallangan vaqt: {finish_time_str}"
        )

        # Yuk rasmi
        if order.get("photo"):
            try:
                bot.send_photo(
                    message.chat.id,
                    order["photo"],
                    caption=text,
                    parse_mode="HTML"
                )
                return
            except Exception as e:
                print(f"Rasm yuborishda xato: {e}")

        bot.send_message(message.chat.id, text, parse_mode="HTML")

    # ================= ADMIN BILAN BOG‘LANISH =================
    @bot.message_handler(func=lambda m: m.text == "📞 Admin bilan bog‘lanish")
    def contact_admin(message):
        user_id = message.chat.id

        remove_markup = telebot.types.ReplyKeyboardRemove()

        bot.send_message(
            user_id,
            "✍️ Admin bilan bog‘lanish uchun xabaringizni yozing (matn, rasm, video, fayl yoki ovozli xabar).\n\n"
            "Javobni shu yerda kutib turing.",
            reply_markup=remove_markup
        )

        admin_step[user_id] = "wait_admin_msg"

    @bot.message_handler(
        func=lambda m: admin_step.get(m.chat.id) == "wait_admin_msg",
        content_types=['text', 'photo', 'video', 'document', 'voice']
    )
    def send_to_admin(message):
        user_id = message.chat.id
        admin_step[user_id] = None

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✉️ Javob berish", callback_data=f"reply_{user_id}")
        )

        caption = getattr(message, 'caption', '') or ""

        if message.content_type == 'text':
            bot.send_message(
                ADMIN_ID,
                f"👤 Foydalanuvchi ID: {user_id}\n✉️ Xabar: {message.text}",
                reply_markup=markup
            )

        elif message.content_type == 'photo':
            bot.send_photo(
                ADMIN_ID,
                message.photo[-1].file_id,
                caption=f"👤 Foydalanuvchi ID: {user_id}\n{caption}",
                reply_markup=markup
            )

        elif message.content_type == 'video':
            bot.send_video(
                ADMIN_ID,
                message.video.file_id,
                caption=f"👤 Foydalanuvchi ID: {user_id}\n{caption}",
                reply_markup=markup
            )

        elif message.content_type == 'document':
            bot.send_document(
                ADMIN_ID,
                message.document.file_id,
                caption=f"👤 Foydalanuvchi ID: {user_id}\n{caption}",
                reply_markup=markup
            )

        elif message.content_type == 'voice':
            bot.send_voice(
                ADMIN_ID,
                message.voice.file_id,
                caption=f"👤 Foydalanuvchi ID: {user_id}\n{caption}",
                reply_markup=markup
            )

        bot.send_message(user_id, "✅ Xabaringiz admin ga yuborildi. Tez orada javob beriladi.")

    # ================= ADMIN JAVOB BERISH =================
    @bot.callback_query_handler(func=lambda call: call.data.startswith("reply_"))
    def admin_reply_inline(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "❌ Sizda bu huquq yo‘q!")
            return

        user_id = int(call.data.split("_")[1])
        selected_driver[ADMIN_ID] = user_id
        admin_step[ADMIN_ID] = "wait_admin_reply"

        bot.send_message(
            ADMIN_ID,
            "✍️ Foydalanuvchiga javob yozing (matn, rasm, video, fayl yoki ovozli xabar bo‘lishi mumkin)."
        )

        bot.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=None
        )

    def send_admin_reply_with_buttons(user_id, content_type, file_id=None, text=None):
        user_markup = InlineKeyboardMarkup()
        user_markup.add(
            InlineKeyboardButton("✉️ Yana javob berish", callback_data=f"continue_support_{user_id}")
        )

        admin_markup = InlineKeyboardMarkup()
        admin_markup.add(
            InlineKeyboardButton("🔴 Suhbatni yakunlash", callback_data=f"close_support_{user_id}")
        )

        if content_type == "text":
            bot.send_message(
                user_id,
                f"👨‍💼 *Admin javobi:*\n\n{text}",
                parse_mode="Markdown",
                reply_markup=user_markup
            )
        elif content_type == "photo":
            bot.send_photo(user_id, file_id, caption="👨‍💼 Admin javobi:", reply_markup=user_markup)
        elif content_type == "video":
            bot.send_video(user_id, file_id, caption="👨‍💼 Admin javobi:", reply_markup=user_markup)
        elif content_type == "document":
            bot.send_document(user_id, file_id, caption="👨‍💼 Admin javobi:", reply_markup=user_markup)
        elif content_type == "voice":
            bot.send_voice(user_id, file_id, caption="👨‍💼 Admin javobi:", reply_markup=user_markup)

        bot.send_message(
            ADMIN_ID,
            "✅ Javob foydalanuvchiga yuborildi",
            reply_markup=admin_markup
        )

    @bot.message_handler(
        func=lambda m: admin_step.get(m.chat.id) == "wait_admin_reply",
        content_types=['text', 'photo', 'video', 'document', 'voice']
    )
    def send_reply_to_user(message):
        if message.chat.id != ADMIN_ID:
            return

        user_id = selected_driver.get(ADMIN_ID)
        if not user_id:
            return

        if message.content_type == "text":
            send_admin_reply_with_buttons(user_id, "text", text=message.text)
        elif message.content_type == "photo":
            send_admin_reply_with_buttons(user_id, "photo", file_id=message.photo[-1].file_id)
        elif message.content_type == "video":
            send_admin_reply_with_buttons(user_id, "video", file_id=message.video.file_id)
        elif message.content_type == "document":
            send_admin_reply_with_buttons(user_id, "document", file_id=message.document.file_id)
        elif message.content_type == "voice":
            send_admin_reply_with_buttons(user_id, "voice", file_id=message.voice.file_id)

        admin_step[ADMIN_ID] = None
        selected_driver[ADMIN_ID] = None

    # ================= FOYDALANUVCHI DAVOM ETTIRISH =================
    @bot.callback_query_handler(func=lambda call: call.data.startswith("continue_support_"))
    def continue_support(call):
        user_id = call.from_user.id
        expected_id = int(call.data.split("_")[2])

        if user_id != expected_id:
            bot.answer_callback_query(call.id, "❌ Bu tugma siz uchun emas!")
            return

        bot.send_message(
            user_id,
            "✍️ Adminga yana javob yozing (matn, rasm, video, fayl yoki ovozli xabar)."
        )
        admin_step[user_id] = "wait_admin_msg"
        bot.answer_callback_query(call.id, "Javob yozish boshlandi")
        
 

   
        

    # ================= SUHBATNI YAKUNLASH =================
    @bot.callback_query_handler(func=lambda call: call.data.startswith("close_support_"))
    def close_support_chat(call):
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "❌ Sizda bu huquq yo‘q!")
            return

        try:
            user_id = int(call.data.split("_")[2])
        except:
            bot.answer_callback_query(call.id, "❌ Xatolik yuz berdi!")
            return

        try:
            bot.send_message(
                user_id,
                "🔴 Suhbat yakunlandi.\n"
                "Murojaatingiz uchun rahmat! 😊\n\n"
                "Botdan foydalanishni davom ettirishingiz mumkin.\n\n"
                "/start buyrug‘ini bosing."
            )
        except:
            pass

        bot.send_message(ADMIN_ID, f"🔴 ID {user_id} bilan suhbat yakunlandi.")
        
        
     
        
        
        