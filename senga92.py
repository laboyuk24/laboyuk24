# main.py
import telebot
import json
import os
import time
import threading
import math
import re
import requests

from datetime import datetime  # fayl boshida import qilingan bo‘lsin
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from admin import register_admin_handlers

# ========== SOZLAMALAR ==========
TOKEN = "8328030526:AAF_Nw7D8L58rBWbl4fjYY0o1iXR1gT5eoA"
AUTO_CHECK_INTERVAL = 5  # sekund
NEARBY_THRESHOLD_KM = 5.0  # km
ADMIN_IDS = [8335295626]

# ========== FAYL NOMLARI ==========
DRIVER_FILE = "drivers.json"
ORDERS_FILE = "orders.json"
USERS_FILE = "users.json"
CANCEL_LIMIT_FILE = "cancel_limits.json"
DRIVER_LOC_FILE = "driver_locations.json"
ORDER_COUNTER_FILE = "order_counter.json"
FINISHED_ORDERS_FILE = "finished_orders.json"
GLOBAL_STATS_FILE = "global_stats.json"




bot = telebot.TeleBot(TOKEN)
GOOGLE_API_KEY = "AIzaSyB5wIhBkwLJPJIJrZNMwRxRBOcG_xgO5to"  # Bu yerga sizning Google API key-ni qo'ying


def get_drivers():
    return load_json(DRIVER_FILE)

def get_driver(user_id):
    drivers = load_json(DRIVER_FILE)
    return drivers.get(str(user_id))

def save_driver(user_id, data):
    drivers = load_json(DRIVER_FILE)
    drivers[str(user_id)] = data
    save_json(DRIVER_FILE, drivers)


def count_finished_orders_for_driver(driver_id):
    finished = load_json(FINISHED_ORDERS_FILE)
    cnt = 0
    for order_id, order in finished.items():
        if str(order.get("driver_id")) == str(driver_id):
            cnt += 1
    return cnt



def calculate_nearby_stats_for_driver(center_lat, center_lon):
    """Haydovchi lokatsiyasidan 5 km ichidagi statistikani hisoblaydi"""
    driver_locs = load_json(DRIVER_LOC_FILE)
    orders_local = load_json(ORDERS_FILE)

    free_drivers = 0
    busy_drivers = 0
    open_orders = 0

    center_lat = float(center_lat)
    center_lon = float(center_lon)

    # 5 km ichidagi haydovchilar
    for driver_id, loc in driver_locs.items():
        if not is_driver_online(driver_id):
            continue

        try:
            d_lat = float(loc["lat"])
            d_lon = float(loc["lon"])
        except:
            continue

        dist = distance_km(center_lat, center_lon, d_lat, d_lon)
        if dist > NEARBY_THRESHOLD_KM:  # 5 km
            continue

        if driver_id in driver_active_order:
            busy_drivers += 1
        else:
            free_drivers += 1

    # 5 km ichidagi ochiq buyurtmalar
    for order in orders_local.values():
        if order.get("status") != "open":
            continue

        try:
            o_lat = float(order["from"]["lat"])
            o_lon = float(order["from"]["lon"])
        except:
            continue

        dist = distance_km(center_lat, center_lon, o_lat, o_lon)
        if dist <= NEARBY_THRESHOLD_KM:
            open_orders += 1

    return {
        "free_drivers": free_drivers,
        "busy_drivers": busy_drivers,
        "total_drivers": free_drivers + busy_drivers,
        "open_orders": open_orders
    }


def load_global_stats():
    if not os.path.exists(GLOBAL_STATS_FILE):
        default = {
            "total_users": 0,          # Faqat buyurtma bergan foydalanuvchilar
            "total_drivers": 0,        # Ro'yxatdan o'tgan haydovchilar
            "total_orders": 0          # Umumiy yaratilgan buyurtmalar
        }
        save_json(GLOBAL_STATS_FILE, default)
        return default
    return load_json(GLOBAL_STATS_FILE)

def update_global_stats():
    """Har safar kerak bo‘lganda yangilaydi"""
    stats = load_global_stats()
    
    # Jami haydovchilar
    stats["total_drivers"] = len(load_json(DRIVER_FILE))
    
    # Jami buyurtma bergan foydalanuvchilar
    orders_local = load_json(ORDERS_FILE)
    unique_users = set()
    for order in orders_local.values():
        if order.get("user_id"):
            unique_users.add(order["user_id"])
    stats["total_users"] = len(unique_users)
    
    # Jami buyurtmalar
    stats["total_orders"] = len(orders_local)
    
    save_json(GLOBAL_STATS_FILE, stats)
    return stats



def get_google_distance(from_lat, from_lon, to_lat, to_lon):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": f"{from_lat},{from_lon}",
        "destinations": f"{to_lat},{to_lon}",
        "mode": "driving",
        "language": "uz",
        "key": GOOGLE_API_KEY
    }

    response = requests.get(url, params=params)
    if response.status_code != 200:
        return None, None

    data = response.json()
    try:
        element = data['rows'][0]['elements'][0]
        distance_m = element['distance']['value']  # metr
        duration_s = element['duration']['value']  # sekund
        return distance_m / 1000, duration_s / 60  # km va daqiqa
    except:
        return None, None


def get_address_from_coords(lat, lon):
    """Koordinatalardan manzil nomini olish (Reverse Geocoding)"""
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "latlng": f"{lat},{lon}",
        "key": GOOGLE_API_KEY,
        "language": "uz"  # O‘zbek tilida natija (agar mavjud bo‘lsa), aks holda rus/ingliz
    }

    try:
        response = requests.get(url, params=params)
        if response.status_code != 200:
            return "Manzil nomi topilmadi"

        data = response.json()
        if data["status"] == "OK" and data["results"]:
            # Eng aniq natijani olamiz
            return data["results"][0]["formatted_address"]
        else:
            return "Manzil nomi topilmadi"
    except Exception as e:
        print("Geocoding xatosi:", e)
        return "Manzil nomi topilmadi"


def check_blocked_and_respond(chat_id):
    drivers_local = load_json(DRIVER_FILE)
    user_id = str(chat_id)

    if user_id in drivers_local and drivers_local[user_id].get("blocked", False):
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("📞 Admin bilan bog‘lanish")
        bot.send_message(
            chat_id,
            "🚫 Siz bloklangansiz!\nBu amalni bajarib bo‘lmaydi.\nAdmin bilan bog‘laning.",
            reply_markup=markup
        )
        return True
    return False

# Narxni hisoblash (misol)
def calculate_price(distance_km):
    base_price = 5000       # boshlang'ich summa
    per_km_price = 1000     # 1 km narxi

    extra_distance_limit = 8    # km
    extra_fixed_price = 50000   # ustama (bir martalik)

    # Asosiy narx
    price = base_price + distance_km * per_km_price

    # ✅ USTAMA: agar 8 km dan oshsa, bir marta 50 000 qo‘shiladi
    if distance_km > extra_distance_limit:
        price += extra_fixed_price

    return int(round(price))


# ========== YANGI FUNKSIYALAR ==========
def is_driver_online(driver_id):
    """Haydovchi onlayn yoki yo'qligini tekshiradi"""
    # 1. Xotira holatini tekshirish
    if live_location_active.get(driver_id, False):
        return True

    # 2. Fayldagi oxirgi lokatsiya vaqtini tekshirish (5 daqiqa ichida)
    driver_locs = load_json(DRIVER_LOC_FILE)
    if driver_id in driver_locs:
        last_update = driver_locs[driver_id].get("time", 0)
        current_time = int(time.time())
        # Agar 5 daqiqa (300 sekund) ichida yangilangan bo'lsa, onlayn deb hisoblaymiz
        if current_time - last_update <= 300:
            return True

    return False

#Tartibli va takrorlanmas buyurtma ID sini olish
def get_next_order_id():
    """Tartibli va takrorlanmas buyurtma ID sini olish"""
    counter_data = load_json(ORDER_COUNTER_FILE)
    current_id = counter_data.get("last_order_id", 0)
    next_id = current_id + 1

    counter_data["last_order_id"] = next_id
    save_json(ORDER_COUNTER_FILE, counter_data)

    return str(next_id)

def reset_order_counter():
    """Buyurtma hisoblagichini nolga tiklash (admin uchun)"""
    counter_data = {"last_order_id": 0}
    save_json(ORDER_COUNTER_FILE, counter_data)
    return "✅ Buyurtma hisoblagichi nolga tiklandi"

# ========== YANGI FUNKSIYALAR ==========
def is_driver_active_and_online(driver_id):
    """Haydovchi faqat ishni boshlagan va onlayn bo'lganda True qaytaradi"""
    # 1. Haydovchi ishni boshlaganmi?
    if not live_location_active.get(driver_id, False):
        return False

    # 2. Haydovchi onlaynmi?
    return is_driver_online(driver_id)


# ========== YORDAMCHI FUNKSIYALAR ==========
def load_json(filename):
    if not os.path.exists(filename):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4, ensure_ascii=False)
        return {}
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4, ensure_ascii=False)
        return {}

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def distance_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1_r, lon1_r, lat2_r, lon2_r = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = math.sin(dlat/2)**2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def can_cancel(user_id):
    now = int(time.time())
    day_seconds = 24 * 3600
    d = cancel_limits.get(user_id)
    if not d:
        cancel_limits[user_id] = {"count": 0, "last_reset": now}
        save_json(CANCEL_LIMIT_FILE, cancel_limits)
        return True
    if now - d.get("last_reset", 0) > day_seconds:
        cancel_limits[user_id] = {"count": 0, "last_reset": now}
        save_json(CANCEL_LIMIT_FILE, cancel_limits)
        return True
    return d.get("count", 0) < 3

def register_cancel(user_id):
    now = int(time.time())
    if user_id not in cancel_limits:
        cancel_limits[user_id] = {"count": 1, "last_reset": now}
    else:
        d = cancel_limits[user_id]
        if now - d.get("last_reset", 0) > 24 * 3600:
            cancel_limits[user_id] = {"count": 1, "last_reset": now}
        else:
            cancel_limits[user_id]["count"] = d.get("count", 0) + 1
    save_json(CANCEL_LIMIT_FILE, cancel_limits)

def remaining_cancels(user_id):
    d = cancel_limits.get(user_id)
    if not d:
        return 3
    now = int(time.time())
    if now - d.get("last_reset", 0) > 24 * 3600:
        return 3
    return max(0, 3 - d.get("count", 0))

def save_driver_location(uid, lat, lon):
    try:
        driver_locations_local = load_json(DRIVER_LOC_FILE)
        driver_locations_local[uid] = {
            "lat": float(lat),
            "lon": float(lon),
            "time": int(time.time()),
            "online": True
        }
        save_json(DRIVER_LOC_FILE, driver_locations_local)
        # Xotira holatini ham yangilash
        live_location_active[uid] = True
    except Exception as e:
        print("save_driver_location error:", e)

def reset_notified_for_order(order_id):
    for driver_id in list(_notified_near_orders.keys()):
        if order_id in _notified_near_orders[driver_id]:
            _notified_near_orders[driver_id].remove(order_id)
        if not _notified_near_orders[driver_id]:
            del _notified_near_orders[driver_id]

def cleanup_other_drivers_messages(order_id, winner_driver):
    """
    order_id: olingan buyurtma ID
    winner_driver: buyurtmani olgan haydovchi ID
    """

    for did, orders_map in sent_order_messages.items():
        if order_id in orders_map and did != winner_driver:
            ids = orders_map[order_id]

            # ✅ eski format bo‘lsa ham ishlasin (bitta int bo‘lsa)
            if isinstance(ids, int):
                ids = [ids]

            for mid in ids:
                try:
                    bot.delete_message(did, mid)
                except:
                    pass

    # ✅ xotiradan ham o'chiramiz
    for did in list(sent_order_messages.keys()):
        sent_order_messages[did].pop(order_id, None)




def notify_if_not_taken_later(order_id):
    time.sleep(10)  # 3 daqiqa

    orders = load_json(ORDERS_FILE)
    order = orders.get(order_id)

    if not order or order.get("status") != "open":
        return  # olingan yoki yo‘q bo‘lib ketgan

    user_id = order["user_id"]

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton(
            "✅ Ha", callback_data=f"resend_yes_{order_id}"
        ),
        telebot.types.InlineKeyboardButton(
            "❌ Bekor", callback_data=f"resend_no_{order_id}"
        )
    )

    bot.send_message(
        user_id,
        "❗ Buyurtma haydovchilar tomonidan olinmadi.\nYana yuboraylikmi?",
        reply_markup=markup
    )


