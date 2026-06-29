import html
import threading
import time
from datetime import datetime

import telebot
from telebot import types

from config import (
    BOT_TOKEN,
    ADMIN_ID,
    BOT_NAME,
    BOT_USERNAME,
    SUPPORT_USERNAME,
    MAX_WAIT_MINUTES,
    TRANSFER_CARD,
    TRANSFER_CONFIRM_PHONE,
    TRANSFER_NOTE,
    MOBILE_BALANCE_NUMBER,
    MOBILE_BALANCE_NOTE,
    USDT_NETWORK,
    USDT_ADDRESS,
    USDT_NOTE,
)

import database as db
from smspool_api import SMSPoolAPI


bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
api = SMSPoolAPI()

# Estados temporales en memoria.
WAITING_DEPOSIT_PROOF = {}
WAITING_SUPPORT_MESSAGE = {}


# -----------------------------
# Utilidades
# -----------------------------
def safe_text(value):
    return html.escape(str(value or ""))


def is_admin(user_id):
    return int(user_id) == int(ADMIN_ID)


def send_admin(text):
    try:
        bot.send_message(ADMIN_ID, text)
    except Exception as e:
        print(f"No se pudo enviar mensaje al admin: {e}")


def username_or_empty(user):
    return user.username or ""


def username_public(user):
    return user.username or "sin_username"


def get_ref_link(user_id):
    username = BOT_USERNAME.replace("@", "").strip()
    return f"https://t.me/{username}?start=ref_{user_id}"


def parse_referrer_from_start(message):
    parts = (message.text or "").split()
    if len(parts) < 2:
        return None

    payload = parts[1].strip()
    if not payload.startswith("ref_"):
        return None

    try:
        referrer_id = int(payload.replace("ref_", ""))
    except ValueError:
        return None

    if referrer_id == int(message.from_user.id):
        return None

    return referrer_id


def order_status_public(status):
    mapping = {
        "created": "Creada",
        "processing": "Procesando",
        "waiting_code": "Esperando código",
        "completed": "Completada",
        "cancelled": "Cancelada",
        "refunded": "Reembolsada",
        "error": "Error",
    }
    return mapping.get(status or "", status or "Desconocido")


def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📲 Comprar número", "💰 Mi saldo")
    markup.row("➕ Recargar saldo", "🧾 Mis compras")
    markup.row("💸 Gana dinero", "🛠 Soporte")
    markup.row("ℹ️ Cómo funciona")
    return markup


def admin_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    # Funciones de usuario también para el admin.
    markup.row("📲 Comprar número", "💰 Mi saldo")
    markup.row("➕ Recargar saldo", "🧾 Mis compras")
    markup.row("💸 Gana dinero", "🛠 Soporte")
    markup.row("ℹ️ Cómo funciona")
    # Funciones privadas.
    markup.row("👑 Panel Admin")
    markup.row("📥 Depósitos pendientes", "🎧 Soportes abiertos")
    markup.row("⚙️ Cambiar precios", "💰 Saldo técnico")
    return markup


def menu_for(user_id):
    return admin_menu() if is_admin(user_id) else main_menu()


# -----------------------------
# Inicio / Menús
# -----------------------------
@bot.message_handler(commands=["start", "menu"])
def start(message):
    referrer_id = parse_referrer_from_start(message)
    db.register_user(message.from_user, referred_by=referrer_id)

    text = f"""
<b>👋 Bienvenido a {safe_text(BOT_NAME)}</b>

Compra números virtuales de forma rápida, segura y automática.

Usa el menú inferior para continuar.
"""
    bot.send_message(message.chat.id, text, reply_markup=menu_for(message.from_user.id))


@bot.message_handler(commands=["saldo"])
def saldo_command(message):
    show_balance(message)


@bot.message_handler(func=lambda message: message.text == "🏠 Menú principal")
def go_main_menu(message):
    bot.send_message(message.chat.id, "🏠 Menú principal", reply_markup=menu_for(message.from_user.id))


@bot.message_handler(func=lambda message: message.text == "👑 Panel Admin")
def show_admin_panel(message):
    if not is_admin(message.from_user.id):
        return

    text = """
<b>👑 Panel Admin</b>

Selecciona una opción del menú inferior.

Comandos útiles:
<code>/aprobar ID MONTO</code>
<code>/rechazar ID</code>
<code>/precio ID PRECIO</code>
<code>/responder USER_ID mensaje</code>
"""
    bot.send_message(message.chat.id, text, reply_markup=admin_menu())


