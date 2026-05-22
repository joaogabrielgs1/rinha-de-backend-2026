from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import asyncio
import asyncpg
import json
import os

class TransactionInput(BaseModel):
    amount: float
    installments: int
    requested_at: str

class CustomerInput(BaseModel):
    avg_amount: float
    tx_count_24h: int
    known_merchants: List[str]

class MerchantInput(BaseModel):
    id: str
    mcc: str
    avg_amount: float

class TerminalInput(BaseModel):
    is_online: bool
    card_present: bool
    km_from_home: float

class LastTransactionInput(BaseModel):
    timestamp: str
    km_from_current: float

class FraudScoreRequest(BaseModel):
    id: str
    transaction: TransactionInput
    customer: CustomerInput
    merchant: MerchantInput
    terminal: TerminalInput
    last_transaction: Optional[LastTransactionInput] = None 


app = FastAPI()
db_pool = None
mcc_risk_cache = {}
app_is_ready = False 

MAX_AMOUNT = 10000.0
MAX_INSTALLMENTS = 12.0
AMOUNT_VS_AVG_RATIO = 10.0
MAX_MINUTES = 1440.0
MAX_KM = 1000.0
MAX_TX_COUNT_24H = 20.0
MAX_MERCHANT_AVG_AMOUNT = 10000.0


def clamp(value: float) -> float:
    """Limita o valor estritamente ao intervalo [0.0, 1.0]"""
    return max(0.0, min(value, 1.0))


async def warmup_database():
    global app_is_ready, db_pool
    print(" Iniciando o aquecimento do banco em background...")
    

    for tentativa in range(1, 6):
        try:
            async with db_pool.acquire() as conn:
                dummy_vector = "[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]"
                await conn.execute(
                    "SELECT id FROM referencias ORDER BY vetor <-> $1::vector LIMIT 1",
                    dummy_vector
                )
            
            app_is_ready = True
            print(" Warm-up concluído! O índice HNSW está cravado na RAM.")
            break 
            
        except Exception as e:
            print(f" Tentativa {tentativa} de warm-up interrompida: {e}. Retentando em 5 segundos...")
            await asyncio.sleep(5)


@app.on_event("startup")
async def startup_event():
    global db_pool, mcc_risk_cache
    

    try:
        with open("mcc_risk.json", "r") as f:
            mcc_risk_cache = json.load(f)
    except FileNotFoundError:
        print("Aviso: mcc_risk.json não encontrado. Usando default 0.5 para tudo.")
        mcc_risk_cache = {}

    db_pool = await asyncpg.create_pool(
        user="admin",
        password="123",
        database="rinha",
        host="db", 
        port=5432,
        min_size=5, 
        max_size=10
    )

    
    asyncio.create_task(warmup_database())

@app.on_event("shutdown")
async def shutdown_event():
    global db_pool
    if db_pool:
        await db_pool.close()


@app.head("/ready")
@app.get("/ready")
async def ready():
    if app_is_ready:
        return {"status": "ready"}
    else:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Aguardando aquecimento do banco de dados..."
        )

@app.post("/fraud-score")
async def fraud_score(payload: FraudScoreRequest):

    t = payload.transaction
    c = payload.customer
    m = payload.merchant
    term = payload.terminal
    lt = payload.last_transaction

   
    req_at = datetime.fromisoformat(t.requested_at.replace("Z", "+00:00"))

    avg_amount_safe = c.avg_amount if c.avg_amount > 0 else 0.0001
    dim2_val = (t.amount / avg_amount_safe) / AMOUNT_VS_AVG_RATIO

    if lt:
        last_time = datetime.fromisoformat(lt.timestamp.replace("Z", "+00:00"))
        minutos = (req_at - last_time).total_seconds() / 60.0
        dim5 = clamp(minutos / MAX_MINUTES)
        dim6 = clamp(lt.km_from_current / MAX_KM)
    else:
        dim5 = -1.0
        dim6 = -1.0

    vetor_calculado = [
        clamp(t.amount / MAX_AMOUNT),                          # 0
        clamp(t.installments / MAX_INSTALLMENTS),              # 1
        clamp(dim2_val),                                       # 2
        req_at.hour / 23.0,                                    # 3
        req_at.weekday() / 6.0,                                # 4
        dim5,                                                  # 5
        dim6,                                                  # 6
        clamp(term.km_from_home / MAX_KM),                     # 7
        clamp(c.tx_count_24h / MAX_TX_COUNT_24H),              # 8
        1.0 if term.is_online else 0.0,                        # 9
        1.0 if term.card_present else 0.0,                     # 10
        1.0 if m.id not in c.known_merchants else 0.0,         # 11
        mcc_risk_cache.get(m.mcc, 0.5),                        # 12
        clamp(m.avg_amount / MAX_MERCHANT_AVG_AMOUNT)          # 13
    ]
    
    vetor_str = "[" + ",".join(map(str, vetor_calculado)) + "]"
    
    query = """
        SELECT label 
        FROM referencias 
        ORDER BY vetor <-> $1::vector 
        LIMIT 5
    """
    
    async with db_pool.acquire() as conn:
        vizinhos = await conn.fetch(query, vetor_str)
    
    fraudes = sum(1 for vizinho in vizinhos if vizinho['label'] == 'fraud')
    score = fraudes / 5.0
    approved = score < 0.6
    
    return {
        "approved": approved,
        "fraud_score": score
    }