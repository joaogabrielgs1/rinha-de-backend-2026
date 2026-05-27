from fastapi import FastAPI
import joblib
from datetime import datetime

MAX_AMOUNT = 50000.0
MAX_INSTALLMENTS = 12.0
AMOUNT_VS_AVG_RATIO = 10.0
MAX_MINUTES = 1440.0
MAX_KM = 5000.0
MAX_TX_COUNT_24H = 50.0
MAX_MERCHANT_AVG_AMOUNT = 50000.0

mcc_risk_dict = {} 

def clamp(valor):
    """Limita o valor entre -1 e 1."""
    return max(-1.0, min(1.0, float(valor)))

app = FastAPI()
modelo_ia = None

@app.get("/ready")
async def ready_check():
    return {"status": "ready"}

@app.on_event("startup")
async def startup_event():
    global modelo_ia
    modelo_ia = joblib.load("modelo_fraude.pkl")

@app.post("/fraud-score")
async def process_transaction(payload: dict): 
    t = payload.get("transaction", {})
    c = payload.get("customer", {})
    term = payload.get("terminal", {})
    m = payload.get("merchant", {})
    last_tx = payload.get("last_transaction")

    try:
        dt_str = t.get("requested_at", "2026-01-01T00:00:00Z").replace("Z", "+00:00")
        dt = datetime.fromisoformat(dt_str)
        hour_of_day = dt.hour / 23.0
        day_of_week = dt.weekday() / 6.0
    except:
        hour_of_day, day_of_week = 0.0, 0.0

    c_avg = c.get("avg_amount", 1.0)
    if c_avg <= 0: c_avg = 1.0
    amount_vs_avg = (t.get("amount", 0) / c_avg) / AMOUNT_VS_AVG_RATIO

  
    if last_tx:
        minutos = last_tx.get("minutes_since_last", 0) 
        minutes_since_last_tx = clamp(minutos / MAX_MINUTES)
        km_from_last_tx = clamp(last_tx.get("km_from_current", 0) / MAX_KM)
    else:
        minutes_since_last_tx = -1.0
        km_from_last_tx = -1.0

    known_merchants = c.get("known_merchants", [])
    unknown_merchant = 1.0 if m.get("id") not in known_merchants else 0.0
    risk_mcc = mcc_risk_dict.get(m.get("mcc", ""), 0.5)

    vetor_calculado = [
        clamp(t.get("amount", 0) / MAX_AMOUNT),                     # 0
        clamp(t.get("installments", 1) / MAX_INSTALLMENTS),         # 1
        clamp(amount_vs_avg),                                       # 2
        clamp(hour_of_day),                                         # 3 
        clamp(day_of_week),                                         # 4
        minutes_since_last_tx,                                      # 5
        km_from_last_tx,                                            # 6
        clamp(term.get("km_from_home", 0) / MAX_KM),                # 7
        clamp(c.get("tx_count_24h", 0) / MAX_TX_COUNT_24H),         # 8
        1.0 if term.get("is_online") else 0.0,                      # 9
        1.0 if term.get("card_present") else 0.0,                   # 10
        unknown_merchant,                                           # 11
        risk_mcc,                                                   # 12
        clamp(m.get("avg_amount", 0) / MAX_MERCHANT_AVG_AMOUNT)     # 13
    ]

    resultado_ia = modelo_ia.predict([vetor_calculado])[0]

    aprovado = bool(resultado_ia == 0)
    
    return {
        "approved": aprovado,
        "fraud_score": 1.0 if not aprovado else 0.0
    }