@bot.message_handler(func=lambda message: message.text == "💰 Mi saldo")
def show_balance(message):
    db.register_user(message.from_user)
    balance, held = db.get_balance(message.from_user.id)

    text = f"""
<b>💰 Mi saldo</b>

Saldo disponible: <b>{balance:.2f} USDT</b>
Saldo retenido: <b>{held:.2f} USDT</b>
"""
    bot.send_message(message.chat.id, text, reply_markup=menu_for(message.from_user.id))


# -----------------------------
# Recargas con comprobante
# -----------------------------
@bot.message_handler(func=lambda message: message.text == "➕ Recargar saldo")
def recharge_menu(message):
    db.register_user(message.from_user)

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💳 Transferencia bancaria", callback_data="deposit_transferencia"))
    markup.add(types.InlineKeyboardButton("📱 Saldo móvil", callback_data="deposit_saldo_movil"))
    markup.add(types.InlineKeyboardButton("💵 USDT BEP20", callback_data="deposit_usdt"))

    bot.send_message(
        message.chat.id,
        "<b>➕ Recargar saldo</b>\n\nElige el método de recarga:",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("deposit_"))
def deposit_selected(call):
    method = call.data.replace("deposit_", "")

    method_names = {
        "transferencia": "Transferencia bancaria",
        "saldo_movil": "Saldo móvil",
        "usdt": "USDT BEP20"
    }

    method_public = method_names.get(method, method)

    db.register_user(call.from_user)
    deposit_id = db.create_deposit(
        call.from_user.id,
        username_or_empty(call.from_user),
        method_public
    )

    WAITING_DEPOSIT_PROOF[call.from_user.id] = deposit_id

    if method == "transferencia":
        payment_info = f"""
<b>💳 Transferencia bancaria</b>

Tarjeta:
<code>{safe_text(TRANSFER_CARD)}</code>

Confirmación:
<code>{safe_text(TRANSFER_CONFIRM_PHONE)}</code>

📌 {safe_text(TRANSFER_NOTE)}
"""
    elif method == "saldo_movil":
        payment_info = f"""
<b>📱 Saldo móvil</b>

Número:
<code>{safe_text(MOBILE_BALANCE_NUMBER)}</code>

📌 {safe_text(MOBILE_BALANCE_NOTE)}
"""
    elif method == "usdt":
        payment_info = f"""
<b>💵 Pago en USDT</b>

Red:
<code>{safe_text(USDT_NETWORK)}</code>

Dirección:
<code>{safe_text(USDT_ADDRESS)}</code>

📌 {safe_text(USDT_NOTE)}
"""
    else:
        payment_info = "Método de pago no reconocido."

    user_text = f"""
<b>📥 Solicitud de recarga creada</b>

Método: <b>{safe_text(method_public)}</b>
Número de solicitud: <b>#{deposit_id}</b>

{payment_info}

<b>Ahora envía aquí la foto o documento del comprobante.</b>
También puedes enviar texto si pagaste por USDT y quieres mandar hash de transacción.
"""
    bot.send_message(call.message.chat.id, user_text)

    admin_text = f"""
<b>📥 Nueva solicitud de depósito</b>

ID: <b>#{deposit_id}</b>
Usuario: @{safe_text(username_public(call.from_user))}
User ID: <code>{call.from_user.id}</code>
Método: <b>{safe_text(method_public)}</b>
Estado: esperando comprobante

Cuando verifiques el pago:
<code>/aprobar {deposit_id} cantidad_usdt</code>

Ejemplo:
<code>/aprobar {deposit_id} 7.25</code>

Para rechazar:
<code>/rechazar {deposit_id}</code>
"""
    send_admin(admin_text)
    bot.answer_callback_query(call.id)