def send_near_order(
    driver_id,
    oid,
    order,
    pickup_distance,          # haydovchidan pickupgacha km
    delivery_distance,        # pickupdan yetkazishgacha km
    price=None,
    pickup_duration=None,     # haydovchidan pickupgacha vaqt (min)
    delivery_duration=None    # pickupdan yetkazishgacha vaqt (min)
):
    """
    driver_id: haydovchi chat_id
    oid: buyurtma ID
    order: buyurtma dict
    """

    driver_id = str(driver_id)

    # 🚫 BLOKLANGAN bo‘lsa — umuman yubormaymiz
    drivers_local = load_json(DRIVER_FILE)
    if drivers_local.get(driver_id, {}).get("blocked", False):
        return

    # ❌ Oldin yuborilgan bo‘lsa — qayta yubormaymiz
    if oid in _notified_near_orders.get(driver_id, set()):
        return

    # 🔒 Narxni faqat buyurtmadan olamiz
    if price is None:
        price = order.get("price") or order.get("total")

    if price is not None:
        try:
            price = int(round(float(price)))
        except:
            price = None

    # 🧾 Asosiy matn
    text = (
        f"📦 *Yangi buyurtma!*\n"
        f"🆔 ID: {oid}\n"
        f"📍 Yukni olishgacha masofa: {round(pickup_distance, 2)} km\n"
    )

    if pickup_duration is not None:
        text += (
            f"⏱️ Haydovchidan yukni olish joyigacha vaqt: "
            f"{round(pickup_duration, 1)} min\n"
        )

    text += f"📍 Yetkazish masofasi: {round(delivery_distance, 2)} km\n"

    if delivery_duration is not None:
        text += (
            f"⏱️ Yukni yetkazish joyigacha vaqt: "
            f"{round(delivery_duration, 1)} min\n"
        )

    text += (
        f"⚖️ Og'irlik: {order.get('weight', '-')} kg\n"
        f"📝 Komment: {order.get('comment', '-')}\n"
    )

    if price is not None:
        text += f"💰 Narx: {price:,} so'm".replace(",", " ")

    # ⌨️ Tugmalar
    markup = telebot.types.InlineKeyboardMarkup()

    if order.get("photo"):
        markup.add(
            telebot.types.InlineKeyboardButton(
                "🖼️ Yuk rasmi",
                callback_data=f"view_photo_{oid}"
            )
        )

    markup.add(
        telebot.types.InlineKeyboardButton(
            "📥 Buyurtmani olish",
            callback_data=f"take_{oid}"
        )
    )

    try:
        ids = []

        # 📍 Pickup (matn + lokatsiya)
        m1 = bot.send_message(driver_id, "📍 Yukni olish joyi")
        ids.append(m1.message_id)

        loc1 = bot.send_location(
            driver_id,
            order["from"]["lat"],
            order["from"]["lon"]
        )
        ids.append(loc1.message_id)

        # 📍 Delivery (matn + lokatsiya)
        m2 = bot.send_message(driver_id, "📍 Yetkazish manzili")
        ids.append(m2.message_id)

        loc2 = bot.send_location(
            driver_id,
            order["to"]["lat"],
            order["to"]["lon"]
        )
        ids.append(loc2.message_id)

        # 📦 Buyurtma matni
        msg = bot.send_message(
            driver_id,
            text,
            parse_mode="Markdown",
            reply_markup=markup
        )
        ids.append(msg.message_id)

        # ✅ hamma message_id larni saqlaymiz
        sent_order_messages.setdefault(driver_id, {})
        sent_order_messages[driver_id][oid] = ids

    except Exception as e:
        print(f"Error sending order {oid} to {driver_id}: {e}")
        return

    _notified_near_orders.setdefault(driver_id, set()).add(oid)




def allow_finish_later(driver_id, order_id, minutes):
    # Yetkazib berish vaqti tugaguncha kutamiz
    time.sleep(int(minutes * 60))

    orders = load_json(ORDERS_FILE)

    # Buyurtma mavjudmi?
    if order_id not in orders:
        return

    order = orders[order_id]

    # Faqat olingan buyurtma bo‘lsa
    if order.get("status") != "taken":
        return

    # Driver_id faqat buyurtmani olgan haydovchi bilan mos kelishini tekshirish
    actual_driver_id = str(order.get("driver_id"))
    if str(driver_id) != actual_driver_id:
        return  # Xabar boshqa haydovchiga yuborilmaydi

    # Endi yopish mumkin
    orders[order_id]["status"] = "can_finish"
    save_json(ORDERS_FILE, orders)

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(
            "✅ Buyurtmani yopish",
            callback_data=f"finish_{order_id}"
        )
    )

    bot.send_message(
        driver_id,
        "⏱️ Yetkazib berish vaqti yakunlandi.\n"
        "Agar yuk yetkazilgan bo‘lsa, buyurtmani yopishingiz mumkin.",
        reply_markup=markup
    )


def auto_send_near_orders_once(order_id):
    driver_locs_local = load_json(DRIVER_LOC_FILE)
    orders_local = load_json(ORDERS_FILE)
    drivers_local = load_json(DRIVER_FILE)

    order = orders_local.get(order_id)
    if not order or order.get("status") != "open":
        return

    sent = False  # hech kimga yuborilmagan

    for driver_id, loc in driver_locs_local.items():
        if not is_driver_online(driver_id):
            continue

    # 🚫 BLOKLANGAN bo‘lsa — umuman yubormaymiz
        if drivers_local.get(str(driver_id), {}).get("blocked", False):
            continue

        driver_balance = float(drivers_local.get(driver_id, {}).get("balance", 0))
        if driver_balance <= 0:
            if not driver_warned.get(driver_id):
                try:
                    bot.send_message(
                        driver_id,
                        "📦 Yangi buyurtma!\n\n⚠️ Balansingiz 0 so‘m!\n"
                        "❌ Siz hozircha buyurtma qabul qila olmaysiz.\n"
                        "💳 Iltimos, balansni to‘ldiring."
                    )
                except:
                    pass
                driver_warned[driver_id] = True
            continue

        driver_warned.pop(driver_id, None)

        if driver_id in order.get("blacklist_drivers", []):
            continue

        if driver_id in driver_active_order:
            continue

        try:
            lat_d = float(loc["lat"])
            lon_d = float(loc["lon"])
            lat_o = float(order["from"]["lat"])
            lon_o = float(order["from"]["lon"])
            lat_to = float(order["to"]["lat"])
            lon_to = float(order["to"]["lon"])
        except:
            continue

        # 🚗 Driver → Pickup masofa
        pickup_distance, pickup_duration = get_google_distance(lat_d, lon_d, lat_o, lon_o)
        if pickup_distance is None:
            pickup_distance = distance_km(lat_d, lon_d, lat_o, lon_o)
            pickup_duration = pickup_distance / 40 * 60

        # 📦 Pickup → Delivery masofa
        delivery_distance, delivery_duration = get_google_distance(lat_o, lon_o, lat_to, lon_to)
        if delivery_distance is None:
            delivery_distance = distance_km(lat_o, lon_o, lat_to, lon_to)
            delivery_duration = delivery_distance / 40 * 60

        if pickup_distance <= NEARBY_THRESHOLD_KM:
            price = order.get("price") or order.get("total")

            send_near_order(
                driver_id,
                order_id,
                order,
                pickup_distance=round(pickup_distance, 2),
                delivery_distance=round(delivery_distance, 2),
                price=price,
                pickup_duration=round(pickup_duration, 1),
                delivery_duration=round(delivery_duration, 1)
            )

            sent = True

            # sent_to_drivers ro'yxatini yangilash (xotirada)
            order.setdefault("sent_to_drivers", [])
            if driver_id not in order["sent_to_drivers"]:
                order["sent_to_drivers"].append(driver_id)

    # ==================================================================
    # 1. Agar buyurtma kamida bitta haydovchiga yuborilgan bo'lsa
    # ==================================================================
    if sent:
        # Fayldagi buyurtmani tekshirib, notify_started yo'qligini aniqlaymiz
        if not orders_local[order_id].get("notify_started"):
            orders_local[order_id]["notify_started"] = True
            save_json(ORDERS_FILE, orders_local)  # Saqlaymiz!

            threading.Thread(
                target=notify_if_not_taken_later,
                args=(order_id,),
                daemon=True
            ).start()

    # ==================================================================
    # 2. Agar hech qanday haydovchiga yuborilmagan bo'lsa → foydalanuvchiga xabar
    # ==================================================================
    else:
        user_id = order.get("user_id")
        if user_id and not order.get("no_driver_notified"):  # bir marta xabar berish uchun flag
            try:
                bot.send_message(
                    user_id,
                    "😔 Hozircha yaqin atrofdagi haydovchi topilmadi.\n\n"
                    "⏳ Biroz kutib turing — yangi haydovchi onlayn bo‘lishi bilan buyurtmangiz avtomatik yuboriladi.\n"
                    "Yoki buyurtmani \"Buyurtmalarim\" bo‘limidan bekor qilishingiz mumkin."
                )
                # Keyingi safar bu xabar takrorlanmasligi uchun flag qo‘yamiz
                orders_local[order_id]["no_driver_notified"] = True
                save_json(ORDERS_FILE, orders_local)
            except:
                pass

    # ==================================================================
    # Har ikki holatda ham sent_to_drivers va boshqa o‘zgarishlarni saqlaymiz
    # ==================================================================
    save_json(ORDERS_FILE, orders_local)


def save_finished_order(order_id, order_data):
    finished = load_json(FINISHED_ORDERS_FILE)
    finished[order_id] = order_data
    save_json(FINISHED_ORDERS_FILE, finished)




# Yuklash
drivers = load_json(DRIVER_FILE)
orders = load_json(ORDERS_FILE)
cancel_limits = load_json(CANCEL_LIMIT_FILE)
driver_locations = load_json(DRIVER_LOC_FILE)

# ========== IN-MEMORY HOLATLAR ==========
# Buyurtmachi "🚚 Sizning buyurtmangiz tanlandi!" xabarini o‘chirish uchun
user_take_messages = {}  # {order_id: message_id}

driver_state = {}
edit_state = {}
driver_active_order = {}
order_flow = {}
live_location_active = {}
_notified_near_orders = {}
sent_order_messages = {}
driver_status = {}
last_location_message = {}
driver_online = {}
driver_warned = {}
# ===== REAL GPS KM HISOBI =====
driver_route = {}
# driver_route[driver_id] = {
#   "last_lat": float,
#   "last_lon": float,
#   "km": float
# }


# ========== CAR MODELS & COLORS ==========
CAR_MODELS = ["Labo"]
CAR_COLORS = ["Oq", "Qora", "Kulrang", "Ko'k"]

# ========== START COMMAND & KEYBOARD ==========
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = str(message.chat.id)

    # Referal ushlash
    parts = message.text.split()
    if len(parts) > 1:
        ref_id = parts[1]
        if ref_id != user_id:
            order_flow.setdefault(user_id, {})
            order_flow[user_id]["referred_by"] = ref_id

    drivers_local = load_json(DRIVER_FILE)

    # 🔴 BLOKLANGAN HAYDOVCHI — faqat bitta tugma
    if user_id in drivers_local and drivers_local[user_id].get("blocked", False):
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("📞 Admin bilan bog‘lanish")

        bot.send_message(
            message.chat.id,
            "🚫 Siz admin tomonidan bloklandingiz!\n\n"
            "❌ Buyurtma qabul qila olmaysiz, ishlay olmaysiz va barcha funksiyalar cheklangan.\n\n"
            "📞 Blokdan chiqarish yoki savollar uchun admin bilan bog‘laning.",
            reply_markup=markup
        )
        return

    # 🟢 ODDIY HOLAT — standart klaviatura
    status = driver_status.get(user_id, "offline")

    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📦 Buyurtma berish", "📦 Buyurtmalarim")
    markup.add("🚖 Haydovchi bo'lish", "👤 Haydovchi haqida")
    markup.add("📞 Admin bilan bog‘lanish")

    if user_id in drivers_local:
        if status == "online":
            markup.add("🟢 Siz onlinesiz", "❌ Ishni tugatish")
        else:
            markup.add("✅ Ishni boshlash", "🔴 Siz offlinesiz")

    bot.send_message(message.chat.id, "Salom! Xush kelibsiz!", reply_markup=markup)


@bot.message_handler(commands=['stats'])
def show_driver_stats(message):
    driver_id = str(message.chat.id)

    # Faqat haydovchilar ishlatishi mumkin
    drivers_local = load_json(DRIVER_FILE)
    if driver_id not in drivers_local:
        bot.send_message(
            message.chat.id,
            "❗ Bu buyruq faqat ro'yxatdan o'tgan haydovchilar uchun mavjud."
        )
        return

    # Lokatsiya borligini tekshirish
    driver_locs = load_json(DRIVER_LOC_FILE)
    if driver_id not in driver_locs or not is_driver_online(driver_id):
        bot.send_message(
            message.chat.id,
            "📍 Hozircha sizning lokatsiyangiz yo‘q.\n\n"
            "Statistikani ko‘rish uchun:\n"
            "1. «✅ Ishni boshlash» tugmasini bosing\n"
            "2. Jonli lokatsiya yuboring\n"
            "Keyin yana /stats deb yozing."
        )
        return

    loc = driver_locs[driver_id]
    driver_lat = float(loc["lat"])
    driver_lon = float(loc["lon"])

    # Taxminiy manzil nomi
    address = get_address_from_coords(driver_lat, driver_lon)
    if len(address) > 70:
        address = address[:67] + "..."

    # 5 km radius statistikasi
    stats_near = calculate_nearby_stats_for_driver(driver_lat, driver_lon)

    # Umumiy statistika
    global_stats = update_global_stats()  # Har safar yangi hisoblaydi

    total_all_users = global_stats["total_users"] + global_stats["total_drivers"]

    # Haydovchi o‘z holati
    my_status = "🟢 Bo'sh" if driver_id not in driver_active_order else "🔴 Band"

    text = (
        f"📊 <b>Atrofingizdagi statistika (5 km radius)</b>\n"
        f"📍 Joriy joyingiz: <i>{address}</i>\n"
        f"🚖 Siz: <b>{my_status}</b>\n\n"
        f"🟢 Bo'sh haydovchilar: <b>{stats_near['free_drivers']}</b> nafar\n"
        f"🔴 Band haydovchilar: <b>{stats_near['busy_drivers']}</b> nafar\n"
        
        f"📦 Olinmagan buyurtmalar: <b>{stats_near['open_orders']}</b> ta\n\n"
        f"{'─' * 15}\n\n"
        f"🌍 <b>Umumiy bot statistikasi</b>\n\n"
        f"👤 Umumiy foydalanuvchilar: <b>{total_all_users}</b> nafar\n"
        f"👥 Buyurtmachilar: <b>{global_stats['total_users']}</b> nafar\n"
        f"🚖 Haydovchilar: <b>{global_stats['total_drivers']}</b> nafar\n"
        
        f"📦 Jami buyurtmalar: <b>{global_stats['total_orders']}</b> ta\n\n"
    )

    if stats_near['open_orders'] > 0:
        text += "🔥 Atrofda ish bor — tezroq buyurtma oling!"
    else:
        text += "⏳ Hozircha yaqin atrofdagi ochiq buyurtma yo‘q."

    bot.send_message(message.chat.id, text, parse_mode="HTML")


