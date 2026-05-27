# In-Memory Decision Tree Engine (Stateless ML)

Uma API de detecção de fraudes de alta performance e stateless para a [Rinha de Backend 2026](https://github.com/zanfranceschi/rinha-de-backend-2026), construída com Python, FastAPI e Scikit-Learn.

**Score**: Latência otimizada através da substituição da busca vetorial exata (K-NN em banco de dados) por inferência de modelo de Machine Learning em memória RAM (Árvore de Decisão), processando milhares de requisições por segundo sob rigorosas restrições de hardware.

---

## Arquitetura

```
db/dados.csv (Dataset oficial, 3M transações)
        │
        ▼
 Treinamento Offline (Jupyter/Colab) ───► modelo_fraude.pkl (~1 MB)
                                          (Decision Tree Classifier)
        │
        ▼
    Nginx (Round-robin, 0.10 CPU · 30 MB)
     ├── api1:8000  (FastAPI + joblib, 0.45 CPU · 160 MB)
     └── api2:8000  (FastAPI + joblib, 0.45 CPU · 160 MB)
```

**Recursos Totais:** 1.0 CPU · 350 MB

---

## Algoritmo de Classificação (Machine Learning)

### Visão Geral

O [sistema V1 (K-NN via pgvector)](https://github.com/joaogabrielgs1/rinha-de-backend-2026/blob/v1-arquitetura-vetorial/README.md) sofria de severos engasgos de CPU (Context Switching) e picos de memória (OOM) ao calcular distâncias euclidianas para 3 milhões de vetores em tempo de requisição.

A solução V2 resolve isso movendo a carga matemática pesada para o tempo de build/pré-deploy. O motor de busca foi substituído por uma Decision Tree Classifier (Árvore de Decisão) pré-treinada, que mapeia a lógica espacial em uma estrutura binária de IF/ELSE executada nativamente na RAM.

## O Vetor de 14 Dimensões

Cada requisição recebida pelo ecossistema é transformada em um vetor numérico de 14 posições. Todos os valores passam por um estágio de normalização (utilizando a função `clamp`) para os intervalos `[-1.0, 1.0]` ou `[0.0, 1.0]`.

|  Índice  | Dimensão           | Normalização / Lógica                                        |
| :------: | :----------------- | :----------------------------------------------------------- |
|  **0**   | `amount`           | `clamp(amount / MAX_AMOUNT)`                                 |
|  **1**   | `installments`     | `clamp(installments / MAX_INSTALLMENTS)`                     |
|  **2**   | `amount_vs_avg`    | `clamp((amount / avg_amount) / RATIO)`                       |
| **3-4**  | `datetime`         | `hora / 23.0` , `dia_semana / 6.0`                           |
| **5-6**  | `last_transaction` | Normalizado por tempo/distância. Valor `-1.0` se `null`.     |
|  **7**   | `km_from_home`     | `clamp(km_from_home / MAX_KM)`                               |
|  **8**   | `tx_count_24h`     | `clamp(count / MAX_COUNT)`                                   |
| **9-10** | `terminal_info`    | `1.0` (online/present) ou `0.0`                              |
|  **11**  | `unknown_merchant` | `1.0` se não estiver na lista `known_merchants`, senão `0.0` |
|  **12**  | `mcc_risk`         | Lookup de risco do MCC (`0.15` a `0.85`)                     |
|  **13**  | `merchant_avg`     | `clamp(merchant.avg_amount / MAX_MERCHANT_AVG)`              |

---

## Fluxo de Validação (Query-time)

O ciclo de vida de uma validação ocorre de forma puramente síncrona e otimizada para tempo real:

1. **Recebimento:** A API intercepta o payload JSON da transação (estrutura padrão da Rinha).
2. **Tratamento:** Extração e sanitização das variáveis, aplicando camadas protetivas contra valores nulos ou ausentes.
3. **Vetorização:** Montagem dinâmica do vetor matricial `X` de 14 dimensões.
4. **Inferência:** Execução do modelo preditivo com complexidade algorítmica de $O(\\log N)$ via `modelo_ia.predict([X])`.
5. **Tradução:**
   - **`0`** ──► Transação Legítima (`approved: true`, `fraud_score: 0.0`)
   - **`1`** ──► Fraude Identificada (`approved: false`, `fraud_score: 1.0`)
6. **Resposta:** Retorno síncrono devolvido ao cliente na escala de microssegundos.

---

## Pipeline de Dados e Modelo

### Pré-processamento e Treinamento (Offline)

Todo o ciclo de treinamento ocorre de forma desacoplada e fora do cluster de execução da Rinha para preservar os recursos computacionais limitados dos containers Docker:

- **Ingestão:** Leitura de um dataset massivo contendo **3 milhões de registros** através da biblioteca Pandas.
- **Modelagem:** Utilização do algoritmo `sklearn.tree.DecisionTreeClassifier(max_depth=10, random_state=42)`. A limitação estrita de profundidade atua como um regularizador contra _overfitting_ e assegura um binário extremamente leve para o runtime.
- **Serialização:** Exportação do artefato compilado utilizando `joblib`.

### Tempo de Execução (In-Memory FastAPI)

- **Inicialização Síncrona:** Durante o evento de startup do Uvicorn (`@app.on_event("startup")`), o arquivo `modelo_fraude.pkl` é lido do disco e alocado diretamente na memória RAM.
- **Zero I/O:** Assim que o servidor atinge o estado _Ready_, o sistema elimina qualquer dependência de consultas em disco ou chamadas de rede para validação. Toda a inferência é processada nos caches L1/L2 da CPU.

---

## Características de Performance & Trade-offs (Resultados Oficiais)

A evolução da arquitetura de busca exata tradicional (V1) para a inferência baseada em Inteligência Artificial em memória (V2) revelou dois grandes cenários de _trade-offs_ clássicos da engenharia de software na prática:

**1. Matemática Exata vs. Disponibilidade Absoluta**
Abrimos mão de **~2.3% de precisão matemática nominal** para alcançar um ganho brutal de estabilidade. Ao remover o banco de dados do fluxo crítico de validação, eliminamos o gargalo de I/O de disco e rede, tornando a API 100% _stateless_ e imune à exaustão de _Connection Pools_.

**2. Throughput vs. Latência (A Teoria das Filas)**
Durante os testes de stress, aplicamos os conceitos da Lei de Little (_Little's Law_). Descobrimos que forçar 150 conexões simultâneas gerava o limite de vazão da CPU (1.130 RPS), mas criava um estrangulamento de espera na memória RAM, elevando o tempo de resposta das últimas requisições da fila.

Ao ajustarmos o proxy para o **Sweet Spot** do hardware (50 requisições simultâneas), sacrificamos levemente o _throughput_ máximo, mas esvaziamos a fila de contenção. O resultado foi uma resposta virtualmente instantânea para o usuário final, maximizando a pontuação logarítmica da competição.

### Métricas Finais da Avaliação

Aplicando a métrica oficial de pontuação da Rinha de Backend 2026 (que pune latência e gargalos de forma logarítmica) sob as severas restrições de `0.90 CPU` e `350MB RAM` combinadas:

- **Score Oficial da Rinha:** **+1660.98 pontos**
- **Latência p99:** **60.10ms** (Garantindo que a interface do aplicativo móvel responda em tempo real sem congelamentos).
- **Vazão Bruta Sustentada:** **~976 RPS** (Requisições Por Segundo).
- **Acurácia do Modelo:** Taxa de falhas na matriz de confusão restrita a apenas **2.32%** (52.847 acertos em 54.100 cenários rotulados via força bruta).
- **Muralha de Infraestrutura:** **0 Erros HTTP**. O Nginx e o FastAPI absorveram toda a carga de stress sem registrar uma única falha de _Timeout_ ou _Bad Gateway_ (0% de erros 502/504).

---

## O Impacto do Python: Ecossistema vs. Limites de Hardware

A escolha do Python como linguagem principal para o backend ditou os limites absolutos desta arquitetura, trazendo facilidades para o desenvolvimento da Inteligência Artificial, mas cobrando um preço na escalabilidade extrema.

### Onde o Python Brilhou (Impacto Positivo)

- **Ecossistema Nativo e Unificado:** O Python nos permitiu treinar a árvore de decisão offline (`scikit-learn`), exportar o modelo e inferir a decisão na API (`joblib`) usando as exatas mesmas estruturas de dados de forma nativa. Não foi necessário reescrever o algoritmo de Árvore de Decisão do zero em outra linguagem ou criar pontes complexas de integração.

### Onde o Python Gargalou (Impacto Negativo)

- **O GIL (Global Interpreter Lock) e CPU-Bound:** O cálculo da IA (`modelo_ia.predict`) é uma operação estritamente matemática (_CPU-bound_). Mesmo utilizando `asyncio` no FastAPI, o GIL do Python impede o paralelismo real de threads. Quando a CPU está ocupada calculando a fraude de uma requisição, o _Event Loop_ bloqueia as outras, criando um teto de ~1.000 RPS.
- **Tempo de Build e Tamanho da Imagem:** Bibliotecas de Data Science carregam muitas dependências compiladas em C/C++ por baixo dos panos. Isso inflou o tempo de _build_ do Docker (passando de 50 segundos) e gerou uma imagem final muito mais pesada (centenas de MBs) do que um binário estático de linguagens compiladas.
- **O "Teto de Vidro" do Hardware:** Sob a restrição rigorosa de `0.45 vCPU` e `160MB` de RAM, linguagens nativamente multithread e compiladas (AOT) conseguiriam processar as mesmas lógicas de `IF/ELSE` gerando de 5.000 a 10.000 RPS. Com o Python, extraímos 100% do que o interpretador consegue entregar antes de saturar o _Context Switching_.

---
