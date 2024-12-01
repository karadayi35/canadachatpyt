import os
import json
import re
from collections import deque
from twisted.internet import reactor, task
from autobahn.twisted.websocket import WebSocketServerFactory, WebSocketServerProtocol
from telethon import TelegramClient, events
from twisted.internet.defer import inlineCallbacks
from twisted.internet.task import deferLater
from twisted.web import server, resource

class MyAPI(resource.Resource):
    isLeaf = True

    # CORS İzinlerini Ayarlamak için render_OPTIONS Ekleyin
    def render_OPTIONS(self, request):
        request.setHeader(b"Access-Control-Allow-Origin", b"*")
        request.setHeader(b"Access-Control-Allow-Methods", b"GET, POST, OPTIONS")
        request.setHeader(b"Access-Control-Allow-Headers", b"Content-Type")
        return b""

    # GET Yöntemi İçin CORS Başlıkları
    def render_GET(self, request):
        request.setHeader(b"Access-Control-Allow-Origin", b"*")  # Tüm domainlere izin ver
        return b"GET request received from React!"

    # POST Yöntemi İçin CORS Başlıkları
    def render_POST(self, request):
        data = request.content.read()
        request.setHeader(b"Access-Control-Allow-Origin", b"*")  # Tüm domainlere izin ver
        print(f"POST data received: {data.decode('utf8')}")
        return b"POST request received from React!"

# Telegram API bilgileri
API_ID = 22856944
API_HASH = "6d75275d1527bd5cda837d04fb984877"
SESSION_NAME = "twisted_session"
GROUP_ID = -1001216775179  # Dinlenecek grup ID'si

# Kullanıcılar ve bot bilgileri
users = {}  # {'kullanici_adi': {'connection': connection_object}}
message_queue = deque()  # Mesaj kuyruğu

bots = {
    "AcademyBot": {
        "icon": "academy_icon.png",
        "message": "Telegram grubumuza katılın <a href='https://t.me/example' target='_blank'>Link</a>",
    },
    "StakeBot": {
        "icon": "stake_icon.png",
        "message": "Best Casino <a href='https://stake.com' target='_blank'>Link</a>",
    },
    "SlotticaBot": {
        "icon": "slottica_icon.png",
        "message": "Best Casino <a href='https://slottica.com' target='_blank'>Link</a>",
    },
    "BetsioBot": {
        "icon": "betsio_icon.png",
        "message": "Best Casino <a href='https://betsio.com' target='_blank'>Link</a>",
    },
}

# WebSocket protokolü
class ChatProtocol(WebSocketServerProtocol):
    def onConnect(self, request):
        print(f"Yeni bağlantı: {request.peer}")

    def onOpen(self):
        print("Bağlantı açıldı")

    def onMessage(self, payload, isBinary):
        if not isBinary:
            data = json.loads(payload.decode("utf-8"))
            if data["type"] == "register":  # Kullanıcı kaydı
                username = data["username"]
                if username not in users:
                    users[username] = {"connection": self}
                    self.sendMessage(
                        json.dumps(
                            {
                                "type": "register_success",
                                "message": f"Hoşgeldin, {username}!",
                            }
                        ).encode("utf-8")
                    )
                else:
                    self.sendMessage(
                        json.dumps(
                            {
                                "type": "register_success",
                                "message": f"Tekrar hoşgeldin, {username}!",
                            }
                        ).encode("utf-8")
                    )
            elif data["type"] == "message":  # Mesaj gönderimi
                username = data["username"]
                message = data["message"]
                icon = data["icon"]  # Frontend'den gelen ikon bilgisi
                if username in users:  # Sadece kayıtlı kullanıcılar yazabilir
                    for user_data in users.values():
                        user_data["connection"].sendMessage(
                            json.dumps(
                                {
                                    "type": "message",
                                    "username": username,
                                    "icon": icon,
                                    "message": message,
                                }
                            ).encode("utf-8")
                        )
                else:
                    self.sendMessage(
                        json.dumps(
                            {
                                "type": "error",
                                "message": "Yazabilmek için kayıt olmanız gerekiyor.",
                            }
                        ).encode("utf-8")
                    )

    def onClose(self, wasClean, code, reason):
        print("Bağlantı kapandı")
        for username, user_data in list(users.items()):
            if user_data["connection"] == self:
                del users[username]