# ========== DRIVER: Ishni boshlash va jonli lokatsiya ==========
@bot.message_handler(func=lambda m: m.text == "✅ Ishni boshlash")
def start_work(message):
    if check_blocked_and_respond(message.chat.id):
        return

    user_id = str(message.chat.id)

    if user_id not in drivers:
        bot.send_message(
            message.chat.id,
            "❗ Siz haydovchi emassiz!\nAvvalo 🚖 Haydovchi bo'lish orqali ro'yxatdan o'ting."
        )
        return

    balance = float(drivers.get(user_id, {}).get("balance", 0))
    if balance <= 0:
        bot.send_message(
            message.chat.id,
            "🚫 Ishni boshlash mumkin emas!\n\n"
            "💰 Balansingiz 0 yoki manfiy.\n"
            "❗ Buyurtma qabul qilish uchun balansni to‘ldiring.\n"
            "📞 Admin bilan bog‘laning."
        )
        return

    driver_status[user_id] = "online"
    live_location_active[user_id] = True
    _notified_near_orders.setdefault(user_id, set())

    bot.send_message(
        message.chat.id,
        "🟢 Ish boshlandi!\n\n"
        "📍 Endi jonli lokatsiya yuboring.\n"
        "➡️ Telegramda: 📎 → Lokatsiya → Jonli lokatsiya"
    )

    start_cmd(message)

@bot.message_handler(func=lambda m: m.text == "❌ Ishni tugatish")
def stop_work(m):
    if check_blocked_and_respond(m.chat.id):
        return

    driver_id = str(m.chat.id)

    # YANGI: Agar haydovchida aktiv buyurtma bo'lsa — ishni tugatish taqiqlanadi
    if driver_id in driver_active_order:
        bot.send_message(
            driver_id,
            "🚫 Ishni tugata olmaysiz!\n\n"
            "📦 Sizda hozirda aktiv buyurtma mavjud.\n"
            "Avval buyurtmani yetkazib bering yoki bekor qiling.\n\n"
            "👉 Buning uchun \"👤 Haydovchi haqida\" → \"📦 Aktiv buyurtma\" bo‘limiga o‘ting."
        )
        return  # Funksiyani to‘xtatamiz

    # Eski kod (faqat aktiv buyurtma yo‘q bo‘lganda ishlaydi)
    driver_status[driver_id] = "offline"
    live_location_active[driver_id] = False

    driver_locs = load_json(DRIVER_LOC_FILE)
    if driver_id in driver_locs:
        driver_locs[driver_id]["online"] = False
        save_json(DRIVER_LOC_FILE, driver_locs)

    if driver_id in last_location_message:
        try:
            bot.delete_message(driver_id, last_location_message[driver_id])
        except:
            pass
        del last_location_message[driver_id]

    bot.send_message(
        driver_id,
        "🔴 Ish to'xtatildi.\n📍 Jonli lokatsiya o'chirildi.\nEndi sizga buyurtmalar yuborilmaydi."
    )
    start_cmd(m)

@bot.message_handler(content_types=['location'])
def get_live_location(message):
    if check_blocked_and_respond(message.chat.id):
        return

    driver_id = str(message.chat.id)

    if driver_status.get(driver_id) != "online":
        bot.send_message(
            driver_id,
            "🚫 Siz ishni boshlamagansiz. Avval 'Ishni boshlash' tugmasini bosing."
        )
        return

    if not message.location:
        return

    lat = float(message.location.latitude)
    lon = float(message.location.longitude)
    save_driver_location(driver_id, lat, lon)

    # Eski xabarni o‘chiramiz
    if driver_id in last_location_message:
        try:
            bot.delete_message(driver_id, last_location_message[driver_id])
        except:
            pass

    # Yangi xabar
    msg = bot.send_message(driver_id, "📍 Jonli lokatsiya yangilandi (eskisi o'chirildi).")
    last_location_message[driver_id] = msg.message_id

# ========== ADMIN BUYRUG'I ==========
@bot.message_handler(commands=['reset_counter'])
def admin_reset_counter(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "❌ Sizda bu buyruqni ishlatish huquqi yo'q!")
        return

    result = reset_order_counter()
    bot.send_message(message.chat.id, result)

# ========== ADMIN COMMANDS ==========
@bot.message_handler(commands=['delete_order'])
def admin_delete_order(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "❌ Sizda bu buyruqni ishlatish huquqi yo'q!")
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "❗ Foydalanish: /delete_order <order_id>")
        return
    order_id = parts[1]
    orders_local = load_json(ORDERS_FILE)
    if order_id not in orders_local:
        bot.send_message(message.chat.id, "❌ Bunday buyurtma mavjud emas!")
        return
    order = orders_local[order_id]
    driver_id = order.get('driver_id')
    if driver_id and driver_id in driver_active_order and driver_active_order[driver_id] == order_id:
        del driver_active_order[driver_id]
        try:
            bot.send_message(driver_id, f"❗ Buyurtmangiz admin tomonidan o'chirildi. Yangi buyurtma olishingiz mumkin.")
        except:
            pass
    user_id = order.get('user_id')
    if user_id:
        try:
            bot.send_message(user_id, f"❌ Sizning buyurtmangiz (ID: {order_id}) admin tomonidan o'chirildi!")
        except:
            pass
    del orders_local[order_id]
    save_json(ORDERS_FILE, orders_local)
    bot.send_message(message.chat.id, f"✅ Buyurtma ID: {order_id} muvaffaqiyatli o'chirildi.")


@bot.message_handler(commands=['driver_info'])
def admin_driver_info(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "❌ Sizda bu buyruqni ishlatish huquqi yo'q!")
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "❗ Foydalanish: /driver_info <driver_id>")
        return

    driver_id = parts[1]
    if driver_id not in drivers:
        bot.send_message(message.chat.id, "❌ Bunday haydovchi mavjud emas!")
        return

    d = drivers[driver_id]

    # ✅ YANGI: tugallangan buyurtmalar soni
    finished_count = count_finished_orders_for_driver(driver_id)

    text = (
        f"👤 Haydovchi ma'lumotlari:\n"
        f"🆔 ID: {driver_id}\n"
        f"Ism familiya: {d.get('fullname','-')}\n"
        f"Mashina: {d.get('car_model','-')}\n"
        f"Davlat raqami: {d.get('car_number','-')}\n"
        f"Rangi: {d.get('car_color','-')}\n"
        f"Telefon: {d.get('phone','-')}\n"
        f"💰 Balans: {d.get('balance',0)} so'm\n"
        f"✅ Tugallangan buyurtmalar: {finished_count} ta\n\n"
    )

    markup = telebot.types.InlineKeyboardMarkup()

    if driver_id in driver_active_order:
        order_id = driver_active_order[driver_id]
        orders_local = load_json(ORDERS_FILE)

        if order_id in orders_local:
            o = orders_local[order_id]
            from_lat = o['from']['lat']; from_lon = o['from']['lon']
            to_lat = o['to']['lat']; to_lon = o['to']['lon']

            google_from = f"https://www.google.com/maps?q={from_lat},{from_lon}"
            google_to   = f"https://www.google.com/maps?q={to_lat},{to_lon}"
            yandex_from = f"https://yandex.com/maps/?ll={from_lon},{from_lat}&z=17"
            yandex_to   = f"https://yandex.com/maps/?ll={to_lon},{to_lat}&z=17"

            text += (
                f"📦 Aktiv buyurtma:\n"
                f"🆔 ID: {order_id}\n"
                f"📍 Qayerdan: [Google]({google_from}) | [Yandex]({yandex_from})\n"
                f"📍 Qayerga: [Google]({google_to}) | [Yandex]({yandex_to})\n"
                f"⚖️ Og'irlik kg: {o.get('weight','-')}\n"
                f"📞 Telefon: {o.get('phone','-')}\n"
                f"📝 Komment: {o.get('comment','-')}\n"
                f"📏 Masofa: {o.get('distance','-')} km\n"
                f"💰 Narx: {o.get('total','-')} so'm\n"
            )

            markup.add(
                telebot.types.InlineKeyboardButton(
                    "❌ Buyurtmani olib tashlash",
                    callback_data=f"admin_take_{driver_id}"
                )
            )
        else:
            text += "❗ Aktiv buyurtma topilmadi!"
    else:
        text += "❌ Haydovchida aktiv buyurtma yo'q."

    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)



@bot.message_handler(commands=['add_balance', 'remove_balance'])
def change_balance(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "❌ Sizda bu buyruqni ishlatish huquqi yo'q!")
        return
    parts = message.text.split()
    if len(parts) < 3:
        bot.send_message(message.chat.id, "❗ Foydalanish: /add_balance <user_id> <summa> yoki /remove_balance <user_id> <summa>")
        return
    target_user_id = parts[1]
    try:
        amount = int(parts[2])
    except:
        bot.send_message(message.chat.id, "❗ Summa butun raqam bo'lishi kerak.")
        return
    if target_user_id not in drivers:
        bot.send_message(message.chat.id, "❌ Bu foydalanuvchi haydovchi sifatida mavjud emas!")
        return
    if message.text.startswith('/add_balance'):
        drivers[target_user_id]['balance'] = drivers[target_user_id].get('balance', 0) + amount
        action = "qo'shildi"
    else:
        drivers[target_user_id]['balance'] = max(drivers[target_user_id].get('balance', 0) - amount, 0)
        action = "olib tashlandi"
    save_json(DRIVER_FILE, drivers)
    bot.send_message(message.chat.id, f"✅ {amount} so'm {target_user_id} balansiga {action}. Yangi balans: {drivers[target_user_id]['balance']} so'm")
    try:
        bot.send_message(target_user_id, f"💰 Sizning balansingizga {amount} so'm {action}. Yangi balans: {drivers[target_user_id]['balance']} so'm")
    except:
        pass

# ========== DRIVER REGISTRATION ==========
@bot.message_handler(func=lambda message: message.text == "🚖 Haydovchi bo'lish")
def driver_register(message):
    user_id = str(message.chat.id)
    if user_id in drivers:
        bot.send_message(message.chat.id,
            "✅ Siz haydovchi sifatida allaqachon ro'yxatdan o'tgansiz!\n\n"
            "👤 Haydovchi ma'lumotlarini ko'rish uchun *Haydovchi haqida* tugmasini bosing.", parse_mode="Markdown")
        return
    bot.send_message(message.chat.id, "Ism familiyangizni kiriting:")
    driver_state[user_id] = {"step": "fullname"}

@bot.message_handler(func=lambda message: str(message.chat.id) in driver_state)
def driver_reg_process(message):
    user_id = str(message.chat.id)
    state = driver_state[user_id]
    if state["step"] == "fullname":
        state["fullname"] = message.text
        state["step"] = "car_model"
        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        buttons = [telebot.types.InlineKeyboardButton(m, callback_data=f"model_{m}") for m in CAR_MODELS]
        for i in range(0, len(buttons), 2):
            if i + 1 < len(buttons): markup.add(buttons[i], buttons[i+1])
            else: markup.add(buttons[i])
        bot.send_message(message.chat.id, "🚗 Mashina rusumini tanlang:", reply_markup=markup)
    elif state["step"] == "car_number":
        car_number = message.text.upper().strip()
        pattern = r'^[0-9]{2} [A-Z]{1} [0-9]{3} [A-Z]{2}$'
        if not re.match(pattern, car_number):
            bot.send_message(message.chat.id,
                "❌ Noto'g'ri format! Iltimos quyidagi formatda kiriting:\n🔢 *AA B AAA BB* (masalan: 01 A 123 BC)",
                parse_mode="Markdown")
            return
        state["car_number"] = car_number
        state["step"] = "car_color"
        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        buttons = [telebot.types.InlineKeyboardButton(c, callback_data=f"color_{c}") for c in CAR_COLORS]
        for i in range(0, len(buttons), 2):
            if i + 1 < len(buttons): markup.add(buttons[i], buttons[i+1])
            else: markup.add(buttons[i])
        bot.send_message(message.chat.id, "🎨 Mashina rangini tanlang:", reply_markup=markup)
    elif state["step"] == "phone":
        phone = message.text.strip()
        pattern1 = r'^\+998\d{9}$'; pattern2 = r'^998\d{9}$'; pattern3 = r'^9\d{8}$'; pattern4 = r'^\d{9}$'
        if not (re.match(pattern1, phone) or re.match(pattern2, phone) or re.match(pattern3, phone) or re.match(pattern4, phone)):
            bot.send_message(message.chat.id, "❌ Noto'g'ri telefon raqami! Iltimos to'g'ri format kiriting.")
            return
        if phone.startswith('+998'): formatted_phone = phone
        elif phone.startswith('998'): formatted_phone = '+' + phone
        elif phone.startswith('9') and len(phone) == 9: formatted_phone = '+998' + phone
        else: formatted_phone = phone
        state["phone"] = formatted_phone
        summary = (
            f"🆔 Haydovchi ID: {user_id}\n"
            f"Ism familiya: {state.get('fullname','-')}\n"
            f"Mashina: {state.get('car_model','-')}\n"
            f"Davlat raqami: {state.get('car_number','-')}\n"
            f"Rangi: {state.get('car_color','-')}\n"
            f"Telefon: {state.get('phone','-')}\n\n"
            "Tasdiqlaysizmi?"
        )
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("✅ Tasdiqlayman", callback_data="driver_ok"),
                   telebot.types.InlineKeyboardButton("❌ Bekor qilish", callback_data="driver_cancel"))
        bot.send_message(message.chat.id, summary, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("model_"))
def select_car_model(call):
    user_id = str(call.message.chat.id)
    if user_id not in driver_state: return
    car_model = call.data.replace("model_", "")
    driver_state[user_id]["car_model"] = car_model
    driver_state[user_id]["step"] = "car_number"
    try:
        bot.edit_message_text(f"✅ Mashina rusumi: {car_model}", call.message.chat.id, call.message.message_id)
    except:
        pass
    bot.send_message(call.message.chat.id, "🔢 Davlat raqamini kiriting:\n📝 *Format: AA B AAA BB* (masalan: 01 A 123 BC)", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("color_"))
def select_car_color(call):
    user_id = str(call.message.chat.id)
    if user_id not in driver_state: return
    car_color = call.data.replace("color_", "")
    driver_state[user_id]["car_color"] = car_color
    driver_state[user_id]["step"] = "phone"
    try:
        bot.edit_message_text(f"✅ Mashina rangi: {car_color}", call.message.chat.id, call.message.message_id)
    except:
        pass
    bot.send_message(call.message.chat.id, "📞 Telefon raqamingizni kiriting:\n📝 Quyidagi formatlardan birida:\n• +998901234567\n• 998901234567\n• 901234567", parse_mode="Markdown")



