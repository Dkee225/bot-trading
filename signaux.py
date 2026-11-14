"""
Générateur de SIGNAUX quotidiens (aucun ordre n'est passé).
Tu exécutes toi-même les signaux sur MetaTrader (démo d'abord, réel ensuite).

Utilisation :
    python signaux.py --capital 50 --risk 0.02               # affiche les signaux
    python signaux.py --capital 50 --risk 0.02 --telegram    # + envoi Telegram
    python signaux.py --instruments EURUSD,XAUUSD --capital 100 --risk 0.02

Lancer une fois par jour, APRÈS la clôture quotidienne (vers 22h00 UTC en semaine).
Le signal est calculé sur la bougie journalière terminée : tu entres à l'ouverture suivante.

IMPORTANT : vérifie dans ta plateforme MetaTrader (Spécification du contrat) la taille du
contrat et le lot minimum de ton courtier, et ajuste INSTRUMENTS / --lot-min si besoin.
Stratégie long uniquement (achat). Aucun gain n'est garanti.
"""
import argparse
import math

import notifier
from bot_squelette import ajouter_indicateurs, charger_donnees, generer_signaux

# yf = symbole Yahoo Finance | contrat = unités par lot standard | stop = stop-loss par défaut
INSTRUMENTS = {
    "EURUSD": {"yf": "EURUSD=X", "contrat": 100_000, "stop": 0.010, "dec": 5},
    "GBPUSD": {"yf": "GBPUSD=X", "contrat": 100_000, "stop": 0.010, "dec": 5},
    "XAUUSD": {"yf": "GC=F", "contrat": 100, "stop": 0.025, "dec": 2},
    "BTCUSD": {"yf": "BTC-USD", "contrat": 1, "stop": 0.050, "dec": 2},
}


def calcul_lot(capital, risque, prix, stop_pct, contrat, lot_min, pas):
    """Lot tel que perte = risque x capital si le stop est touché.
    Si même le lot minimum dépasse ce risque, on le signale (force = True)."""
    distance = prix * stop_pct
    risque_voulu = capital * risque
    lots = math.floor(risque_voulu / (distance * contrat) / pas + 1e-9) * pas
    force = lots < lot_min
    if force:
        lots = lot_min
    risque_reel = lots * contrat * distance
    return distance, round(lots, 3), risque_reel, force


def analyser(nom, cfg, a):
    data = ajouter_indicateurs(charger_donnees(cfg["yf"], debut="2018-01-01"))
    sig = generer_signaux(data, a.rsi_achat, a.rsi_vente)
    pos = sig["position"]
    aujourd, hier = int(pos.iloc[-1]), int(pos.iloc[-2])
    prix = float(sig["Close"].iloc[-1])
    date = sig.index[-1].date()
    d = cfg["dec"]
    stop_pct = a.stop if a.stop else cfg["stop"]

    if aujourd == 1 and hier == 0:
        statut = "ACHAT"
    elif aujourd == 0 and hier == 1:
        statut = "SORTIE"
    elif aujourd == 1:
        statut = "DÉTENIR"
    else:
        statut = "CASH"

    ligne = f"{nom} [{date}] clôture {prix:.{d}f} -> {statut}"
    if statut == "ACHAT":
        dist, lots, risque_reel, force = calcul_lot(
            a.capital, a.risk, prix, stop_pct, cfg["contrat"], a.lot_min, a.lot_pas)
        stop_prix = prix - dist
        pct = risque_reel / a.capital
        ligne = (f"🟢 ACHAT {nom} | réf. {prix:.{d}f} | stop {stop_prix:.{d}f} (-{stop_pct:.1%}) | "
                 f"lot {lots} | perte max si stop ≈ {risque_reel:.2f} $ ({pct:.0%} du capital)")
        if force:
            ligne += (f"\n   ⚠️ Le lot minimum ({a.lot_min}) dépasse déjà ton risque voulu ({a.risk:.0%}). "
                      "Compte cent / lot plus petit, capital plus grand, ou ne prends pas ce trade.")
    elif statut == "SORTIE":
        ligne = f"🔴 SORTIE {nom} | clôture {prix:.{d}f} | ferme ta position si tu l'avais prise"
    elif statut == "DÉTENIR":
        entrees = pos.diff().fillna(0)
        entrees = entrees[entrees == 1]
        if len(entrees):
            dte = entrees.index[-1]
            p_ent = float(sig.loc[dte, "Close"])
            stop_niv = p_ent * (1 - stop_pct)
            if prix <= stop_niv:
                statut = "STOP"
                ligne = (f"🟠 STOP FRANCHI {nom} | entrée du {dte.date()} à {p_ent:.{d}f}, stop {stop_niv:.{d}f}, "
                         f"clôture {prix:.{d}f} | sors si tu es encore dedans, pas de nouvelle entrée "
                         "avant un nouveau signal")
            else:
                ligne = (f"🟡 DÉTENIR {nom} | signal d'entrée du {dte.date()} à {p_ent:.{d}f} | "
                         f"stop suggéré {stop_niv:.{d}f} | clôture {prix:.{d}f}")
    return statut, ligne


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--instruments", default=",".join(INSTRUMENTS), help="ex. EURUSD,XAUUSD")
    p.add_argument("--capital", type=float, default=50.0, help="capital du compte en $")
    p.add_argument("--risk", type=float, default=0.02, help="part du capital risquée par trade (0.02 = 2 %)")
    p.add_argument("--stop", type=float, default=0.0, help="stop-loss en %% du prix (sinon valeur par instrument)")
    p.add_argument("--rsi-achat", type=int, default=40)
    p.add_argument("--rsi-vente", type=int, default=60)
    p.add_argument("--lot-min", type=float, default=0.01)
    p.add_argument("--lot-pas", type=float, default=0.01)
    p.add_argument("--telegram", action="store_true", help="envoie le résultat sur Telegram")
    a = p.parse_args()

    lignes, actions = [], False
    for nom in [x.strip().upper() for x in a.instruments.split(",") if x.strip()]:
        if nom not in INSTRUMENTS:
            lignes.append(f"{nom} : instrument inconnu (voir INSTRUMENTS dans signaux.py)")
            continue
        try:
            statut, ligne = analyser(nom, INSTRUMENTS[nom], a)
            actions |= statut in ("ACHAT", "SORTIE", "STOP")
        except Exception as e:  # un instrument en erreur ne bloque pas les autres
            ligne = f"{nom} : erreur de données ({type(e).__name__})"
        lignes.append(ligne)

    entete = f"📡 Signaux du jour | capital {a.capital:g} $ | risque {a.risk:.0%}"
    pied = "Exécution manuelle à l'ouverture suivante. Vérifie le prix et ton lot avant d'agir."
    texte = "\n".join([entete, *lignes, pied] if actions else [entete, *lignes])
    print(texte)
    if a.telegram:
        notifier.envoyer(texte)


if __name__ == "__main__":
    main()
