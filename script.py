import os
import sys
import json
import time
from datetime import datetime, timezone

import requests

# ----------------- CONFIGURATION -----------------
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK")
DRY_RUN = os.environ.get("DRY_RUN") == "1"  # n'envoie rien, affiche seulement

API_URL = "https://metadata.luckperms.net/data/all"
CACHE_FILE = "last_build.json"
MAX_NOTIFS = 5  # sécurité anti-spam si le cache est perdu

HEADERS = {"User-Agent": "LuckPerms-Check-Bot/1.0 (+https://github.com/TON_PSEUDO/LuckPerms-check)"}

# Plateformes affichées dans l'embed (clé API -> nom affiché)
PLATFORMS = {
    "bukkit": "Bukkit/Paper/Spigot",
    "velocity": "Velocity",
    "bungee": "BungeeCord",
    "fabric": "Fabric",
    "neoforge": "NeoForge",
    "forge": "Forge",
    "sponge": "Sponge",
}
# -------------------------------------------------


def version_key(v):
    """'5.5.87' -> (5, 5, 87) pour comparer correctement (5.5.100 > 5.5.99)."""
    try:
        return tuple(int(p) for p in v.split("."))
    except (ValueError, AttributeError):
        return (0,)


def load_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("last_version", "0")
    except (FileNotFoundError, json.JSONDecodeError):
        return "0"


def save_cache(version):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_version": version}, f, indent=2)
        f.write("\n")


def fetch_metadata(retries=3):
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(API_URL, headers=HEADERS, timeout=15)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            print(f"Tentative {attempt}/{retries} échouée : {e}")
            time.sleep(2 * attempt)
    return None


def build_embed(data, entry):
    version = entry["version"]
    is_latest = version == data.get("version")
    ts = entry.get("timestamp")
    commit = entry.get("commit", "")

    fields = [
        {"name": "🆔 Version", "value": f"`{version}`", "inline": True},
        {"name": "📝 Changement", "value": entry.get("title", "N/A")[:1000], "inline": False},
    ]
    # Les liens de téléchargement ne sont valables que pour la dernière version
    if is_latest:
        links = [
            f"[{name}]({data['downloads'][key]})"
            for key, name in PLATFORMS.items()
            if key in data.get("downloads", {})
        ]
        if links:
            fields.append({"name": "⬇️ Téléchargements", "value": " • ".join(links), "inline": False})

    embed = {
        "title": "🔐 LUCKPERMS - Nouvelle version détectée",
        "url": "https://luckperms.net/download",
        "color": 3447003,
        "fields": fields,
        "footer": {"text": "Automatic via GitHub"},
    }
    if commit:
        embed["fields"].insert(2, {
            "name": "🔗 Commit",
            "value": f"[`{commit[:7]}`](https://github.com/LuckPerms/LuckPerms/commit/{commit})",
            "inline": True,
        })
    if ts:
        embed["timestamp"] = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
    return embed


def send_discord(embed):
    """Retourne True seulement si Discord a bien accepté le message."""
    if DRY_RUN:
        print(json.dumps(embed, indent=2, ensure_ascii=False))
        return True
    for _ in range(3):
        try:
            res = requests.post(WEBHOOK_URL, json={"embeds": [embed]}, timeout=15)
        except requests.RequestException as e:
            print(f"Erreur réseau Discord : {e}")
            time.sleep(2)
            continue
        if res.status_code == 429:  # rate limit
            time.sleep(float(res.json().get("retry_after", 2)))
            continue
        if res.status_code < 400:
            return True
        print(f"Échec Discord : {res.status_code} - {res.text}")
        return False
    return False


def main():
    if not WEBHOOK_URL and not DRY_RUN:
        print("Erreur : DISCORD_WEBHOOK manquant.")
        sys.exit(1)

    data = fetch_metadata()
    if not data or "version" not in data:
        print("API LuckPerms indisponible, on réessaiera au prochain passage.")
        sys.exit(1)

    last = load_cache()
    print(f"Dernière version API : {data['version']} | Cache : {last}")

    # Toutes les versions plus récentes que le cache, de la plus ancienne à la plus récente
    new = [e for e in data.get("changeLog", []) if version_key(e["version"]) > version_key(last)]
    new.sort(key=lambda e: version_key(e["version"]))

    if not new:
        print("Pas de nouvelle version.")
        return

    # Premier lancement (cache vide) : on ne notifie que la dernière version
    if last == "0":
        new = new[-1:]
    new = new[-MAX_NOTIFS:]

    for entry in new:
        if not send_discord(build_embed(data, entry)):
            print(f"Envoi raté pour {entry['version']}, cache non mis à jour.")
            sys.exit(1)
        if not DRY_RUN:
            save_cache(entry["version"])  # sauvegarde au fur et à mesure
        print(f"Notification envoyée : {entry['version']}")


if __name__ == "__main__":
    main()
