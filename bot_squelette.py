"""
Squelette de bot de trading : données -> indicateurs -> signaux -> backtest.
Installation : pip install yfinance pandas numpy
AUCUN ordre réel n'est passé ici. Outil d'apprentissage uniquement.
"""
import numpy as np
import pandas as pd
import yfinance as yf

# ---------- 1. Données ----------
def charger_donnees(ticker="AAPL", debut="2015-01-01", fin=None):
    df = yf.download(ticker, start=debut, end=fin, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):  # yfinance récent
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()

# ---------- 2. Indicateurs ----------
def rsi(close, n=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    perte = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / perte
    return 100 - 100 / (1 + rs)

def ajouter_indicateurs(df):
    df = df.copy()
    df["rsi"] = rsi(df["Close"])
    df["sma50"] = df["Close"].rolling(50).mean()
    df["sma200"] = df["Close"].rolling(200).mean()
    return df

# ---------- 3. Stratégie ----------
def generer_signaux(df, rsi_achat=30, rsi_vente=60):
    """Position = 1 (investi) ou 0 (cash). Achat: RSI bas + tendance haussière."""
    df = df.copy()
    achat = (df["rsi"] < rsi_achat) & (df["sma50"] > df["sma200"])
    vente = (df["rsi"] > rsi_vente) | (df["sma50"] < df["sma200"])
    pos = pd.Series(np.nan, index=df.index)
    pos[achat] = 1
    pos[vente] = 0
    df["position"] = pos.ffill().fillna(0)
    return df

# ---------- 4. Backtest ----------
def backtest(df, frais=0.001, slippage=0.0005, stop_loss=None, trailing=False):
    """Backtest bougie par bougie avec stop-loss optionnel.

    - shift(1) : le signal de la bougie t est exécuté sur la bougie t+1 (pas de look-ahead).
    - stop_loss : ex. 0.05 = sortie si le prix touche -5 % sous le niveau d'entrée.
    - trailing  : si True, le stop suit le plus haut (stop suiveur) au lieu d'être fixe.
    - Le stop est testé sur le Low de la journée ; si le prix ouvre sous le stop (gap),
      la sortie se fait à l'ouverture (pire cas réaliste).
    - Après un stop, pas de ré-entrée tant que le signal n'est pas repassé à 0.
    Ajoute : position_eff (position réellement détenue), stop_hit, rend_strat, equity, buy_hold."""
    df = df.copy()
    signal = df["position"].shift(1).fillna(0).to_numpy()
    close = df["Close"].to_numpy(float)
    open_ = df["Open"].to_numpy(float)
    low = df["Low"].to_numpy(float)
    n = len(df)
    cout = frais + slippage

    rend = np.zeros(n)
    pos_eff = np.zeros(n)
    stop_hit = np.zeros(n, dtype=bool)
    prev, bloque, niveau = 0, False, 0.0

    for i in range(1, n):
        if signal[i] == 0:
            bloque = False
        want = 1 if (signal[i] == 1 and not bloque) else 0
        r = 0.0
        if want == 1:
            if prev == 0:  # entrée au close de la veille
                r -= cout
                niveau = close[i - 1] * (1 - stop_loss) if stop_loss else 0.0
            if stop_loss and low[i] <= niveau:  # stop touché
                prix_sortie = min(open_[i], niveau)
                r += prix_sortie / close[i - 1] - 1 - cout
                stop_hit[i], bloque, want = True, True, 0
            else:
                r += close[i] / close[i - 1] - 1
                if stop_loss and trailing:
                    niveau = max(niveau, close[i] * (1 - stop_loss))
        elif prev == 1:  # sortie sur signal
            r -= cout
        rend[i], pos_eff[i], prev = r, want, want
        if stop_hit[i]:
            pos_eff[i] = 1  # détenu pendant la journée du stop

    df["position_eff"] = pos_eff
    df["stop_hit"] = stop_hit
    df["rend_strat"] = rend
    df["equity"] = (1 + df["rend_strat"]).cumprod()
    df["buy_hold"] = (1 + df["Close"].pct_change().fillna(0)).cumprod()
    return df

def metriques(df):
    r = df["rend_strat"]
    col_pos = "position_eff" if "position_eff" in df else "position"
    annees = len(r) / 252
    cagr = df["equity"].iloc[-1] ** (1 / annees) - 1
    sharpe = np.sqrt(252) * r.mean() / r.std() if r.std() > 0 else 0
    max_dd = (df["equity"] / df["equity"].cummax() - 1).min()
    r_bh = df["buy_hold"].pct_change().dropna()
    cagr_bh = df["buy_hold"].iloc[-1] ** (1 / annees) - 1
    sharpe_bh = np.sqrt(252) * r_bh.mean() / r_bh.std() if r_bh.std() > 0 else 0
    dd_bh = (df["buy_hold"] / df["buy_hold"].cummax() - 1).min()
    return {
        "CAGR": f"{cagr:.1%}",
        "Sharpe": round(sharpe, 2),
        "Max drawdown": f"{max_dd:.1%}",
        "Nb trades": int((df[col_pos].diff().abs() > 0).sum() // 2),
        "Stops déclenchés": int(df["stop_hit"].sum()) if "stop_hit" in df else 0,
        "Buy&Hold final": f"{df['buy_hold'].iloc[-1]:.2f}x",
        "B&H CAGR": f"{cagr_bh:.1%}",
        "B&H Sharpe": round(sharpe_bh, 2),
        "B&H Max drawdown": f"{dd_bh:.1%}",
        "Stratégie finale": f"{df['equity'].iloc[-1]:.2f}x",
    }

# ---------- 5. Validation hors échantillon ----------
if __name__ == "__main__":
    data = ajouter_indicateurs(charger_donnees("AAPL"))
    coupure = int(len(data) * 0.7)  # 70% train / 30% test
    for nom, morceau in [("TRAIN", data.iloc[:coupure]), ("TEST (hors échantillon)", data.iloc[coupure:])]:
        res = backtest(generer_signaux(morceau))
        print(f"\n=== {nom} ===")
        for k, v in metriques(res).items():
            print(f"{k:18}: {v}")
    # Règle d'or : si le TEST est bien pire que le TRAIN, la stratégie est sur-ajustée.