def forward_deposit_proof(message, deposit_id):
    if message.content_type == "photo":
        proof_type = "photo"
        file_id = message.photo[-1].file_id
        proof_text = message.caption or ""
    elif message.content_type == "document":
        proof_type = "document"
        file_id = message.document.file_id
        proof_text = message.caption or ""
    else:
        proof_type = "text"
        file_id = None
        proof_text = message.text or ""

    db.save_deposit_proof(
        deposit_id=deposit_id,
        proof_type=proof_type,
        file_id=file_id,
        text=proof_text
    )

    dep = db.get_deposit(deposit_id)
    if dep:
        _, user_id, username, method, status, usdt_amount, created_at, updated_at, proof_type_db, proof_file_id, proof_text_db = dep
    else:
        user_id, username, method = message.from_user.id, username_or_empty(message.from_user), "Desconocido"

    admin_caption = f"""
<b>📎 Comprobante recibido</b>

Depósito: <b>#{deposit_id}</b>
Usuario: @{safe_text(username or username_public(message.from_user))}
User ID: <code>{user_id}</code>
Método: <b>{safe_text(method)}</b>

Aprobar:
<code>/aprobar {deposit_id} 10</code>

Rechazar:
<code>/rechazar {deposit_id}</code>
"""

    try:
        if message.content_type == "photo":
            bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=admin_caption)
        elif message.content_type == "document":
            bot.send_document(ADMIN_ID, message.document.file_id, caption=admin_caption)
        else:
            bot.send_message(ADMIN_ID, admin_caption + f"\nTexto/hash:\n<code>{safe_text(proof_text)}</code>")
    except Exception as e:
        send_admin(admin_caption + f"\nNo se pudo reenviar el archivo automáticamente: <code>{safe_text(e)}</code>")

    bot.send_message(
        message.chat.id,
        f"✅ Comprobante recibido para la solicitud <b>#{deposit_id}</b>.\n\nEspera mientras verificamos tu pago y configuramos tu saldo en USDT.",
        reply_markup=menu_for(message.from_user.id)
    )
    WAITING_DEPOSIT_PROOF.pop(message.from_user.id, None)


