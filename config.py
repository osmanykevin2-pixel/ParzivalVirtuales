import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")

load_dotenv(ENV_PATH, override=True)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
SMSPOOL_API_KEY = os.getenv("SMSPOOL_API_KEY", "").strip()
BOT_NAME = os.getenv("BOT_NAME", "Parzival Virtuales").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "@Parzivalvirtualesbot").strip()
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@ParzivalFF").strip()

DB_NAME = "bot_database.db"

# Tiempo máximo esperando código, en minutos
MAX_WAIT_MINUTES = 20

# Seguridad: el proveedor nunca debe mencionarse al cliente.
PUBLIC_PROVIDER_NAME = "servicio"

# Datos de pago
TRANSFER_CARD = "9227959879784218"
TRANSFER_CONFIRM_PHONE = "56587187"
TRANSFER_NOTE = "Realiza el pago y envía el comprobante por este chat."

MOBILE_BALANCE_NUMBER = "55977179"
MOBILE_BALANCE_NOTE = "Realiza el envío de saldo móvil y manda el comprobante por este chat."

USDT_NETWORK = "BEP20"
USDT_ADDRESS = "0x6b282a527fCE9b385cC2d94dA198044c94010c40"
USDT_NOTE = "Envía USDT por la red BEP20 y manda el comprobante o hash de la transacción por este chat."