@bot.callback_query_handler(func=lambda call: call.data in ["driver_ok", "driver_cancel"])
def callback_driver(call):
    user_id = str(call.message.chat.id)

    if call.data == "driver_ok":
        drivers[user_id] = driver_state.get(user_id, {})
        drivers[user_id].setdefault("balance", 0)
        drivers[user_id].setdefault("reg_time", int(time.time()))
        drivers[user_id].setdefault("referred_by", None)
        drivers[user_id].setdefault("referral_paid", False)

        # 🔗 REFERALNI BOG‘LASH
        ref_by = order_flow.get(user_id, {}).get("referred_by")
        if ref_by and ref_by in drivers:
            drivers[user_id]["referred_by"] = ref_by

        save_json(DRIVER_FILE, drivers)

        try:
            bot.edit_message_text(
                "🎉 Siz muvaffaqiyatli ro'yxatdan o'tdingiz!\n\n /start /start /start bosing.",
                call.message.chat.id,
                call.message.message_id
            )
        except:
            pass

    else:
        try:
            bot.edit_message_text(
                "❌ Ro'yxatdan o'tish bekor qilindi!",
                call.message.chat.id,
                call.message.message_id
            )
        except:
            pass

    if user_id in driver_state:
        del driver_state[user_id]


# ========== DRIVER INFO ==========
@bot.message_handler(func=lambda m: m.text == "👤 Haydovchi haqida")
def show_driver_info(message):
    if check_blocked_and_respond(message.chat.id):
        return

    user_id = str(message.chat.id)
    drivers_local = load_json(DRIVER_FILE)

    if user_id not in drivers_local:
        bot.send_message(
            message.chat.id,
            "❗ Siz hali haydovchi sifatida ro'yxatdan o'tmagansiz!"
        )
        return

    d = drivers_local[user_id]

    text = (
        f"🆔 Haydovchi ID: {user_id}\n"
        f"👤 Ism familiya: {d.get('fullname','-')}\n"
        f"🚘 Mashina: {d.get('car_model','-')}\n"
        f"🔢 Davlat raqami: {d.get('car_number','-')} 🔒\n"
        f"🎨 Rangi: {d.get('car_color','-')} 🔒\n"
        f"📞 Telefon: {d.get('phone','-')}\n\n"
        f"🔁 24 soat ichida bekor qilish: {remaining_cancels(user_id)} ta qoldi"
    )

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton(
            "📝 Ma'lumotlarni tahrirlash",
            callback_data="edit_driver_info"
        )
    )
    markup.add(
        telebot.types.InlineKeyboardButton(
            "💰 Balans",
            callback_data=f"driver_balance_{user_id}"
        )
    )
    markup.add(
        telebot.types.InlineKeyboardButton(
            "👥 Referal tizim",
            callback_data="driver_referral"
        )
    )

    markup.add(
        telebot.types.InlineKeyboardButton(
            "📜 Tugallangan buyurtmalar",
            callback_data="show_finished_orders"
        )
    )

    if user_id in driver_active_order:
        order_id = driver_active_order[user_id]
        markup.add(
            telebot.types.InlineKeyboardButton(
                "📦 Aktiv buyurtma",
                callback_data=f"active_{order_id}"
            )
        )
    else:
        markup.add(
            telebot.types.InlineKeyboardButton(
                "📦 Aktiv buyurtma yo'q",
                callback_data="no_active"
            )
        )

    bot.send_message(message.chat.id, text, reply_markup=markup)


# ====== YANGI: "Tugallangan buyurtmalar" tugmasi bosilganda ishlaydigan handler ======
@bot.callback_query_handler(func=lambda c: c.data == "show_finished_orders")
def handle_show_finished_orders(c):
    show_driver_finished_orders(c)
    bot.answer_callback_query(c.id)  # Tugma bosilganini tasdiqlash (ixtiyoriy, lekin yaxshi)


@bot.callback_query_handler(func=lambda c: c.data == "show_finished_orders")
def show_driver_finished_orders(c):  # nomini shu qoldirdim
    user_id = str(c.message.chat.id)

    # Bloklanganlikni tekshirish
    if check_blocked_and_respond(c.message.chat.id):
        bot.answer_callback_query(c.id)
        return

    drivers = load_json(DRIVER_FILE)
    if user_id not in drivers:
        bot.answer_callback_query(c.id, "Siz haydovchi emassiz!")
        return

    # Tugallangan buyurtmalarni olish (ID bilan birga)
    finished_orders = load_json(FINISHED_ORDERS_FILE)

    # Faqat shu haydovchiga tegishli buyurtmalarni (order_id, order_data) juftligida olish
    user_orders_with_id = [
        (order_id, order_data)
        for order_id, order_data in finished_orders.items()
        if str(order_data.get("driver_id")) == user_id
    ]

    if not user_orders_with_id:
        text = "📜 Sizda hali tugallangan buyurtma yo‘q."
        markup = None
    else:
        # Tartiblash: yangi tugallangan birinchi bo‘lsin
        user_orders_with_id = sorted(
            user_orders_with_id,
            key=lambda x: x[1].get("finish_time", 0),
            reverse=True
        )[:10]  # faqat so‘nggi 10 ta

        text = f"📜 Tugallangan buyurtmalar ({len(user_orders_with_id)} ta):\n\n"

        for i, (order_id, order) in enumerate(user_orders_with_id, 1):
            date = order.get("date", "Noma’lum")  # finish_order da saqlangan sana
            text += f"{i}. 📦 Buyurtma #{order_id} — {date}\n"

        # Agar 10 tadan ko‘p bo‘lsa, eslatma
        total_user_orders = len([
            o for o in finished_orders.values()
            if str(o.get("driver_id")) == user_id
        ])
        if total_user_orders > 10:
            text += "\n... va boshqa eskilar"

        markup = None

    # Xabarni tahrirlash yoki yangi yuborish
    try:
        bot.edit_message_text(
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=markup
        )
    except Exception as e:
        print(f"Edit xatosi (show_finished_orders): {e}")
        bot.send_message(c.message.chat.id, text, parse_mode="HTML", reply_markup=markup)

    bot.answer_callback_query(c.id, "Buyurtmalar yuklandi")


@bot.callback_query_handler(func=lambda c: c.data == "edit_driver_info")
def edit_driver_menu(c):
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        telebot.types.InlineKeyboardButton("👤 Ism familiya", callback_data="edit_fullname"),
        telebot.types.InlineKeyboardButton("📞 Telefon raqami", callback_data="edit_phone"),
    )

    # YANGI: Orqaga tugmasi
    markup.add(
        telebot.types.InlineKeyboardButton("◀️ Orqaga", callback_data="back_to_driver_info")
    )

    bot.edit_message_text(
        "✏️ Qaysi ma’lumotni tahrirlaysiz?\n\n"
        "✍️ Kerakli bo‘limni tanlang.",
        c.message.chat.id,
        c.message.message_id,
        reply_markup=markup
    )


# 👤 Ism familiya
@bot.callback_query_handler(func=lambda c: c.data == "edit_fullname")
def edit_fullname(c):
    user_id = str(c.message.chat.id)
    edit_state[user_id] = "fullname"
    bot.send_message(user_id, "👤 Yangi ism familiyangizni kiriting:")


# 🔢 Davlat raqami
#@bot.callback_query_handler(func=lambda c: c.data == "edit_car_number")
#def edit_car_number(c):
 #   user_id = str(c.message.chat.id)
 #   edit_state[user_id] = "car_number"
 #   bot.send_message(
 #       user_id,
 #       "🔢 Davlat raqamini kiriting:\n📝 Format: 01 A 123 BC"
 #   )


# 📞 Telefon raqami
@bot.callback_query_handler(func=lambda c: c.data == "edit_phone")
def edit_phone(c):
    user_id = str(c.message.chat.id)
    edit_state[user_id] = "phone"
    bot.send_message(
        user_id,
        "📞 Telefon raqamingizni kiriting:\n+998901234567 yoki 901234567"
    )


# 🎨 Mashina rangi (inline tugmalar bilan)
#@bot.callback_query_handler(func=lambda c: c.data == "edit_car_color")
#def edit_car_color(c):
#    user_id = str(c.message.chat.id)
#    edit_state[user_id] = "car_color"
#
#    # Rang variantlari
#    markup = telebot.types.InlineKeyboardMarkup(row_width=3)
#    colors = ["Oq", "Qora", "Ko‘k", "Qizil", "Yashil", "Kumush"]
#    for color in colors:
#        markup.add(
#            telebot.types.InlineKeyboardButton(color, callback_data=f"car_color_{color.lower()}")
#        )
#
#    bot.send_message(user_id, "🎨 Mashina rangini tanlang:", reply_markup=markup)


# Rang tanlanganini qabul qilish
@bot.callback_query_handler(func=lambda c: c.data.startswith("car_color_"))
def car_color_selected(c):
    user_id = str(c.message.chat.id)
    color = c.data.split("_")[2]  # masalan: 'oq', 'qora'

    drivers_local = load_json(DRIVER_FILE)
    drivers_local.setdefault(user_id, {})
    drivers_local[user_id]["car_color"] = color
    save_json(DRIVER_FILE, drivers_local)

    bot.answer_callback_query(c.id, text=f"🎨 Rang '{color}' tanlandi ✅")
    bot.edit_message_text(
        f"🎨 Mashina rangi '{color}' ga o‘zgartirildi",
        c.message.chat.id,
        c.message.message_id
    )

    if user_id in edit_state:
        del edit_state[user_id]

    # ⚡ Yangilangan barcha ma’lumotlarni foydalanuvchiga ko‘rsatish
    driver = drivers_local.get(user_id, {})
    bot.send_message(
        user_id,
        f"🆔 Haydovchi ID: {user_id}\n"
        f"👤 Ism familiya: {driver.get('fullname', '—')}\n"
        f"🚘 Mashina: {driver.get('car', '—')}\n"
        f"🔢 Davlat raqami: {driver.get('car_number', '—')}\n"
        f"🎨 Rangi: {driver.get('car_color', '—')}\n"
        f"📞 Telefon: {driver.get('phone', '—')}"
    )


# 💾 Saqlash (bitta handler — ism, raqam, telefon uchun)
@bot.message_handler(func=lambda m: str(m.chat.id) in edit_state)
def save_edit_driver_data(m):
    user_id = str(m.chat.id)
    field = edit_state[user_id]
    value = m.text.strip()

    drivers_local = load_json(DRIVER_FILE)

    # 👤 Ism familiya
    if field == "fullname":
        if any(ch.isdigit() for ch in value):
            bot.send_message(user_id, "❌ Ism familiyada raqam bo‘lmasligi kerak!")
            return

    # 🔢 Davlat raqami
    if field == "car_number":
        value = value.upper()
        pattern = r'^[0-9]{2} [A-Z]{1} [0-9]{3} [A-Z]{2}$'
        if not re.match(pattern, value):
            bot.send_message(user_id, "❌ Noto‘g‘ri format!\nMasalan: 01 A 123 BC")
            return

    # 📞 Telefon raqami
    if field == "phone":
        p1 = r'^\+998\d{9}$'
        p2 = r'^998\d{9}$'
        p3 = r'^9\d{8}$'
        p4 = r'^\d{9}$'
        if not (re.match(p1, value) or re.match(p2, value) or
                re.match(p3, value) or re.match(p4, value)):
            bot.send_message(user_id, "❌ Telefon raqami noto‘g‘ri!")
            return

        if value.startswith('998'):
            value = '+' + value
        elif value.startswith('9') and len(value) == 9:
            value = '+998' + value

    # 💾 Saqlash
    drivers_local.setdefault(user_id, {})
    drivers_local[user_id][field] = value
    save_json(DRIVER_FILE, drivers_local)

    bot.send_message(user_id, "✅ Ma’lumot muvaffaqiyatli yangilandi!")
    del edit_state[user_id]

    # ⚡ Yangilangan barcha ma’lumotlarni foydalanuvchiga ko‘rsatish
    driver = drivers_local.get(user_id, {})
    bot.send_message(
        user_id,
        f"🆔 Haydovchi ID: {user_id}\n"
        f"👤 Ism familiya: {driver.get('fullname', '—')}\n"
        f"🚘 Mashina: {driver.get('car', '—')}\n"
        f"🔢 Davlat raqami: {driver.get('car_number', '—')}\n"
        f"🎨 Rangi: {driver.get('car_color', '—')}\n"
        f"📞 Telefon: {driver.get('phone', '—')}"
    )



@bot.callback_query_handler(func=lambda c: c.data == "driver_referral")
def driver_referral(c):
    driver_id = str(c.message.chat.id)
    bot_username = bot.get_me().username

    referral_link = f"https://t.me/{bot_username}?start={driver_id}"

    text = (
        "👥 *Referal tizim*\n\n"
        "🔗 Sizning referal linkingiz:\n"
        f"`{referral_link}`\n\n"
        "📌 Har bir taklif qilingan haydovchi\n"
        "1 ta buyurtma bajarsa:\n"
        "🎁 Sizga +5 000 so‘m\n"
        "♻️ Bonus cheklanmagan!"
    )

    bot.send_message(c.message.chat.id, text, parse_mode="Markdown")
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("driver_balance_"))
def show_driver_balance(c):
    user_id = c.data.replace("driver_balance_", "")

    drivers_local = load_json(DRIVER_FILE)  # 🔥 MUHIM
    d = drivers_local.get(user_id, {})

    balance = d.get("balance", 0)

    bot.send_message(
        c.message.chat.id,
        f"💰 Sizning balansingiz: {balance:,} so‘m\n\n"
        "➕ Hisobingizni to‘ldirish uchun admin bilan bog‘laning!"
    )




# ========== EDIT HANDLERS ==========
@bot.callback_query_handler(func=lambda c: c.data == "edit_fullname")
def edit_fullname(c):
    user_id = str(c.message.chat.id)
    edit_state[user_id] = "fullname"
    bot.send_message(c.message.chat.id, "👤 Yangi ism familiyangizni kiriting (faqat harflar):")