@bot.message_handler(commands=["aprobar"])
def approve_deposit_command(message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()

    if len(parts) != 3:
        bot.send_message(message.chat.id, "Uso correcto: /aprobar ID CANTIDAD\nEjemplo: /aprobar 1 7.25")
        return

    try:
        deposit_id = int(parts[1])
        amount = float(parts[2])
    except ValueError:
        bot.send_message(message.chat.id, "ID o cantidad inválida.")
        return

    result = db.approve_deposit(deposit_id, amount)

    if not result:
        bot.send_message(message.chat.id, "No se pudo aprobar. Verifica que el depósito exista y esté pendiente.")
        return

    if isinstance(result, dict):
        user_id = result["user_id"]
        referrer_id = result.get("referrer_id")
        reward = float(result.get("reward", 0.0))
    else:
        # Compatibilidad con database.py viejo.
        user_id = result
        referrer_id = None
        reward = 0.0

    bot.send_message(message.chat.id, f"✅ Depósito #{deposit_id} aprobado por {amount:.2f} USDT.")

    bot.send_message(
        user_id,
        f"✅ <b>Depósito aprobado</b>\n\nSe acreditaron <b>{amount:.2f} USDT</b> a tu saldo.\nYa puedes comprar números virtuales."
    )

    if referrer_id and reward > 0:
        try:
            bot.send_message(
                referrer_id,
                f"""
💸 <b>Referido válido</b>

Uno de tus invitados realizó una recarga aprobada.

Recompensa acreditada: <b>{reward:.2f} USDT</b>
"""
            )
        except Exception:
            pass

        bot.send_message(
            message.chat.id,
            f"💸 Recompensa de referido acreditada: {reward:.2f} USDT al usuario {referrer_id}."
        )


@bot.message_handler(commands=["rechazar"])
def reject_deposit_command(message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()

    if len(parts) != 2:
        bot.send_message(message.chat.id, "Uso correcto: /rechazar ID\nEjemplo: /rechazar 1")
        return

    try:
        deposit_id = int(parts[1])
    except ValueError:
        bot.send_message(message.chat.id, "ID inválido.")
        return

    result = db.reject_deposit(deposit_id)

    if not result:
        bot.send_message(message.chat.id, "No se pudo rechazar. Verifica que el depósito exista y esté pendiente.")
        return

    user_id = result["user_id"] if isinstance(result, dict) else result

    bot.send_message(message.chat.id, f"❌ Depósito #{deposit_id} rechazado.")

    try:
        bot.send_message(
            user_id,
            "❌ <b>Depósito rechazado</b>\n\nNo pudimos confirmar el pago recibido. Si crees que fue un error, contacta soporte."
        )
    except Exception:
        pass


@bot.message_handler(func=lambda message: message.text == "📥 Depósitos pendientes")
def pending_deposits(message):
    if not is_admin(message.from_user.id):
        return

    rows = db.get_pending_deposits()

    if not rows:
        bot.send_message(message.chat.id, "No hay depósitos pendientes.", reply_markup=admin_menu())
        return

    text = "<b>📥 Depósitos pendientes</b>\n\n"

    for row in rows:
        deposit_id, user_id, username, method, status, created_at, proof_type = row
        text += f"ID: <b>#{deposit_id}</b>\n"
        text += f"Usuario: @{safe_text(username or 'sin_username')}\n"
        text += f"User ID: <code>{user_id}</code>\n"
        text += f"Método: {safe_text(method)}\n"
        text += f"Estado: {safe_text(status)}\n"
        text += f"Comprobante: {'sí' if proof_type else 'pendiente'}\n"
        text += f"Fecha: {safe_text(created_at)}\n"
        text += f"Aprobar: <code>/aprobar {deposit_id} 10</code>\n"
        text += f"Rechazar: <code>/rechazar {deposit_id}</code>\n\n"

    bot.send_message(message.chat.id, text, reply_markup=admin_menu())


# -----------------------------
# Compras
# -----------------------------
@bot.message_handler(func=lambda message: message.text == "💰 Saldo técnico")
def technical_balance(message):
    if not is_admin(message.from_user.id):
        return

    result = api.get_balance()

    bot.send_message(
        message.chat.id,
        f"<b>💰 Saldo técnico</b>\n\n<code>{safe_text(result)}</code>",
        reply_markup=admin_menu()
    )


@bot.message_handler(func=lambda message: message.text == "📲 Comprar número")
def buy_number_menu(message):
    db.register_user(message.from_user)
    products = db.get_active_products()

    if not products:
        bot.send_message(message.chat.id, "No hay servicios disponibles en este momento.")
        return

    markup = types.InlineKeyboardMarkup()

    for product in products:
        product_id, service, country, price = product
        text = f"{service} {country} — {price:.2f} USDT"
        markup.add(types.InlineKeyboardButton(text, callback_data=f"buy_{product_id}"))

    bot.send_message(
        message.chat.id,
        "<b>📲 Comprar número virtual</b>\n\nElige una opción disponible:",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def buy_selected(call):
    product_id = int(call.data.replace("buy_", ""))
    product = db.get_product(product_id)

    if not product or product[6] != 1:
        bot.send_message(call.message.chat.id, "Este servicio no está disponible temporalmente.")
        bot.answer_callback_query(call.id)
        return

    price = float(product[3])
    balance, held = db.get_balance(call.from_user.id)

    if balance < price:
        text = f"""
⚠️ <b>Saldo insuficiente</b>

No tienes crédito disponible suficiente para completar esta compra.

💰 Saldo actual: <b>{balance:.2f} USDT</b>
💵 Precio del número: <b>{price:.2f} USDT</b>

Por favor recarga saldo para continuar.
"""
        bot.send_message(call.message.chat.id, text)
        bot.answer_callback_query(call.id)
        return

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Confirmar compra", callback_data=f"confirmbuy_{product_id}"))
    markup.add(types.InlineKeyboardButton("❌ Cancelar", callback_data="cancelbuy"))

    text = f"""
<b>📋 Confirmar compra</b>

Servicio: <b>{safe_text(product[1])}</b>
País: <b>{safe_text(product[2])}</b>
Precio: <b>{price:.2f} USDT</b>
Tu saldo: <b>{balance:.2f} USDT</b>

¿Deseas continuar?
"""
    bot.send_message(call.message.chat.id, text, reply_markup=markup)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "cancelbuy")
def cancel_buy(call):
    bot.send_message(call.message.chat.id, "Compra cancelada.")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("confirmbuy_"))
def confirm_buy(call):
    product_id = int(call.data.replace("confirmbuy_", ""))
    product = db.get_product(product_id)

    if not product:
        bot.send_message(call.message.chat.id, "Este servicio no está disponible temporalmente.")
        bot.answer_callback_query(call.id)
        return

    price = float(product[3])
    ok = db.hold_balance(call.from_user.id, price)

    if not ok:
        balance, held = db.get_balance(call.from_user.id)
        text = f"""
⚠️ <b>Saldo insuficiente</b>

No tienes crédito disponible suficiente para completar esta compra.

💰 Saldo actual: <b>{balance:.2f} USDT</b>
💵 Precio del número: <b>{price:.2f} USDT</b>

Por favor recarga saldo para continuar.
"""
        bot.send_message(call.message.chat.id, text)
        bot.answer_callback_query(call.id)
        return

    order_id = db.create_order(
        call.from_user.id,
        username_or_empty(call.from_user),
        product,
        status="processing"
    )

    bot.send_message(
        call.message.chat.id,
        "⏳ Procesando solicitud...\n\nEstamos buscando un número disponible. Espera unos segundos."
    )

    result = api.purchase_sms(product[4], product[5])

    if not isinstance(result, dict):
        db.release_held_balance(call.from_user.id, price)
        db.cancel_order(order_id)
        bot.send_message(
            call.message.chat.id,
            "⚠️ No pudimos procesar esta solicitud en este momento. Intenta nuevamente en unos minutos."
        )
        send_admin(f"Error técnico compra orden local #{order_id}: respuesta no válida: {safe_text(result)}")
        bot.answer_callback_query(call.id)
        return

    number = result.get("number") or result.get("phone") or result.get("phonenumber")
    external_order_id = result.get("order_id") or result.get("orderid") or result.get("id")

    if not number or not external_order_id:
        db.release_held_balance(call.from_user.id, price)
        db.cancel_order(order_id)

        bot.send_message(
            call.message.chat.id,
            "❌ No hay números disponibles para este servicio en este momento.\n\nIntenta nuevamente en unos minutos o elige otro país disponible."
        )
        send_admin(f"Error técnico compra orden local #{order_id}:\n<code>{safe_text(result)}</code>")
        bot.answer_callback_query(call.id)
        return

    db.update_order_external(
        order_id,
        external_order_id=str(external_order_id),
        phone_number=str(number),
        status="waiting_code"
    )

    text = f"""
✅ <b>Número asignado</b>

Servicio: <b>{safe_text(product[1])}</b>
País: <b>{safe_text(product[2])}</b>
Número: <code>{safe_text(number)}</code>

⏳ Esperando código...
Tiempo máximo aproximado: <b>{MAX_WAIT_MINUTES} minutos</b>.

Te avisaremos automáticamente cuando llegue.

⚠️ <b>Recomendación importante:</b>
Si el código demora más de <b>1 minuto</b> en llegar, solicita reembolso y pide otro número.

Si vuelve a fallar, prueba con otro país disponible, ya que la efectividad puede variar según el servicio y la región.
"""

    refund_markup = types.InlineKeyboardMarkup()
    refund_markup.add(types.InlineKeyboardButton("🔁 Solicitar reembolso", callback_data=f"refund_{order_id}"))

    bot.send_message(call.message.chat.id, text, reply_markup=refund_markup)

    send_admin(f"""
📲 Orden creada

Local: #{order_id}
Usuario: @{safe_text(username_public(call.from_user))}
Servicio: {safe_text(product[1])} {safe_text(product[2])}
Precio: {price:.2f} USDT
Orden técnica: {safe_text(external_order_id)}
""")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("refund_"))
def refund_order(call):
    try:
        order_id = int(call.data.replace("refund_", ""))
    except ValueError:
        bot.answer_callback_query(call.id, "Solicitud inválida.")
        return

    order = db.get_order(order_id)

    if not order:
        bot.send_message(call.message.chat.id, "No encontramos esta orden.")
        bot.answer_callback_query(call.id)
        return

    local_order_id = order[0]
    user_id = order[1]
    service_name = order[4]
    country_name = order[5]
    price = float(order[6])
    external_order_id = order[8]
    code = order[9]
    status = order[10]

    if int(call.from_user.id) != int(user_id):
        bot.answer_callback_query(call.id, "Esta orden no pertenece a tu cuenta.")
        return

    if status == "completed" or code:
        bot.send_message(
            call.message.chat.id,
            "❌ Esta orden no puede ser reembolsada porque el código ya fue recibido."
        )
        bot.answer_callback_query(call.id)
        return

    if status not in ["waiting_code", "processing"]:
        bot.send_message(
            call.message.chat.id,
            "⚠️ Esta orden ya no está disponible para reembolso."
        )
        bot.answer_callback_query(call.id)
        return

    bot.send_message(
        call.message.chat.id,
        "⏳ Procesando solicitud de reembolso...\n\nEspera unos segundos."
    )

    cancel_result = None
    if external_order_id:
        cancel_result = api.cancel_sms(external_order_id)

    db.release_held_balance(user_id, price)
    db.mark_order_refunded(local_order_id)

    bot.send_message(
        call.message.chat.id,
        f"""
✅ <b>Reembolso procesado</b>

Orden: <b>#{local_order_id}</b>
Servicio: <b>{safe_text(service_name)}</b>
País: <b>{safe_text(country_name)}</b>

Se devolvieron <b>{price:.2f} USDT</b> a tu saldo disponible.
"""
    )

    send_admin(f"""
🔁 Reembolso solicitado

Orden local: #{local_order_id}
Usuario: @{safe_text(username_public(call.from_user))}
Servicio: {safe_text(service_name)} {safe_text(country_name)}
Monto devuelto: {price:.2f} USDT

Respuesta técnica:
<code>{safe_text(cancel_result)}</code>
""")
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda message: message.text == "🧾 Mis compras")
def my_orders(message):
    rows = db.get_user_orders(message.from_user.id, limit=10)

    if not rows:
        bot.send_message(message.chat.id, "🧾 No tienes compras registradas todavía.")
        return

    text = "<b>🧾 Mis compras</b>\n\n"
    markup = types.InlineKeyboardMarkup()

    for row in rows:
        order_id, service_name, country_name, public_price, phone_number, code, status, created_at = row
        text += f"<b>#{order_id}</b> — {safe_text(service_name)} {safe_text(country_name)}\n"
        text += f"Precio: <b>{float(public_price):.2f} USDT</b>\n"
        text += f"Estado: <b>{order_status_public(status)}</b>\n"

        if phone_number:
            text += f"Número: <code>{safe_text(phone_number)}</code>\n"

        if code:
            text += f"Código: <code>{safe_text(code)}</code>\n"

        text += f"Fecha: {safe_text(created_at)}\n\n"

        if status in ["waiting_code", "processing"] and not code:
            markup.add(types.InlineKeyboardButton(f"🔁 Reembolsar orden #{order_id}", callback_data=f"refund_{order_id}"))

    bot.send_message(message.chat.id, text, reply_markup=markup if markup.keyboard else None)


