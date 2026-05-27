import json
import asyncio
import aiohttp
import time
import math

ARQUIVO_JSON = "/workspaces/rinha-de-backend-2026/db/test-data.json"
URL_API = "http://127.0.0.1:9999/fraud-score"
CONCORRENCIA = 25  

tp = 0  
tn = 0 
fp = 0
fn = 0 
http_errors = 0
processados = 0
tempos_resposta = []

def calcular_score_rinha(total_requisicoes, tp, tn, fp, fn, http_errors, p99_ms):
    """Calcula a pontuação baseada na matemática oficial da Rinha."""
    falhas = fp + fn + http_errors
    tx_falhas = falhas / total_requisicoes
    
    weighted_errors_E = (1 * fp) + (3 * fn) + (5 * http_errors)
    error_rate_epsilon = weighted_errors_E / total_requisicoes
    
    cut_triggered_p99 = p99_ms > 2000.0
    if cut_triggered_p99:
        p99_score = -3000.0
    else:
        p99_score = 1000.0 * math.log10(1000.0 / max(p99_ms, 1.0))
        p99_score = min(p99_score, 3000.0)

    cut_triggered_det = tx_falhas > 0.15
    rate_component = None
    absolute_penalty = None
    
    if cut_triggered_det:
        detection_score = -3000.0
    else:
        rate_component = 1000.0 * math.log10(1 / max(error_rate_epsilon, 0.001))
        absolute_penalty = -300.0 * math.log10(1 + weighted_errors_E)
        detection_score = rate_component + absolute_penalty
        detection_score = min(detection_score, 3000.0)

    # 3. FINAL SCORE
    return {
        "p99_ms": round(p99_ms, 2),
        "scoring": {
            "breakdown": {
                "true_positive_detections": tp,
                "true_negative_detections": tn,
                "false_positive_detections": fp,
                "false_negative_detections": fn,
                "http_errors": http_errors
            },
            "failure_rate": f"{(tx_falhas * 100):.2f}%",
            "weighted_errors_E": weighted_errors_E,
            "error_rate_epsilon": round(error_rate_epsilon, 4),
            "p99_score": {"value": round(p99_score, 2), "cut_triggered": cut_triggered_p99},
            "detection_score": {
                "value": round(detection_score, 2),
                "rate_component": round(rate_component, 2) if rate_component else None,
                "absolute_penalty": round(absolute_penalty, 2) if absolute_penalty else None,
                "cut_triggered": cut_triggered_det
            },
            "final_score": round(p99_score + detection_score, 2)
        }
    }

async def enviar_requisicao(session, sem, entry):
    global tp, tn, fp, fn, http_errors, processados
    
    payload = entry["request"]
    gabarito_aprovado = entry["expected_approved"]

    async with sem:
        inicio = time.perf_counter()
        try:
            async with session.post(URL_API, json=payload, timeout=60) as response:
                if response.status == 200:
                    resultado = await response.json()
                    aprovou = resultado.get("approved")
                    
                    if aprovou == gabarito_aprovado:
                        if gabarito_aprovado:
                            tn += 1 
                        else:
                            tp += 1
                    else:
                        if gabarito_aprovado:
                            fp += 1 
                        else:
                            fn += 1
                else:
                    if http_errors == 0:
                        texto = await response.text()
                        print(f"\n ERRO HTTP {response.status}: {texto[:150]} ")
                    http_errors += 1
                    
        except Exception as e:
            if http_errors == 0:
                print(f"\n ERRO DE REDE: {repr(e)}")
            http_errors += 1
            
        finally:
            processados += 1
            if processados % 500 == 0:
                print(f" Progresso: {processados} / 54100 concluídas...")
        
        fim = time.perf_counter()
        tempo_ms = (fim - inicio) * 1000
        tempos_resposta.append(tempo_ms)

async def main():
    print(f" Lendo o arquivo {ARQUIVO_JSON}...")
    with open(ARQUIVO_JSON, "r") as f:
        dados = json.load(f)
    
    entradas = dados.get("entries", [])
    total_requisicoes = len(entradas)
    print(f" Iniciando teste com {total_requisicoes} requisições...")
    print(f"  Concorrência: {CONCORRENCIA} simultâneas.")
    
    sem = asyncio.Semaphore(CONCORRENCIA)
    start_time = time.time()
    
    async with aiohttp.ClientSession() as session:
        tarefas = [enviar_requisicao(session, sem, entry) for entry in entradas]
        await asyncio.gather(*tarefas)
        
    end_time = time.time()
    tempo_total = end_time - start_time
    rps = total_requisicoes / tempo_total if tempo_total > 0 else 0
    
    print("\n" + "="*40)
    print(" RELATÓRIO DO TESTE DE CARGA")
    print("="*40)
    print(f" Tempo total: {tempo_total:.2f} segundos")
    print(f" Velocidade:  {rps:.2f} RPS")
    print("="*40)
    
    if tempos_resposta:
        tempos_resposta.sort()
        indice_p99 = int(len(tempos_resposta) * 0.99)
        p99_ms = tempos_resposta[indice_p99]
    else:
        p99_ms = 2000.0

    print(f" Latência p99: {p99_ms:.2f}ms\n")

    resultado_oficial = calcular_score_rinha(
        total_requisicoes=len(tempos_resposta), 
        tp=tp, 
        tn=tn, 
        fp=fp, 
        fn=fn, 
        http_errors=http_errors, 
        p99_ms=p99_ms
    )

    print(json.dumps(resultado_oficial, indent=2))

if __name__ == "__main__":
    asyncio.run(main())