@bot.message_handler(func=lambda msg: str(msg.chat.id) in edit_state)
def save_edit(msg):
    user_id = str(msg.chat.id)
    field = edit_state[user_id]
    value = msg.text.strip()
    if field == "fullname":
        if re.search(r'\d', value):
            bot.send_message(msg.chat.id, "❌ Ism familiyada raqam bo'lishi mumkin emas! Qaytadan kiriting:")
            return
    elif field == "car_number":
        pattern = r'^[0-9]{2} [A-Z]{1} [0-9]{3} [A-Z]{2}$'
        if not re.match(pattern, value.upper()):
            bot.send_message(msg.chat.id, "❌ Noto'g'ri format! Qaytadan kiriting:", parse_mode="Markdown")
            return
        value = value.upper()
    elif field == "phone":
        pattern1 = r'^\+998\d{9}$'; pattern2 = r'^998\d{9}$'; pattern3 = r'^9\d{8}$'; pattern4 = r'^\d{9}$'
        if not (re.match(pattern1, value) or re.match(pattern2, value) or re.match(pattern3, value) or re.match(pattern4, value)):
            bot.send_message(msg.chat.id, "❌ Noto'g'ri telefon raqami! Qaytadan kiriting:", parse_mode="Markdown")
            return
        if value.startswith('+998'): value = value
        elif value.startswith('998'): value = '+' + value
        elif value.startswith('9') and len(value) == 9: value = '+998' + value
    drivers[user_id][field] = value
    save_json(DRIVER_FILE, drivers)
    bot.send_message(msg.chat.id, f"✅ {field} muvaffaqiyatli yangilandi!")
    del edit_state[user_id]

# ========== ORDER CREATION (user) ==========
@bot.message_handler(func=lambda m: m.text == "📦 Buyurtma berish")
def start_order(message):
    user_id = str(message.chat.id)
    order_flow[user_id] = {}
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🚗 Labo", callback_data="car_labo"))
    bot.send_message(message.chat.id, "Sizga qanday mashina kerak?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "car_labo")
def car_selected(call):
    user_id = str(call.message.chat.id)
    order_flow[user_id] = {"car": "Labo"}
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except:
        pass
    msg = bot.send_message(call.message.chat.id, "📍 Qayerdan yukni olish kerak? Lokatsiya tashlang:")
    bot.register_next_step_handler(msg, order_from)

def order_from(message):
    user_id = str(message.chat.id)
    if not message.location:
        msg = bot.send_message(message.chat.id, "❗ Iltimos faqat lokatsiya yuboring!\n📍 Qayerdan yukni olish kerak? Lokatsiya tashlang:")
        bot.register_next_step_handler(msg, order_from)
        return

    lat = float(message.location.latitude)
    lon = float(message.location.longitude)

    # Manzil nomini olish (yangi qo'shildi)
    address = get_address_from_coords(lat, lon)

    order_flow[user_id]["from"] = {
        "lat": lat,
        "lon": lon,
        "address": address  # Yangi qo'shildi
    }

    msg = bot.send_message(message.chat.id, "📍 Qayerga olib boramiz? Lokatsiya tashlang:")
    bot.register_next_step_handler(msg, order_to)

def order_to(message):
    user_id = str(message.chat.id)
    if not message.location:
        msg = bot.send_message(message.chat.id, "❗ Iltimos faqat lokatsiya yuboring!\n📍 Qayerga olib boramiz? Lokatsiya tashlang:")
        bot.register_next_step_handler(msg, order_to)
        return

    lat = float(message.location.latitude)
    lon = float(message.location.longitude)

    # Manzil nomini olish (yangi qo'shildi)
    address = get_address_from_coords(lat, lon)

    order_flow[user_id]["to"] = {
        "lat": lat,
        "lon": lon,
        "address": address  # Yangi qo'shildi
    }

    msg = bot.send_message(message.chat.id, "📸 Yukning rasmini yuboring (kamida 1 ta rasm majburiy):")
    bot.register_next_step_handler(msg, order_photo)

def order_photo(message):
    user_id = str(message.chat.id)
    if message.photo:
        photo_id = message.photo[-1].file_id
        order_flow[user_id]["photo"] = photo_id
        bot.send_message(message.chat.id, "✅ Rasm qabul qilindi!")
        msg = bot.send_message(message.chat.id, "⚖️ Yukning og'irligi qancha? (faqat raqam kiriting):")
        bot.register_next_step_handler(msg, order_weight)
    else:
        msg = bot.send_message(message.chat.id, "❌ Iltimos yukning rasmini yuboring! (kamida 1 ta rasm majburiy):")
        bot.register_next_step_handler(msg, order_photo)

def order_weight(message):
    user_id = str(message.chat.id)
    try:
        weight = float(message.text)
        if weight <= 0: raise ValueError()
    except:
        msg = bot.send_message(message.chat.id, "❗ Iltimos faqat raqam kiriting! Masalan: 5 yoki 10.5")
        bot.register_next_step_handler(msg, order_weight)
        return
    order_flow[user_id]["weight"] = str(weight)
    msg = bot.send_message(message.chat.id, "📞 Telefon raqamingizni kiriting (masalan: +998901234567 yoki 901234567):")
    bot.register_next_step_handler(msg, order_phone)

def order_phone(message):
    user_id = str(message.chat.id)
    phone = message.text.strip()
    pattern1 = r'^\+998\d{9}$'; pattern2 = r'^998\d{9}$'; pattern3 = r'^9\d{8}$'; pattern4 = r'^\d{9}$'
    if not (re.match(pattern1, phone) or re.match(pattern2, phone) or re.match(pattern3, phone) or re.match(pattern4, phone)):
        msg = bot.send_message(message.chat.id, "❗ Iltimos to'g'ri telefon raqam kiriting!")
        bot.register_next_step_handler(msg, order_phone)
        return
    if phone.startswith('+998'): formatted_phone = phone
    elif phone.startswith('998'): formatted_phone = '+' + phone
    elif phone.startswith('9') and len(phone) == 9: formatted_phone = '+998' + phone
    else: formatted_phone = phone
    order_flow[user_id]["phone"] = formatted_phone
    msg = bot.send_message(message.chat.id, "✍️ Kommentariya yozing (majburiy emas):")
    bot.register_next_step_handler(msg, order_comment)

def order_comment(message):
    user_id = str(message.chat.id)
    order_flow[user_id]["comment"] = message.text or ""
    order_flow[user_id]["user_id"] = user_id

    from_lat = order_flow[user_id]["from"]["lat"]
    from_lon = order_flow[user_id]["from"]["lon"]
    to_lat = order_flow[user_id]["to"]["lat"]
    to_lon = order_flow[user_id]["to"]["lon"]

    # Agar oldin reverse geocoding orqali address saqlangan bo'lsa — olamiz
    from_address = order_flow[user_id]["from"].get("address", "Lokatsiya")
    to_address = order_flow[user_id]["to"].get("address", "Lokatsiya")

    # 📏 Google orqali masofa va vaqt hisoblash
    distance, duration = get_google_distance(
        from_lat,
        from_lon,
        to_lat,
        to_lon
    )

    # Agar internet bo'lmasa yoki Google API ishlamasa — fallback
    if distance is None:
        distance = distance_km(from_lat, from_lon, to_lat, to_lon)

    distance = round(distance, 2)

    # ⏱️ YETKAZIB BERISH VAQTINI HISOBLASH (YANGI QISM)
    estimated_minutes = duration  # Google API dan olingan taxminiy vaqt (daqiqada)

    # Agar API ishlamasa yoki 0 qaytarsa — masofaga qarab taxminiy hisoblash
    if estimated_minutes is None or estimated_minutes <= 0:
        # O‘rtacha tezlik 40 km/soat deb faraz qilamiz
        estimated_minutes = int((distance / 40) * 60)

    # Juda yaqin masofalarda ham aldovning oldini olish uchun minimal 10 daqiqa qo‘yamiz
    delivery_minutes = max(estimated_minutes, 10)

    # Buyurtmaga yetkazib berish vaqtini saqlaymiz
    order_flow[user_id]["delivery_duration"] = delivery_minutes

    # 💰 Narxni hisoblash
    base_price = 30000
    km_price = distance * 5000
    extra_fee = 0

    if 8 <= distance < 20:
        extra_fee = 50000
    elif distance >= 20:
        extra_fee = 80000

    total = int(base_price + km_price + extra_fee)

    # 🎁 Yangi foydalanuvchi chegirmasi
    users_local = load_json(USERS_FILE)
    user_orders = users_local.get(user_id, {}).get("orders", 0)
    discount = 0

    if user_orders == 0:
        discount = int(total * 0.10)
        total -= discount

    # 📦 Saqlash
    order_flow[user_id]["distance"] = distance
    order_flow[user_id]["extra_fee"] = extra_fee
    order_flow[user_id]["discount"] = discount
    order_flow[user_id]["total"] = total

    # 🔗 Google Maps linklari (koordinatalar bo'yicha)
    from_maps_link = f"https://www.google.com/maps/search/?api=1&query={from_lat},{from_lon}"
    to_maps_link = f"https://www.google.com/maps/search/?api=1&query={to_lat},{to_lon}"

    # Markdown uchun bosiladigan link matn
    from_text = f"[{from_address}]({from_maps_link})"
    to_text = f"[{to_address}]({to_maps_link})"

    # 🧾 Foydalanuvchiga ko‘rsatiladigan matn
    fee_text = ""
    if extra_fee == 50000:
        fee_text = "\n➕ 8–20 km ustama: 50 000 so'm"
    elif extra_fee == 80000:
        fee_text = "\n➕ 20 km dan yuqori ustama: 80 000 so'm"

    discount_text = ""
    if discount > 0:
        discount_text = f"\n🎁 Yangi foydalanuvchi chegirmasi: -{discount:,} so'm (10%)"

    # Qo‘shimcha: taxminiy yetkazib berish vaqtini foydalanuvchiga ko‘rsatish (ixtiyoriy, lekin foydali)
    time_text = f"\n⏱️ Taxminiy yetkazib berish vaqti: ~{delivery_minutes} daqiqa"

    summary = (
        f"🚕 *Buyurtma ma'lumotlari:*\n\n"
        f"🚗 Mashina turi: {order_flow[user_id].get('car', '-')}\n"
        f"📍 Qayerdan: {from_text}\n"
        f"📍 Qayerga: {to_text}\n"
        f"⚖️ Yuk og'irligi: {order_flow[user_id]['weight']} kg\n"
        f"📞 Telefon raqami: {order_flow[user_id]['phone']}\n"
        f"📝 Izoh/kommentariya: {order_flow[user_id]['comment']}\n"
        f"📏 Umumiy masofa: {distance} km"
        f"{time_text}"          # <-- Yangi qo‘shilgan qator
        f"{fee_text}"
        f"{discount_text}\n"
        f"💰 Yakuniy narx: {total:,} so'm\n\n"
        f"Tasdiqlaysizmi?"
    )

    # ⌨️ Inline tugmalar
    markup = telebot.types.InlineKeyboardMarkup()
    if order_flow[user_id].get("photo"):  # Agar rasm yuklangan bo‘lsa
        markup.add(
            telebot.types.InlineKeyboardButton(
                "🖼️ Yuk rasmini ko'rish",
                callback_data=f"preview_photo_{user_id}"
            )
        )
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Tasdiqlash", callback_data="order_yes"),
        telebot.types.InlineKeyboardButton("❌ Bekor qilish", callback_data="order_no")
    )

    # 💬 Xabar yuborish
    bot.send_message(
        message.chat.id,
        summary,
        parse_mode="Markdown",
        reply_markup=markup
    )



@bot.callback_query_handler(func=lambda c: c.data.startswith("preview_photo_"))
def preview_photo(c):
    user_id = c.data.replace("preview_photo_", "")
    if user_id not in order_flow:
        bot.answer_callback_query(c.id, "❌ Rasm topilmadi!")
        return
    photo_id = order_flow[user_id].get("photo")
    if not photo_id:
        bot.answer_callback_query(c.id, "❌ Rasm mavjud emas!")
        return
    bot.send_photo(c.message.chat.id, photo_id, caption="📸 Yukning rasmi:")
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda call: call.data in ["order_yes", "order_no"])
def order_confirm(call):
    user_id = str(call.message.chat.id)

    if call.data == "order_yes":
        orders_local = load_json(ORDERS_FILE)

        order_id = get_next_order_id()

        order_flow[user_id]["status"] = "open"
        order_flow[user_id]["blacklist_drivers"] = []
        order_flow[user_id]["sent_to_drivers"] = []
        
        # YANGI: Buyurtmaga yaratilgan vaqt qo‘shish (keyinchalik foydali)
        order_flow[user_id]["created_time"] = int(time.time())
        order_flow[user_id]["user_id"] = user_id  # aniq belgilash

        orders_local[order_id] = order_flow[user_id]
        save_json(ORDERS_FILE, orders_local)

        print(f"🎯 YANGI BUYURTMA: {order_id}")

        threading.Thread(target=auto_send_near_orders_once, args=(order_id,)).start()

        # YANGI: Umumiy statistikani yangilash
        update_global_stats()

        text = (
            f"✅ <b>Buyurtmangiz saqlandi!</b> ID: {order_id}\n\n"
            "⏳ Iltimos kuting...\n"
            "🚗 Haydovchi <b>3 daqiqa</b> ichida javob beradi!"
        )

        try:
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode="HTML"
            )
        except:
            bot.send_message(
                call.message.chat.id,
                text,
                parse_mode="HTML"
            )

    else:
        try:
            bot.edit_message_text(
                "<b>❌ Buyurtma bekor qilindi!</b>",
                call.message.chat.id,
                call.message.message_id,
                parse_mode="HTML"
            )
        except:
            bot.send_message(
                call.message.chat.id,
                "<b>❌ Buyurtma bekor qilindi!</b>",
                parse_mode="HTML"
            )

    # Har ikki holatda ham order_flow dan tozalash
    if user_id in order_flow:
        del order_flow[user_id]

# ========== DRIVER: manual buyurtma ko'rish ==========
@bot.message_handler(func=lambda m: m.text == "📝 Buyurtmalar")
def driver_orders_request(message):
    user_id = str(message.chat.id)
    if user_id not in drivers:
        bot.send_message(message.chat.id, "❗ Siz hali haydovchi sifatida ro'yxatdan o'tmagansiz!")
        return
    if user_id in driver_active_order:
        bot.send_message(message.chat.id, "❗ Sizda aktiv buyurtma mavjud! Uni tugating yoki bekor qiling.")
        return
    bot.send_message(message.chat.id, "📍 Iltimos joriy lokatsiyangizni yuboring:")
    bot.register_next_step_handler(message, driver_send_location)