# -----------------------------
# Referidos
# -----------------------------
@bot.message_handler(func=lambda message: message.text == "💸 Gana dinero")
def referral_menu(message):
    db.register_user(message.from_user)
    summary = db.get_referral_summary(message.from_user.id)
    ref_link = get_ref_link(message.from_user.id)

    text = f"""
<b>💸 Gana dinero con {safe_text(BOT_NAME)}</b>

Invita personas y gana <b>0.30 USDT</b> de crédito interno por cada referido válido.

<b>Tu link:</b>
<code>{safe_text(ref_link)}</code>

📊 <b>Resumen rápido</b>
👥 Invitados totales: <b>{summary['total']}</b>
⏳ Pendientes sin recarga aprobada: <b>{summary['pending']}</b>
✅ Referidos válidos: <b>{summary['valid']}</b>
💰 Ganancias generadas: <b>{summary['earnings']:.2f} USDT</b>

Un referido solo cuenta cuando recarga y su depósito es aprobado.
"""

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("ℹ️ Cómo funciona", callback_data="ref_how"))
    markup.add(types.InlineKeyboardButton("📊 Ver resumen", callback_data="ref_summary"))
    markup.add(types.InlineKeyboardButton("🔗 Mi link", callback_data="ref_link"))
    bot.send_message(message.chat.id, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("ref_"))
