import requests
from config import SMSPOOL_API_KEY


BASE_URL = "https://api.smspool.net"


class SMSPoolAPI:
    def __init__(self):
        self.key = SMSPOOL_API_KEY

    def _post(self, endpoint, data=None, timeout=30):
        if data is None:
            data = {}

        data["key"] = self.key
        url = f"{BASE_URL}{endpoint}"

        try:
            response = requests.post(url, data=data, timeout=timeout)
            try:
                return response.json()
            except Exception:
                return {
                    "success": False,
                    "error": "Respuesta no válida",
                    "raw": response.text
                }
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_balance(self):
        return self._post("/request/balance")

    def get_countries(self):
        return self._post("/country/retrieve_all")

    def get_services(self, country=None):
        data = {}
        if country:
            data["country"] = country
        return self._post("/service/retrieve_all", data)

    def get_success_rate(self, service, country):
        data = {
            "service": service,
            "country": country
        }
        return self._post("/request/success_rate", data)

    def purchase_sms(self, service, country, max_price=None):
        data = {
            "service": service,
            "country": country,
            "pricing_option": "0",
            "quantity": "1"
        }

        if max_price is not None:
            data["max_price"] = str(max_price)

        return self._post("/purchase/sms", data)

    def check_sms(self, order_id):
        data = {
            "orderid": order_id
        }
        return self._post("/sms/check", data)

    def cancel_sms(self, order_id):
        data = {
            "orderid": order_id
        }
        return self._post("/sms/cancel", data)