def driver_send_location(message):
    user_id = str(message.chat.id)

    if user_id not in drivers:
        bot.send_message(
            message.chat.id,
            "❗ Siz hali haydovchi sifatida ro'yxatdan o'tmagansiz!"
        )
        return

    if not message.location:
        bot.send_message(message.chat.id, "❗ Iltimos lokatsiya yuboring!")
        return

    if not live_location_active.get(user_id, False):
        bot.send_message(
            message.chat.id,
            "❗ Buyurtmalarni ko'rish uchun avval 'Ishni boshlash' tugmasini bosing va jonli lokatsiya yuboring!"
        )
        return

    if user_id in driver_active_order:
        bot.send_message(
            message.chat.id,
            "❗ Sizda aktiv buyurtma mavjud! Yangi buyurtmalarni faqat u tugagach ko'ra olasiz."
        )
        return

    driver_lat = float(message.location.latitude)
    driver_lon = float(message.location.longitude)

    orders_local = load_json(ORDERS_FILE)
    nearby = []

    for oid, order in orders_local.items():
        if order.get("status") != "open":
            continue

        from_lat = float(order["from"]["lat"])
        from_lon = float(order["from"]["lon"])
        to_lat = float(order["to"]["lat"])
        to_lon = float(order["to"]["lon"])

        # ✅ Driver → Pickup masofa va vaqt
        pickup_distance, pickup_duration = get_google_distance(driver_lat, driver_lon, from_lat, from_lon)
        if pickup_distance is None:
            pickup_distance = distance_km(driver_lat, driver_lon, from_lat, from_lon)
            pickup_duration = pickup_distance / 40 * 60  # taxminiy, 40 km/soat

        # ✅ Pickup → Delivery masofa va vaqt
        delivery_distance, delivery_duration = get_google_distance(from_lat, from_lon, to_lat, to_lon)
        if delivery_distance is None:
            delivery_distance = distance_km(from_lat, from_lon, to_lat, to_lon)
            delivery_duration = delivery_distance / 40 * 60  # taxminiy

        # Umumiy masofa (kerak bo‘lsa)
        total_distance = round(pickup_distance + delivery_distance, 2)
        total_duration = round(pickup_duration + delivery_duration, 1)

        # Radius tekshirish
        if pickup_distance <= NEARBY_THRESHOLD_KM:
            order["distance_to_driver"] = round(pickup_distance, 2)
            nearby.append((oid, order))

    if not nearby:
        bot.send_message(
            message.chat.id,
            f"❗ Sizga yaqin buyurtmalar topilmadi (radius {NEARBY_THRESHOLD_KM} km)."
        )
        return

    for oid, order in nearby:
        phone_text = "❌ Yashirilgan (5 km ichida)"

        text = (
            f"📦 *Buyurtma ID:* {oid}\n"
            f"📍 Masofa haydovchidan: {round(pickup_distance,2)} km\n"
            f"⏱️ Vaqt haydovchidan olish joyigacha: {round(pickup_duration,1)} min\n"
            f"📍 Yetkazish masofasi: {round(delivery_distance,2)} km\n"
            f"⏱️ Vaqt yukni yetkazish joyigacha: {round(delivery_duration,1)} min\n"
            f"⚖️ Og'irlik kg: {order['weight']}\n"
            f"💰 Narx: {order.get('total', 'N/A')} so'm\n"
            f"📝 Komment: {order.get('comment','-')}"
        )

        bot.send_message(message.chat.id, "📍 Yukni olish joyi (karta)")
        bot.send_location(
            message.chat.id,
            order["from"]["lat"],
            order["from"]["lon"]
        )

        bot.send_message(message.chat.id, "📍 Yetkazish manzili (karta)")
        bot.send_location(
            message.chat.id,
            order["to"]["lat"],
            order["to"]["lon"]
        )

        markup = telebot.types.InlineKeyboardMarkup(row_width=1)

        if order.get("photo"):
            markup.add(
                telebot.types.InlineKeyboardButton(
                    "🖼️ Yuk rasmini ko'rish",
                    callback_data=f"view_photo_{oid}"
                )
            )

        markup.add(
            telebot.types.InlineKeyboardButton(
                "📥 Buyurtmani olish",
                callback_data=f"take_{oid}"
            )
        )

        bot.send_message(
            message.chat.id,
            text,
            parse_mode="Markdown",
            reply_markup=markup
        )



# ========== USER ORDERS ==========
@bot.message_handler(func=lambda m: m.text == "📦 Buyurtmalarim")
def my_orders(m):
    user_id = str(m.chat.id)
    orders_local = load_json(ORDERS_FILE)
    user_orders = {
        oid: data for oid, data in orders_local.items()
        if data.get("user_id") == user_id
    }
    if not user_orders:
        bot.send_message(user_id, "📭 Sizda hali buyurtmalar yo'q.")
        return
    for oid, order in user_orders.items():
        status = order.get("status", "-")
        weight = order.get("weight", "-")
        total = order.get("total", "-")
        comment = order.get("comment", "-")
        from_lat = order["from"]["lat"]
        from_lon = order["from"]["lon"]
        to_lat = order["to"]["lat"]
        to_lon = order["to"]["lon"]
        from_url = f"https://www.google.com/maps?q={from_lat},{from_lon}"
        to_url = f"https://www.google.com/maps?q={to_lat},{to_lon}"
        text = (
            f"📦 *Buyurtma ID:* {oid}\n"
            f"📌 *Holat:* {status}\n"
            f"⚖️ *Vazni:* {weight} kg\n"
            f"💰 *Narxi:* {total} so'm\n"
            f"📝 *Komment:* {comment}\n\n"
            f"📍 *Yuk olish manzili:*\n"
            f"[Google Maps orqali ko'rish]({from_url})\n\n"
            f"🏁 *Yetkazish manzili:*\n"
            f"[Google Maps orqali ko'rish]({to_url})"
        )

        # 🔥 YANGI: Agar "taken" holatida bo'lsa, haydovchi ma'lumotlarini qo'shish
        if order.get("status") == "taken":
            driver_id = order.get("driver_id")
            if driver_id and driver_id in drivers:
                driver = drivers[driver_id]
                text += f"\n\n🚚 *Haydovchi ma'lumotlari:*\n👤 {driver.get('fullname', '-')}\n🚗 {driver.get('car_model', '-')} {driver.get('car_color', '-')}\n🔢 {driver.get('car_number', '-')}\n📞 {driver.get('phone', '-')}"

        markup = telebot.types.InlineKeyboardMarkup()
        if order.get("photo"):
            markup.add(telebot.types.InlineKeyboardButton("🖼️ Yuk rasmi", callback_data=f"view_photo_{oid}"))

        # 🔥 YANGI: Open yoki Closed holatida bekor qilish tugmasi
        if order.get("status") in ["open", "closed"]:
            markup.add(telebot.types.InlineKeyboardButton("❌ Bekor qilish", callback_data=f"user_cancel_{oid}"))

        bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=markup)

# 🔥 YANGI: Foydalanuvchi buyurtmani bekor qilish funksiyasi
@bot.callback_query_handler(func=lambda c: c.data.startswith("user_cancel_"))
def user_cancel_order(c):
    user_id = str(c.message.chat.id)
    order_id = c.data.replace("user_cancel_", "")
    orders_local = load_json(ORDERS_FILE)

    if order_id not in orders_local:
        bot.answer_callback_query(c.id, "❌ Buyurtma topilmadi!")
        return

    order = orders_local[order_id]

    # Faqat buyurtma egasi bekor qilishi mumkin
    if order.get('user_id') != user_id:
        bot.answer_callback_query(c.id, "❌ Siz bu buyurtmani bekor qila olmaysiz!")
        return

    # 🔥 YANGI: Agar buyurtma "taken" holatida bo'lsa, bekor qilish mumkin emas
    if order.get('status') == 'taken':
        bot.answer_callback_query(c.id, "❌ Haydovchi buyurtmani olgan! Bekor qila olmaysiz.")
        return

    # Agar buyurtma taken holatida bo'lsa, haydovchiga xabar berish
    # (Bu qism endi faqat "open" yoki "closed" holatida ishlaydi)
    if order.get('status') == 'taken':
        driver_id = order.get('driver_id')
        if driver_id:
            try:
                bot.send_message(driver_id, f"❗ Buyurtmangiz bekor qilindi!\n🚫 Buyurtmachi bekor qildi.\n🆔 Buyurtma ID: {order_id}")
            except:
                pass
            # Haydovchining aktiv buyurtmasini olib tashlash
            if driver_id in driver_active_order and driver_active_order[driver_id] == order_id:
                del driver_active_order[driver_id]

    # Buyurtmani JSON fayldan o'chirish
    del orders_local[order_id]
    save_json(ORDERS_FILE, orders_local)

    # Xabarni yangilash
    try:
        bot.edit_message_text(
            f"✅ Buyurtma bekor qilindi!\n🆔 ID: {order_id}",
            c.message.chat.id,
            c.message.message_id
        )
    except:
        bot.send_message(user_id, f"✅ Buyurtma bekor qilindi!\n🆔 ID: {order_id}")

    bot.answer_callback_query(c.id, "✅ Buyurtma bekor qilindi!")

# ========== CALLBACK HANDLERS ==========
@bot.callback_query_handler(func=lambda c: c.data.startswith("view_photo_"))
def view_photo_driver(c):
    order_id = c.data.replace("view_photo_", "")
    orders_local = load_json(ORDERS_FILE)
    if order_id not in orders_local:
        bot.answer_callback_query(c.id, "❌ Buyurtma topilmadi!")
        return
    order = orders_local[order_id]
    photo_id = order.get("photo")
    if not photo_id:
        bot.answer_callback_query(c.id, "❌ Bu buyurtmada rasm mavjud emas!")
        return
    bot.send_photo(c.message.chat.id, photo_id, caption=f"📸 Buyurtma ID: {order_id} - Yukning rasmi")
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("active_"))
def show_active_order(c):
    driver_id = str(c.message.chat.id)
    order_id = c.data.replace("active_", "")
    orders_local = load_json(ORDERS_FILE)

    if order_id not in orders_local:
        bot.answer_callback_query(c.id, "❌ Buyurtma topilmadi!")
        return

    order = orders_local[order_id]

    if order.get("driver_id") != driver_id:
        bot.answer_callback_query(c.id, "❌ Bu buyurtma sizga biriktirilmagan!")
        return

    from_lat = order['from']['lat']
    from_lon = order['from']['lon']
    to_lat = order['to']['lat']
    to_lon = order['to']['lon']

    google_from = f"https://www.google.com/maps?q={from_lat},{from_lon}"
    google_to   = f"https://www.google.com/maps?q={to_lat},{to_lon}"

    text = (
        f"📦 <b>Sizning aktiv buyurtmangiz</b>\n\n"
        f"🆔 ID: {order_id}\n"
        f"📍 Qayerdan: <a href=\"{google_from}\">Google Maps</a>\n"
        f"📍 Qayerga: <a href=\"{google_to}\">Google Maps</a>\n"
        f"⚖️ Og'irlik: {order.get('weight','-')} kg\n"
        f"📞 Telefon: {order.get('phone','-')}\n"
        f"📝 Komment: {order.get('comment','-')}\n"
        f"💰 Narx: {order.get('total','-')} so'm"
    )

    markup = telebot.types.InlineKeyboardMarkup()

    if order.get("photo"):
        markup.add(
            telebot.types.InlineKeyboardButton(
                "🖼️ Yuk rasmi", callback_data=f"view_photo_{order_id}"
            )
        )

    markup.add(
        telebot.types.InlineKeyboardButton(
            "❌ Buyurtmani bekor qilish", callback_data=f"cancel_order_{order_id}"
        )
    )

    markup.add(
        telebot.types.InlineKeyboardButton(
            "✅ Buyurtmani tugatdim", callback_data=f"finish_{order_id}"
        )
    )

    bot.send_message(c.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("finish_"))