def referral_callbacks(call):
    db.register_user(call.from_user)

    if call.data == "ref_link":
        bot.send_message(
            call.message.chat.id,
            f"🔗 <b>Tu link de invitación</b>\n\n<code>{safe_text(get_ref_link(call.from_user.id))}</code>\n\nCompártelo con tus clientes o contactos."
        )
        bot.answer_callback_query(call.id)
        return

    if call.data == "ref_how":
        bot.send_message(
            call.message.chat.id,
            """
ℹ️ <b>Cómo funciona el sistema de referidos</b>

1. Comparte tu link de invitación.
2. La persona entra al bot usando tu link.
3. Esa persona realiza una recarga.
4. La recarga debe ser aprobada por administración.
5. Cuando sea aprobada, ganas <b>0.30 USDT</b> de crédito interno.

⚠️ Los usuarios que solo entren al bot pero no recarguen quedan como pendientes y no generan recompensa.
"""
        )
        bot.answer_callback_query(call.id)
        return

    if call.data == "ref_summary":
        summary = db.get_referral_summary(call.from_user.id)
        bot.send_message(
            call.message.chat.id,
            f"""
📊 <b>Resumen de referidos</b>

👥 Invitados totales: <b>{summary['total']}</b>
⏳ Pendientes sin recarga aprobada: <b>{summary['pending']}</b>
✅ Referidos válidos: <b>{summary['valid']}</b>
💰 Ganancias generadas: <b>{summary['earnings']:.2f} USDT</b>
"""
        )
        bot.answer_callback_query(call.id)
        return


# -----------------------------
# Soporte
# -----------------------------
@bot.message_handler(func=lambda message: message.text == "🛠 Soporte")
def support(message):
    WAITING_SUPPORT_MESSAGE[message.from_user.id] = True
    bot.send_message(
        message.chat.id,
        """
🛠 <b>Soporte</b>

Escribe tu duda o problema en este chat.
También puedes enviar una foto o documento si hace falta.

Tu mensaje será enviado al panel de administración.
"""
    )


