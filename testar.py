import json
import asyncio
import aiohttp
import time

# --- CONFIGURAÇÕES ---
ARQUIVO_JSON = "/workspaces/rinha-de-backend-2026/db/test-data.json"
URL_API = "http://127.0.0.1:9999/fraud-score"
CONCORRENCIA = 40  

acertos = 0
erros = 0
falhas_rede = 0
processados = 0

async def enviar_requisicao(session, sem, entry):
    global acertos, erros, falhas_rede
    
    payload = entry["request"]
    gabarito_aprovado = entry["expected_approved"]
    

    async with sem:
        try:
            async with session.post(URL_API, json=payload, timeout=60) as response:
                if response.status == 200:
                    resultado = await response.json()
                    if resultado.get("approved") == gabarito_aprovado:
                        acertos += 1
                    else:
                        erros += 1
                else:
                    if falhas_rede == 0:
                        texto = await response.text()
                        print(f"\n ERRO HTTP {response.status}: {texto[:150]} ")
                    falhas_rede += 1
                    
        except Exception as e:
            if falhas_rede == 0:
                print(f"\n ERRO DE REDE: {repr(e)}")
            falhas_rede += 1
            
        finally:
            global processados
            processados += 1
            if processados % 50 == 0:
                print(f" Progresso: {processados} / 54100 concluídas..., erros:{erros}, acertos{acertos}, falhas: {falhas_rede}")

async def main():
    print(f" Lendo o arquivo {ARQUIVO_JSON}...")
    with open(ARQUIVO_JSON, "r") as f:
        dados = json.load(f)
    
    entradas = dados.get("entries", [])
    total_requisicoes = len(entradas)
    print(f" Iniciando teste com {total_requisicoes} requisições...")
    print(f"  Concorrência: {CONCORRENCIA} requisições simultâneas.")
    
    sem = asyncio.Semaphore(CONCORRENCIA)
    
    # Inicia o cronômetro
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
    print(f"  Tempo total: {tempo_total:.2f} segundos")
    print(f" Velocidade:  {rps:.2f} requisições por segundo (RPS)")
    print("-" * 40)
    print(f" Acertos (Matemática correta): {acertos}")
    print(f" Erros (Matemática errada):  {erros}")
    print(f"  Falhas (Timeout/502/etc):   {falhas_rede}")
    print("="*40)

if __name__ == "__main__":
    asyncio.run(main())