def finish_order(c):
    driver_id = str(c.message.chat.id)
    order_id = c.data.replace("finish_", "")

    orders_local = load_json(ORDERS_FILE)
    drivers_local = load_json(DRIVER_FILE)

    # ❗ Buyurtma mavjudmi?
    if order_id not in orders_local:
        bot.answer_callback_query(c.id, "❌ Buyurtma topilmadi!")
        return

    order = orders_local[order_id]

    # ❗ Bu buyurtma shu haydovchigami?
    if order.get("driver_id") != driver_id:
        bot.answer_callback(c.id, "❌ Bu buyurtma sizga biriktirilmagan!")
        return

    # ❗ Tugmani faqat ruxsat etilgan vaqtda bosish mumkin
    if order.get("status") != "can_finish":
        bot.answer_callback_query(c.id, "⏳ Hali yetkazib berishni tugatish mumkin emas. Biroz kutib turing.")
        return

    # 💰 Buyurtma narxi va komissiya
    total_price = float(order.get("total", 0))
    commission = round(total_price * 0.05)  # 5% komissiya

    # ✔ Haydovchi balansi
    driver_balance = float(drivers_local.get(driver_id, {}).get("balance", 0))
    new_balance = driver_balance - commission

    # Haydovchi ma'lumotlarini yangilash
    if driver_id not in drivers_local:
        drivers_local[driver_id] = {}
    drivers_local[driver_id]["balance"] = new_balance

    # 🎁 Referal bonus (faqat 1-buyurtma uchun 1 marta)
    referred_by = drivers_local.get(driver_id, {}).get("referred_by")
    if referred_by and referred_by in drivers_local:
        if not drivers_local[driver_id].get("referral_paid", False):
            drivers_local[referred_by]["balance"] = (
                float(drivers_local[referred_by].get("balance", 0)) + 5000
            )
            drivers_local[driver_id]["referral_paid"] = True
            try:
                bot.send_message(
                    referred_by,
                    "🎉 Referal bonus!\n"
                    "Siz taklif qilgan haydovchi birinchi buyurtmani bajardi.\n"
                    "💰 +5 000 so‘m balansingizga qo‘shildi!"
                )
            except Exception as e:
                print(f"Referal xabari yuborishda xato: {e}")

    # Haydovchilar faylini saqlash
    save_json(DRIVER_FILE, drivers_local)

    # 👤 Buyurtmachi statistikasi
    user_id = order.get("user_id")
    if user_id:
        users = load_json(USERS_FILE)
        users.setdefault(user_id, {})
        users[user_id]["orders"] = users[user_id].get("orders", 0) + 1
        save_json(USERS_FILE, users)

    # 🟢 Tugallangan buyurtmani arxivga saqlash
    order["status"] = "finished"
    finish_timestamp = int(time.time())
    order["finish_time"] = finish_timestamp

    # Inson o‘qishi oson sana qo‘shish (kun.oy.yil)
    order["date"] = datetime.fromtimestamp(finish_timestamp).strftime("%d.%m.%Y")

    # === YANGI: Manzil nomlarini olish va saqlash ===
    try:
        from_lat = order["from"]["lat"]
        from_lon = order["from"]["lon"]
        to_lat = order["to"]["lat"]
        to_lon = order["to"]["lon"]

        from_address = get_address_from_coords(from_lat, from_lon)
        to_address = get_address_from_coords(to_lat, to_lon)

        # Agar API ishlamasa yoki xato bo‘lsa, fallback
        order["from_address"] = from_address if from_address and from_address != "Manzil nomi topilmadi" else "Manzil topilmadi"
        order["to_address"] = to_address if to_address and to_address != "Manzil nomi topilmadi" else "Manzil topilmadi"
    except Exception as e:
        print(f"Manzil nomlarini olishda xato: {e}")
        order["from_address"] = "Manzil topilmadi (xato)"
        order["to_address"] = "Manzil topilmadi (xato)"

    # Saqlash
    save_finished_order(order_id, order)

    # 🗑 Faol buyurtmadan o‘chirish
    del orders_local[order_id]
    save_json(ORDERS_FILE, orders_local)

    # 🚗 Haydovchini bo‘shatish
    driver_active_order.pop(driver_id, None)

    # 👤 Buyurtmachiga xabar
    if user_id:
        try:
            bot.send_message(
                user_id,
                f"✅ Buyurtmangiz muvaffaqiyatli yetkazib berildi!\n"
                f"🆔 Buyurtma ID: {order_id}\n"
                f"Rahmat, yana kutamiz! 🚀"
            )
        except Exception as e:
            print(f"Buyurtmachiga xabar yuborishda xato: {e}")

    # 🚖 Haydovchiga hisobot
    driver_text = (
        f"🎉 Buyurtma muvaffaqiyatli tugatildi!\n\n"
        f"🆔 Buyurtma ID: {order_id}\n"
        f"💰 Buyurtma narxi: {total_price:,} so‘m\n"
        f"📉 5% komissiya: {commission:,} so‘m\n"
        f"💳 Yangi balansingiz: {new_balance:,} so‘m.\n\n Buyurtmalar qidirilmoqda...\n⏳ Iltimos kuting..."
    )

    try:
        bot.edit_message_text(
            driver_text,
            c.message.chat.id,
            c.message.message_id,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Edit xatosi: {e}")
        bot.send_message(driver_id, driver_text, parse_mode="Markdown")

    # 🚫 Balans nol yoki manfiy bo‘lsa — bloklash
    if new_balance <= 0:
        try:
            bot.send_message(
                driver_id,
                "⚠️ Balansingiz 0 yoki manfiy bo‘lib qoldi.\n"
                "❌ Yangi buyurtma qabul qila olmaysiz.\n"
                "💳 Iltimos, balansni to‘ldiring (admin bilan bog‘laning)."
            )
        except:
            pass
        
        # Onlayn holatni o‘chirish
        driver_online[driver_id] = False
        live_location_active[driver_id] = False

    # Tugma bosilganini tasdiqlash
    bot.answer_callback_query(c.id, "✅ Buyurtma tugatildi!")


@bot.callback_query_handler(func=lambda call: call.data.startswith("take_"))
def take_order(call):
    driver_id = str(call.message.chat.id)
    order_id = call.data.replace("take_", "")

    # Haydovchi ro'yxatdan o'tganmi?
    drivers_local = load_json(DRIVER_FILE)
    if driver_id not in drivers_local:
        bot.answer_callback_query(call.id, "❌ Siz haydovchi emassiz! Ro'yxatdan o'ting.")
        return

    # 🚫 BLOKLANGAN haydovchi buyurtma ola olmaydi
    if drivers_local.get(driver_id, {}).get("blocked", False):
        bot.answer_callback_query(call.id, "🚫 Siz bloklangansiz! Buyurtma ola olmaysiz.")
        try:
            bot.delete_message(driver_id, call.message.message_id)
        except:
            pass
        return

    orders_local = load_json(ORDERS_FILE)
    if order_id not in orders_local:
        bot.answer_callback_query(call.id, "❌ Buyurtma topilmadi yoki allaqachon olingan!")
        return

    order = orders_local[order_id]

    # Buyurtma ochiqmi?
    if order.get("status") != "open":
        bot.answer_callback_query(call.id, "❌ Kech qoldingiz! Buyurtma boshqa haydovchi tomonidan olingan.")
        try:
            bot.delete_message(driver_id, call.message.message_id)
        except:
            pass
        return

    # O'z buyurtmasini ololmaydi
    if str(order.get("user_id")) == driver_id:
        bot.answer_callback_query(call.id, "❌ O'z buyurtmangizni ola olmaysiz!")
        return

    # Haydovchi bandmi?
    if driver_id in driver_active_order:
        bot.answer_callback_query(call.id, "❌ Sizda aktiv buyurtma bor. Avval uni tugating.")
        return

    # ✅ BUYURTMA OLINADI
    orders_local[order_id]["status"] = "taken"
    orders_local[order_id]["driver_id"] = driver_id
    orders_local[order_id]["taken_time"] = int(time.time())
    save_json(ORDERS_FILE, orders_local)

    # ✅ Xotirada aktiv buyurtma
    driver_active_order[driver_id] = order_id

    # ✅ Boshqa haydovchilardan xabarlarni o'chirish
    cleanup_other_drivers_messages(order_id, driver_id)

    # Maps linklari
    from_lat = order["from"]["lat"]
    from_lon = order["from"]["lon"]
    to_lat = order["to"]["lat"]
    to_lon = order["to"]["lon"]

    google_from = f"https://www.google.com/maps?q={from_lat},{from_lon}"
    google_to = f"https://www.google.com/maps?q={to_lat},{to_lon}"
    yandex_from = f"https://yandex.com/maps/?ll={from_lon},{from_lat}&z=17"
    yandex_to = f"https://yandex.com/maps/?ll={to_lon},{to_lat}&z=17"

    # Haydovchiga batafsil ma'lumot
    driver_text = (
        f"📦 *Buyurtma muvaffaqiyatli tanlandi\\!*\n\n"
        f"🆔 ID: {order_id}\n\n"
        f"📍 *Qayerdan\\:* [Google]({google_from}) \\| [Yandex]({yandex_from})\n"
        f"📍 *Qayerga\\:* [Google]({google_to}) \\| [Yandex]({yandex_to})\n\n"
        f"⚖️ Og‘irlik: {order.get('weight', '-')} kg\n"
        f"📞 Telefon: {order.get('phone', '-')}\n"
        f"📝 Izoh: {order.get('comment', '-')}\n"
        f"📏 Masofa: {order.get('distance', '-')} km\n"
        f"💰 Narx: {order.get('total', '-')} so‘m"
    )

    try:
        bot.edit_message_text(
            driver_text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"Edit error: {e}")
        bot.send_message(call.message.chat.id, driver_text, parse_mode="Markdown", disable_web_page_preview=True)

    # Muhim ogohlantirish
    warning_text = (
        "✅ *Siz buyurtmani muvaffaqiyatli tanladingiz!* 🚀\n\n"
        "🚫 Shubhali yoki noqonuniy yuklarni **aslo** tashimang!\n"
        "🔐 Barcha javobgarlik o‘z zimmasingizda!\n"
        "❗ Bot bunday holatlar uchun javobgarlikni o‘z zimmasiga olmaydi.\n\n"
        "❌ *Buyurtmani bekor qilmoqchi bo‘lsangiz:*\n"
        "👤 “Haydovchi haqida” bo‘limidagi\n"
        "📦 “Aktiv buyurtma” tugmasi orqali bekor qilishingiz mumkin.\n\n"
        "⏳ Iltimos kuting..."
    )
    bot.send_message(call.message.chat.id, warning_text, parse_mode="Markdown")

    # ⏱️ Yetkazish vaqti (minutda)
    delivery_minutes = int(order.get("delivery_duration", 15))

    # 🕒 Timer ishga tushiriladi
    threading.Thread(
        target=allow_finish_later,
        args=(driver_id, order_id, delivery_minutes),
        daemon=True
    ).start()

    # ✅ Buyurtmachiga xabar + message_id saqlash
    buyer_id = order.get("user_id")
    if buyer_id:
        driver_info = drivers_local.get(driver_id, {})
        user_text = (
            f"🚚 *Sizning buyurtmangiz tanlandi!*\n\n"
            f"👤 Haydovchi: {driver_info.get('fullname', '-')}\n"
            f"🚗 Mashina: {driver_info.get('car_model', '-')}\n"
            f"🎨 Rangi: {driver_info.get('car_color', '-')}\n"
            f"🔢 Davlat raqami: {driver_info.get('car_number', '-')}\n"
            f"📞 Telefon: {driver_info.get('phone', '-')}\n\n"
            f"🆔 Buyurtma ID: {order_id}\n"
        )

        try:
            umsg = bot.send_message(buyer_id, user_text, parse_mode="Markdown")

            # 1) RAM (xotira) ga saqlaymiz
            user_take_messages[order_id] = umsg.message_id

            # 2) Orders.json ichiga ham saqlaymiz (restart bo'lsa ham o'chira olish uchun)
            orders_local2 = load_json(ORDERS_FILE)
            if order_id in orders_local2:
                orders_local2[order_id]["user_take_msg_id"] = umsg.message_id
                save_json(ORDERS_FILE, orders_local2)

        except Exception as e:
            print("buyer notify error:", e)

    bot.answer_callback_query(call.id, "✅ Buyurtma sizniki bo‘ldi!")




@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_take_"))
def admin_take_order_callback(c):
    driver_id = c.data.replace("admin_take_", "")

    if driver_id not in driver_active_order:
        bot.answer_callback_query(c.id, "❌ Haydovchida aktiv buyurtma yo'q!")
        return

    order_id = driver_active_order[driver_id]

    # Admin majburan bekor qilmoqda
    success = force_cancel_order_by_admin(driver_id, order_id)

    if success:
        try:
            bot.send_message(
                driver_id,
                f"❗ Sizning aktiv buyurtmangiz (ID: {order_id}) admin tomonidan olib tashlandi.\n"
                "Yangi buyurtma olishingiz mumkin."
            )
        except:
            pass

        bot.answer_callback_query(
            c.id,
            f"✅ Buyurtma muvaffaqiyatli olib tashlandi (ID: {order_id})"
        )
    else:
        bot.answer_callback_query(c.id, "❌ Xato yuz berdi!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("resend_yes_"))
def resend_order_yes(c):
    order_id = c.data.replace("resend_yes_", "")

    orders = load_json(ORDERS_FILE)
    if order_id not in orders:
        return

    orders[order_id]["status"] = "open"
    save_json(ORDERS_FILE, orders)

    reset_notified_for_order(order_id)
    auto_send_near_orders_once(order_id)

    # 🔁 YANA 3 DAQIQA KUTISH
    threading.Thread(
        target=notify_if_not_taken_later,
        args=(order_id,)
    ).start()

    bot.edit_message_text(
        "♻️ Buyurtma yana haydovchilarga yuborildi.",
        c.message.chat.id,
        c.message.message_id
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("resend_no_"))
def resend_order_no(c):
    order_id = c.data.replace("resend_no_", "")

    orders = load_json(ORDERS_FILE)
    if order_id in orders:
        orders[order_id]["status"] = "closed"
        save_json(ORDERS_FILE, orders)

    bot.edit_message_text(
        "❌ Buyurtma bekor qilindi.",
        c.message.chat.id,
        c.message.message_id
    )


def force_cancel_order_by_admin(driver_id, order_id):
    """Admin haydovchidan buyurtmani majburan olib tashlaydi"""
    orders_local = load_json(ORDERS_FILE)
    drivers_local = load_json(DRIVER_FILE)

    if order_id not in orders_local:
        return False

    order = orders_local[order_id]

    if order.get("driver_id") != driver_id:
        return False

    # Jarima va cancel limitni qo‘shmaymiz (admin qilayotgan bo‘lsa)
    # Faqat buyurtmani ochamiz va blacklistga qo‘shamiz (ixtiyoriy)

    order.setdefault("blacklist_drivers", [])
    if driver_id not in order["blacklist_drivers"]:
        order["blacklist_drivers"].append(driver_id)

    order["status"] = "open"
    order["driver_id"] = None
    order.pop("notify_started", None)

    save_json(ORDERS_FILE, orders_local)

    # Aktiv buyurtmadan chiqarish
    if driver_id in driver_active_order:
        del driver_active_order[driver_id]

    # Eski xabarlarni tozalash
    cleanup_other_drivers_messages(order_id, None)

    # Qayta yuborish
    reset_notified_for_order(order_id)
    auto_send_near_orders_once(order_id)

    # 3 daqiqa kutish threadini qayta ishga tushirish
    threading.Thread(target=notify_if_not_taken_later, args=(order_id,), daemon=True).start()

    # Buyurtmachiga xabar (haydovchi bekor qilgandek ko‘rinadi)
    user_id = order.get("user_id")
    if user_id:
        try:
            bot.send_message(
                user_id,
                "❗ Haydovchi sizning buyurtmangizni bekor qildi.\n"
                "📦 Buyurtma yana haydovchilar uchun ochiq.\nKuting... ⏳ "
            )
        except:
            pass

    return True


@bot.callback_query_handler(func=lambda c: c.data.startswith("cancel_order_"))
def cancel_order(c):
    import threading

    driver_id = str(c.message.chat.id)
    order_id = c.data.replace("cancel_order_", "")

    orders_local = load_json(ORDERS_FILE)
    drivers_local = load_json(DRIVER_FILE)

    # ❌ Aktiv buyurtma emasmi?
    if driver_id not in driver_active_order or driver_active_order[driver_id] != order_id:
        bot.answer_callback_query(c.id, "❌ Sizda bu buyurtma aktiv emas!")
        return

    # 🔢 Cancel limit
    register_cancel(driver_id)
    cancel_count = cancel_limits[driver_id]["count"]

    balance = float(drivers_local.get(driver_id, {}).get("balance", 0))

    # 💸 Limitdan oshsa jarima
    if cancel_count > 3:
        if balance < 2000:
            bot.send_message(
                driver_id,
                "❌ Hisobingizda 2000 so‘m yetarli emas.\n"
                "Buyurtmani bekor qilib bo‘lmaydi."
            )
            return

        drivers_local[driver_id]["balance"] = balance - 2000
        save_json(DRIVER_FILE, drivers_local)

        bot.send_message(
            driver_id,
            f"⚠️ Limitdan oshdingiz!\n"
            f"2000 so‘m balansingizdan yechildi.\n"
            f"💰 Yangi balans: {drivers_local[driver_id]['balance']} so‘m"
        )
    else:
        remaining = remaining_cancels(driver_id)
        bot.send_message(
            driver_id,
            f"✅ Buyurtma bekor qilindi.\n"
            f"Qolgan bepul bekor qilishlar: {remaining}"
        )

    # 📦 Buyurtmani qayta ochish
    if order_id in orders_local:
        order = orders_local[order_id]

        # ✅ BUYURTMACHIDAGI "TANLANDI" XABARINI DELETE QILISH
        user_id = order.get("user_id")
        if user_id:
            # 1) avval orders.json dan urinib ko‘ramiz
            msg_id = order.get("user_take_msg_id")

            # 2) bo‘lmasa RAM dagisini ishlatamiz
            if not msg_id:
                msg_id = user_take_messages.get(order_id)

            if msg_id:
                try:
                    bot.delete_message(user_id, int(msg_id))
                except:
                    pass

            # RAM dagisini ham tozalab qo‘yamiz
            user_take_messages.pop(order_id, None)

        # 🔴 MUHIM: notify holatini reset qilamiz
        order.pop("notify_started", None)
        reset_notified_for_order(order_id)

        # 🚫 Haydovchini blacklistga qo‘shish
        order.setdefault("blacklist_drivers", [])
        if driver_id not in order["blacklist_drivers"]:
            order["blacklist_drivers"].append(driver_id)

        order["status"] = "open"
        order["driver_id"] = None

        # ✅ saqlab qo‘yamiz (user_take_msg_id ham endi keraksiz bo‘ldi)
        order.pop("user_take_msg_id", None)
        save_json(ORDERS_FILE, orders_local)

        # 🧹 Eski xabarlarni tozalash
        cleanup_other_drivers_messages(order_id, None)

        # 🚀 Yana haydovchilarga yuborish
        auto_send_near_orders_once(order_id)

        # 👤 Buyurtmachiga xabar (ixtiyoriy)
        if user_id:
            try:
                bot.send_message(
                    user_id,
                    "❗ Haydovchi sizning buyurtmangizni bekor qildi.\n"
                    "📦 Buyurtma yana haydovchilar uchun ochiq."
                )
            except:
                pass

    # 🚗 Haydovchini aktiv buyurtmadan chiqarish
    if driver_id in driver_active_order:
        del driver_active_order[driver_id]

    # 🧾 Haydovchi interfeysini yangilash
    try:
        bot.edit_message_text(
            "❌ Buyurtma bekor qilindi!\n"
            "📦 Buyurtma yana haydovchilar uchun ochiq.",
            c.message.chat.id,
            c.message.message_id
        )
    except:
        bot.send_message(
            c.message.chat.id,
            "❌ Buyurtma bekor qilindi!\n"
            "📦 Buyurtma yana haydovchilar uchun ochiq."
        )

    bot.answer_callback_query(c.id, "Buyurtma bekor qilindi")




# ============================
#  HAYDOVCHI MA'LUMOTLARINI TAHRIRLASH (INLINE)
# ============================

# 📝 Tahrirlash menyusi
# ============================
# HAYDOVCHI MA'LUMOTLARINI TAHRIRLASH (INLINE)
# ============================

@bot.callback_query_handler(func=lambda c: c.data == "edit_driver_info")
def edit_driver_menu(c):
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        telebot.types.InlineKeyboardButton("👤 Ism familiya", callback_data="edit_fullname"),
        telebot.types.InlineKeyboardButton("🔢 Davlat raqami", callback_data="edit_car_number"),
        telebot.types.InlineKeyboardButton("📞 Telefon raqami", callback_data="edit_phone"),
        telebot.types.InlineKeyboardButton("🎨 Mashina rangi", callback_data="edit_car_color"),
    )

    bot.edit_message_text(
        "✏️ Qaysi ma’lumotni tahrirlaysiz?",
        c.message.chat.id,
        c.message.message_id,
        reply_markup=markup
    )


# 👤 Ism familiya
@bot.callback_query_handler(func=lambda c: c.data == "edit_fullname")
def edit_fullname(c):
    user_id = str(c.message.chat.id)
    edit_state[user_id] = "fullname"
    bot.send_message(user_id, "👤 Yangi ism familiyangizni kiriting:")


# 🔢 Davlat raqami
@bot.callback_query_handler(func=lambda c: c.data == "edit_car_number")
def edit_car_number(c):
    user_id = str(c.message.chat.id)
    edit_state[user_id] = "car_number"
    bot.send_message(
        user_id,
        "🔢 Davlat raqamini kiriting:\n📝 Format: 01 A 123 BC"
    )


# 📞 Telefon raqami
@bot.callback_query_handler(func=lambda c: c.data == "edit_phone")
def edit_phone(c):
    user_id = str(c.message.chat.id)
    edit_state[user_id] = "phone"
    bot.send_message(
        user_id,
        "📞 Telefon raqamingizni kiriting:\n+998901234567 yoki 901234567"
    )


# 🎨 Mashina rangi (inline tugmalar bilan)
@bot.callback_query_handler(func=lambda c: c.data == "edit_car_color")
def edit_car_color(c):
    user_id = str(c.message.chat.id)
    edit_state[user_id] = "car_color"

    # Rang variantlari
    markup = telebot.types.InlineKeyboardMarkup(row_width=3)
    colors = ["Oq", "Qora", "Ko‘k", "Qizil", "Yashil", "Kumush"]
    for color in colors:
        markup.add(
            telebot.types.InlineKeyboardButton(color, callback_data=f"car_color_{color.lower()}")
        )

    bot.send_message(user_id, "🎨 Mashina rangini tanlang:", reply_markup=markup)


# Rang tanlanganini qabul qilish
@bot.callback_query_handler(func=lambda c: c.data.startswith("car_color_"))
def car_color_selected(c):
    user_id = str(c.message.chat.id)
    color = c.data.split("_")[2]  # masalan: 'oq', 'qora'

    drivers_local = load_json(DRIVER_FILE)
    drivers_local.setdefault(user_id, {})
    drivers_local[user_id]["car_color"] = color
    save_json(DRIVER_FILE, drivers_local)

    bot.answer_callback_query(c.id, text=f"🎨 Rang '{color}' tanlandi ✅")
    bot.edit_message_text(
        f"🎨 Mashina rangi '{color}' ga o‘zgartirildi",
        c.message.chat.id,
        c.message.message_id
    )

    if user_id in edit_state:
        del edit_state[user_id]

    # ⚡ Yangilangan barcha ma’lumotlarni foydalanuvchiga ko‘rsatish
    driver = drivers_local.get(user_id, {})
    bot.send_message(
        user_id,
        f"🆔 Haydovchi ID: {user_id}\n"
        f"👤 Ism familiya: {driver.get('fullname', '—')}\n"
        f"🚘 Mashina: {driver.get('car', '—')}\n"
        f"🔢 Davlat raqami: {driver.get('car_number', '—')}\n"
        f"🎨 Rangi: {driver.get('car_color', '—')}\n"
        f"📞 Telefon: {driver.get('phone', '—')}"
    )


# 💾 Saqlash (bitta handler — ism, raqam, telefon uchun)
@bot.message_handler(func=lambda m: str(m.chat.id) in edit_state)
def save_edit_driver_data(m):
    user_id = str(m.chat.id)
    field = edit_state[user_id]
    value = m.text.strip()

    drivers_local = load_json(DRIVER_FILE)

    # 👤 Ism familiya
    if field == "fullname":
        if any(ch.isdigit() for ch in value):
            bot.send_message(user_id, "❌ Ism familiyada raqam bo‘lmasligi kerak!")
            return

    # 🔢 Davlat raqami
    if field == "car_number":
        value = value.upper()
        pattern = r'^[0-9]{2} [A-Z]{1} [0-9]{3} [A-Z]{2}$'
        if not re.match(pattern, value):
            bot.send_message(user_id, "❌ Noto‘g‘ri format!\nMasalan: 01 A 123 BC")
            return

    # 📞 Telefon raqami
    if field == "phone":
        p1 = r'^\+998\d{9}$'
        p2 = r'^998\d{9}$'
        p3 = r'^9\d{8}$'
        p4 = r'^\d{9}$'
        if not (re.match(p1, value) or re.match(p2, value) or
                re.match(p3, value) or re.match(p4, value)):
            bot.send_message(user_id, "❌ Telefon raqami noto‘g‘ri!")
            return

        if value.startswith('998'):
            value = '+' + value
        elif value.startswith('9') and len(value) == 9:
            value = '+998' + value

    # 💾 Saqlash
    drivers_local.setdefault(user_id, {})
    drivers_local[user_id][field] = value
    save_json(DRIVER_FILE, drivers_local)

    bot.send_message(user_id, "✅ Ma’lumot muvaffaqiyatli yangilandi!")
    del edit_state[user_id]

    # ⚡ Yangilangan barcha ma’lumotlarni foydalanuvchiga ko‘rsatish
    driver = drivers_local.get(user_id, {})
    bot.send_message(
        user_id,
        f"🆔 Haydovchi ID: {user_id}\n"
        f"👤 Ism familiya: {driver.get('fullname', '—')}\n"
        f"🚘 Mashina: {driver.get('car', '—')}\n"
        f"🔢 Davlat raqami: {driver.get('car_number', '—')}\n"
        f"🎨 Rangi: {driver.get('car_color', '—')}\n"
        f"📞 Telefon: {driver.get('phone', '—')}"
    )



@bot.callback_query_handler(func=lambda c: c.data == "back_to_driver_info")
def back_to_driver_info(c):  # <--- message emas, c!!!
    user_id = str(c.message.chat.id)  # <--- c.message.chat.id

    # Bloklangan haydovchi tekshiruvi
    if check_blocked_and_respond(c.message.chat.id):
        bot.answer_callback_query(c.id)
        return

    drivers_local = load_json(DRIVER_FILE)
    if user_id not in drivers_local:
        bot.edit_message_text(
            "❗ Siz hali haydovchi sifatida ro'yxatdan o'tmagansiz!\n"
            "Avvalo 🚖 Haydovchi bo'lish tugmasini bosing.",
            c.message.chat.id,
            c.message.message_id
        )
        bot.answer_callback_query(c.id)
        return

    d = drivers_local[user_id]
    text = (
        f"🆔 <b>Haydovchi ID:</b> {user_id}\n"
        f"👤 <b>Ism familiya:</b> {d.get('fullname', '—')}\n"
        f"🚘 <b>Mashina:</b> {d.get('car_model', '—')}\n"
        f"🔢 <b>Davlat raqami:</b> {d.get('car_number', '—')} 🔒\n"
        f"🎨 <b>Rangi:</b> {d.get('car_color', '—')} 🔒\n"
        f"📞 <b>Telefon:</b> {d.get('phone', '—')}\n\n"
        f"🔁 <b>24 soat ichida bekor qilish:</b> {remaining_cancels(user_id)} ta qoldi\n\n"
        f"ℹ️ Davlat raqami va rang faqat admin tomonidan o‘zgartiriladi."
    )

    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        telebot.types.InlineKeyboardButton("✏️ Ma'lumotlarni tahrirlash", callback_data="edit_driver_info")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("💰 Balans", callback_data=f"driver_balance_{user_id}")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("👥 Referal tizim", callback_data="driver_referral")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("📜 Tugallangan buyurtmalar", callback_data="show_finished_orders")
    )

    if user_id in driver_active_order:
        order_id = driver_active_order[user_id]
        markup.add(
            telebot.types.InlineKeyboardButton("📦 Aktiv buyurtma", callback_data=f"active_{order_id}")
        )
    else:
        markup.add(
            telebot.types.InlineKeyboardButton("📦 Aktiv buyurtma yo‘q", callback_data="no_active")
        )

    try:
        bot.edit_message_text(
            text=text,
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            parse_mode="HTML",
            reply_markup=markup
        )
    except:
        bot.send_message(c.message.chat.id, text, parse_mode="HTML", reply_markup=markup)

    bot.answer_callback_query(c.id, "Yangilandi")