# Mesajları sırayla göndermek için bir fonksiyon
@inlineCallbacks
def process_message_queue():
    while True:
        if message_queue:
            message_data = message_queue.popleft()  # Kuyruktaki ilk mesajı al
            for user_data in users.values():
                user_data["connection"].sendMessage(json.dumps(message_data).encode("utf-8"))
            yield deferLater(reactor, 3, lambda: None)  # 3 saniye bekle
        else:
            yield deferLater(reactor, 1, lambda: None)  # Kuyruk boşsa bekle

# Bot mesajlarını her 60 saniyede bir gönderme
def send_bot_messages():
    for bot_name, bot_data in bots.items():
        message_data = {
            "type": "message",
            "username": bot_name,
            "icon": bot_data["icon"],
            "message": bot_data["message"],
        }
        for user_data in users.values():
            user_data["connection"].sendMessage(json.dumps(message_data).encode("utf-8"))

# Telegram'dan Mesajları Dinleme ve Kuyruğa Ekleme
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

async def listen_to_telegram():
    if not os.path.exists(f"{SESSION_NAME}.session"):
        print("Session dosyası bulunamadı. Yeni oturum oluşturuluyor...")
        await client.start()
        print("Session dosyası oluşturuldu ve giriş yapıldı!")
    else:
        print("Session dosyası mevcut. Giriş yapılıyor...")
        await client.connect()
        if not await client.is_user_authorized():
            print("Kullanıcı yetkilendirilmemiş. Tekrar giriş yapılıyor...")
            await client.start()

    print("Telegram'a başarıyla giriş yapıldı!")

    @client.on(events.NewMessage(chats=GROUP_ID))
    async def handler(event):
        sender = await event.get_sender()
        username = sender.first_name or sender.username or "Anonim"
        message = event.message.message

        # Mesaj filtreleme
        if (
            not message
            or event.message.photo
            or event.message.gif
            or "http" in message
            or re.search(r"@\w+", message)
            or (sender and sender.bot)
        ):
            return

        print(f"Telegram'dan gelen mesaj: {username}: {message}")

        # Mesajı kuyruğa ekle
        message_data = {
            "type": "message",
            "username": username,
            "icon": "telegram_icon.png",
            "message": message,
        }
        message_queue.append(message_data)

    await client.run_until_disconnected()

# WebSocket sunucusunu başlatma
class ChatServer:
    def __init__(self, port):
        factory = WebSocketServerFactory(f"ws://0.0.0.0:{port}")
        factory.protocol = ChatProtocol
        reactor.listenTCP(port, factory)
        print(f"Chat sunucusu {port} portunda çalışıyor!")

# Ana program
# Ana Program
if __name__ == "__main__":
    reactor.callInThread(process_message_queue)  # Mesaj kuyruğunu işleme başlat
    task.LoopingCall(send_bot_messages).start(60.0)  # Her 60 saniyede bir bot mesajlarını gönder

    # WebSocket Sunucusunu Başlat (Port 9000)
    ChatServer(9000)

    # HTTP API Sunucusunu Başlat (Port 8080)
    site = server.Site(MyAPI())
    reactor.listenTCP(8080, interface="0.0.0.0")
    print("HTTP server running on http://0.0.0.0:8080")

    # Telegram İstemcisini Başlat
    reactor.callInThread(client.loop.run_until_complete, listen_to_telegram())

    # Reactor'u Çalıştır
    reactor.run()