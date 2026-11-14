"""
Alertes Telegram pour le bot (aucune dépendance externe).

Configuration (une seule fois) :
 1. Sur Telegram, ouvre @BotFather -> /newbot -> récupère le TOKEN.
 2. Envoie un message quelconque à ton nouveau bot.
 3. Ouvre dans un navigateur : https://api.telegram.org/bot<TOKEN>/getUpdates
    puis repère "chat":{"id": 123456789 ...} -> c'est ton CHAT_ID.
 4. Variables d'environnement (comme pour les clés Alpaca) :
      TELEGRAM_BOT_TOKEN  et  TELEGRAM_CHAT_ID
 5. Test : python notifier.py
Ne partage jamais ton token (il donne le contrôle du bot).
"""
import os
import urllib.parse
import urllib.request


def _afficher(texte):
    """print() qui ne plante jamais, même si la console ne gère pas les emojis (tâche planifiée)."""
    try:
        print(texte)
    except UnicodeEncodeError:
        print(texte.encode("ascii", "replace").decode())


def envoyer(message):
    """Envoie un message. Ne lève jamais d'exception : une alerte ratée ne doit pas casser le bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        _afficher(f"[Alerte non envoyée : Telegram non configuré] {message}")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message[:3500]}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10) as r:
            return r.status == 200
    except Exception as e:  # réseau coupé, token invalide...
        _afficher(f"[Alerte Telegram échouée : {type(e).__name__}]")
        return False


if __name__ == "__main__":
    ok = envoyer("✅ Test : les alertes du bot de trading fonctionnent.")
    print("Message envoyé." if ok else "Échec : vérifie TOKEN et CHAT_ID.")