@bot.message_handler(commands=['broadcast'])
def broadcast(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "❌ Siz admin emassiz")
        return

    text = message.text.replace("/broadcast", "").strip()
    if not text:
        bot.send_message(message.chat.id, "❗ Foydalanish:\n/broadcast Xabar matni")
        return

    users = load_users()
    sent = 0
    failed = 0

    for user_id in users:
        try:
            bot.send_message(user_id, text)
            sent += 1
        except:
            failed += 1

    bot.send_message(
        message.chat.id,
        f"✅ Yuborildi: {sent}\n❌ Yuborilmadi: {failed}"
    )



@bot.message_handler(commands=['send'])
def send_to_user(message):
    # admin tekshirish
    if message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "❌ Siz admin emassiz!")
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.send_message(
            message.chat.id,
            "❗ Foydalanish:\n/send USER_ID XABAR"
        )
        return

    user_id = parts[1]
    text = parts[2]

    try:
        bot.send_message(user_id, f"📩 Admin xabari:\n\n{text}")
        bot.send_message(message.chat.id, "✅ Xabar yuborildi")
    except Exception as e:
        bot.send_message(
            message.chat.id,
            f"❌ Xatolik! Xabar yuborilmadi\n{e}"
        )





register_admin_handlers(bot, load_json, save_json, DRIVER_FILE, ORDERS_FILE, FINISHED_ORDERS_FILE)



# ========== BOT ISHLAYOTGAN PAYTDA THREAD VA POLLING ==========
if __name__ == "__main__":
    print("Bot ishga tushdi...")

    
    bot.polling(non_stop=True, interval=0, timeout=100)