@bot.message_handler(func=lambda message: message.text == "🎧 Soportes abiertos")
def support_list(message):
    if not is_admin(message.from_user.id):
        return

    rows = db.get_support_tickets(limit=10)

    if not rows:
        bot.send_message(message.chat.id, "No hay consultas de soporte registradas.", reply_markup=admin_menu())
        return

    text = "<b>🎧 Últimas consultas de soporte</b>\n\n"

    for row in rows:
        ticket_id, user_id, username, message_type, text_body, status, created_at = row
        text += f"Ticket: <b>#{ticket_id}</b>\n"
        text += f"Usuario: @{safe_text(username or 'sin_username')}\n"
        text += f"User ID: <code>{user_id}</code>\n"
        text += f"Estado: {safe_text(status)}\n"
        text += f"Fecha: {safe_text(created_at)}\n"
        if text_body:
            text += f"Mensaje: {safe_text(text_body[:200])}\n"
        text += f"Responder: <code>/responder {user_id} tu mensaje</code>\n\n"

    bot.send_message(message.chat.id, text, reply_markup=admin_menu())


@bot.message_handler(commands=["responder"])
def reply_user(message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=2)

    if len(parts) < 3:
        bot.send_message(message.chat.id, "Uso correcto: /responder USER_ID mensaje")
        return

    try:
        user_id = int(parts[1])
    except ValueError:
        bot.send_message(message.chat.id, "User ID inválido.")
        return

    response_text = parts[2]

    try:
        bot.send_message(user_id, f"🛠 <b>Respuesta de soporte</b>\n\n{safe_text(response_text)}")
        db.close_user_support_tickets(user_id)
        bot.send_message(message.chat.id, "✅ Respuesta enviada.")
    except Exception as e:
        bot.send_message(message.chat.id, f"No se pudo enviar la respuesta: <code>{safe_text(e)}</code>")


def handle_support_message(message):
    user_text = message.caption or message.text or ""

    if message.content_type == "photo":
        msg_type = "photo"
    elif message.content_type == "document":
        msg_type = "document"
    else:
        msg_type = "text"

    ticket_id = db.create_support_ticket(
        user_id=message.from_user.id,
        username=username_or_empty(message.from_user),
        message_type=msg_type,
        text=user_text
    )

    admin_caption = f"""
🎧 <b>Nueva consulta de soporte</b>

Ticket: <b>#{ticket_id}</b>
Usuario: @{safe_text(username_public(message.from_user))}
User ID: <code>{message.from_user.id}</code>
Tipo: <b>{safe_text(msg_type)}</b>

Responder:
<code>/responder {message.from_user.id} tu mensaje</code>
"""

    try:
        if message.content_type == "photo":
            bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=admin_caption + f"\nMensaje:\n{safe_text(user_text)}")
        elif message.content_type == "document":
            bot.send_document(ADMIN_ID, message.document.file_id, caption=admin_caption + f"\nMensaje:\n{safe_text(user_text)}")
        else:
            bot.send_message(ADMIN_ID, admin_caption + f"\nMensaje:\n{safe_text(user_text)}")
    except Exception as e:
        send_admin(admin_caption + f"\nError al reenviar soporte: <code>{safe_text(e)}</code>")

    bot.send_message(
        message.chat.id,
        "✅ Tu mensaje fue enviado a soporte. Te responderemos lo antes posible.",
        reply_markup=menu_for(message.from_user.id)
    )
    WAITING_SUPPORT_MESSAGE.pop(message.from_user.id, None)


# -----------------------------
# Info / Admin precios
# -----------------------------
@bot.message_handler(func=lambda message: message.text == "ℹ️ Cómo funciona")
def how_it_works(message):
    text = f"""
<b>ℹ️ Cómo funciona {safe_text(BOT_NAME)}</b>

1. Recarga saldo.
2. Envía el comprobante por el bot.
3. Espera la aprobación.
4. Compra el número virtual que necesites.
5. Recibe el número.
6. Espera el código automáticamente.
7. Si el código no llega, puedes solicitar reembolso mientras la orden siga activa.

📌 Recomendación:
Para uso continuo, deja reposar el número 48 horas.
Para uso de negocios/proveedores, úsalo con cuidado las primeras 5-6 horas.

⚠️ Los números virtuales normalmente reciben solo 1 código.
"""
    bot.send_message(message.chat.id, text)


@bot.message_handler(func=lambda message: message.text == "⚙️ Cambiar precios")
def prices_info(message):
    if not is_admin(message.from_user.id):
        return

    products = db.get_active_products()
    text = "<b>⚙️ Cambiar precios</b>\n\n"

    for product in products:
        product_id, service, country, price = product
        text += f"{product_id}. {safe_text(service)} {safe_text(country)} — {price:.2f} USDT\n"

    text += "\nPara cambiar un precio usa:\n"
    text += "<code>/precio ID NUEVO_PRECIO</code>\n\n"
    text += "Ejemplo:\n<code>/precio 1 4.50</code>"

    bot.send_message(message.chat.id, text, reply_markup=admin_menu())


@bot.message_handler(commands=["precio"])
def change_price(message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()

    if len(parts) != 3:
        bot.send_message(message.chat.id, "Uso correcto: /precio ID PRECIO\nEjemplo: /precio 1 4.50")
        return

    try:
        product_id = int(parts[1])
        new_price = float(parts[2])
    except ValueError:
        bot.send_message(message.chat.id, "ID o precio inválido.")
        return

    product = db.get_product(product_id)

    if not product:
        bot.send_message(message.chat.id, "Producto no encontrado.")
        return

    db.update_product_price(product_id, new_price)
    bot.send_message(
        message.chat.id,
        f"✅ Precio actualizado.\n\n{safe_text(product[1])} {safe_text(product[2])} ahora cuesta {new_price:.2f} USDT.",
        reply_markup=admin_menu()
    )


# -----------------------------
# Monitor automático de códigos/reembolsos
# -----------------------------
def extract_code_from_response(result):
    if not isinstance(result, dict):
        return None

    possible_keys = ["code", "sms", "message", "text", "value"]

    for key in possible_keys:
        value = result.get(key)

        if not value:
            continue

        if isinstance(value, list) and value:
            value = value[0]

        if isinstance(value, dict):
            for sub_key in possible_keys:
                sub_value = value.get(sub_key)
                if sub_value:
                    return str(sub_value)

        value = str(value).strip()
        if value and value.lower() not in ["pending", "none", "null", "0"]:
            return value

    return None


def order_monitor_loop():
    while True:
        try:
            waiting_orders = db.get_waiting_orders()

            for order in waiting_orders:
                order_id, user_id, service_name, country_name, price, phone_number, external_order_id, created_at = order

                result = api.check_sms(external_order_id)
                code = extract_code_from_response(result)

                if code:
                    db.complete_order(order_id, code)
                    db.confirm_held_balance(user_id, price)

                    bot.send_message(
                        user_id,
                        f"""
✅ <b>Código recibido</b>

Orden: <b>#{order_id}</b>
Servicio: <b>{safe_text(service_name)}</b>
País: <b>{safe_text(country_name)}</b>
Número: <code>{safe_text(phone_number)}</code>
Código: <code>{safe_text(code)}</code>

Gracias por usar {safe_text(BOT_NAME)}.

📌 Recomendación:
Para uso continuo, deja reposar el número 48 horas.
Para uso de negocios/proveedores, úsalo con cuidado las primeras 5-6 horas.

⚠️ Los números virtuales normalmente reciben solo 1 código.
"""
                    )
                    send_admin(f"✅ Código entregado\nOrden #{order_id}\nUsuario: {user_id}\nServicio: {safe_text(service_name)} {safe_text(country_name)}")
                    continue

                if db.order_is_expired(created_at, MAX_WAIT_MINUTES):
                    cancel_result = api.cancel_sms(external_order_id)
                    db.release_held_balance(user_id, price)
                    db.mark_order_refunded(order_id)

                    bot.send_message(
                        user_id,
                        f"""
🔁 <b>Reembolso automático</b>

La orden <b>#{order_id}</b> no recibió código dentro del tiempo máximo.

Se devolvieron <b>{float(price):.2f} USDT</b> a tu saldo disponible.
"""
                    )
                    send_admin(f"🔁 Reembolso automático\nOrden #{order_id}\nUsuario: {user_id}\nServicio: {safe_text(service_name)} {safe_text(country_name)}\nRespuesta técnica: {safe_text(cancel_result)}")

        except Exception as e:
            try:
                send_admin(f"⚠️ Error en monitor de órdenes:\n<code>{safe_text(e)}</code>")
            except Exception:
                pass

        time.sleep(25)


@bot.message_handler(content_types=["photo", "document", "text"])
def catch_user_messages(message):
    if message.content_type == "text" and message.text and message.text.startswith("/"):
        return

    if message.from_user.id in WAITING_DEPOSIT_PROOF:
        deposit_id = WAITING_DEPOSIT_PROOF.get(message.from_user.id)
        forward_deposit_proof(message, deposit_id)
        return

    if message.from_user.id in WAITING_SUPPORT_MESSAGE:
        handle_support_message(message)
        return


def run():
    db.init_db()
    monitor_thread = threading.Thread(target=order_monitor_loop, daemon=True)
    monitor_thread.start()
    print("Bot iniciado correctamente...")
    bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)


if __name__ == "__main__":
    run()
