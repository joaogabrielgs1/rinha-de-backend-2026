# Rinha de Backend 2026 - Protótipo V1 (Arquitetura Vetorial)

Este branch/diretório contém o **primeiro protótipo** desenvolvido para o desafio da Rinha de Backend 2026. O objetivo inicial era realizar a detecção de fraudes utilizando busca de vizinhos mais próximos (K-Nearest Neighbors) diretamente no banco de dados.

## Arquitetura Inicial

- **Load Balancer:** Nginx
- **API:** Python (FastAPI + asyncpg)
- **Banco de Dados:** PostgreSQL com a extensão `pgvector`
- **Abordagem:** Cálculo de distância Euclidiana ($L_2$) em vetores de 14 dimensões sobre um dataset de 3 milhões de transações.

---

## O que deu errado? (Post-Mortem)

A arquitetura funcionou perfeitamente em um ambiente sem restrições, mas colapsou sob os rigorosos limites de recursos impostos pelas regras da Rinha (ex: `0.40 CPU` e `140MB RAM`).

Enfrentamos três grandes gargalos técnicos que inviabilizaram essa abordagem:

### 1. OOM Killer e o Custo do Índice HNSW

Para evitar que a busca levasse $O(N \times D)$ (Força Bruta), foi implementado o índice **HNSW (Hierarchical Navigable Small World)** no PostgreSQL. No entanto, o HNSW cria grafos de navegação em múltiplas camadas na memória. Quando o teste de carga aplicou requisições concorrentes, o consumo de RAM estourou o limite de 140MB, fazendo com que o Linux (OOM Killer) "assassinasse" o container do banco de dados, resultando em erro `502 Bad Gateway`.

### 2. Throttling de CPU e Fila de Conexões

Para proteger o banco de dados da falta de memória, o pool de conexões do Python (`asyncpg`) foi estrangulado para processar no máximo 3 conexões simultâneas. O banco sobreviveu, mas esbarramos no limite de **0.40 vCPUs**. A matemática vetorial (elevar 14 números ao quadrado, somar e extrair a raiz quadrada) dividindo uma fração de CPU gerou um _Context Switching_ massivo. O banco passou a levar vários segundos para resolver um único lote de queries.

### 3. Efeito Cascata (Erro 504 Gateway Time-out)

Com o banco de dados demorando para processar a fila devido à restrição de CPU, as requisições começaram a se acumular na memória da API FastAPI. O Nginx (Load Balancer), que possui um limite padrão de fábrica de 60 segundos de tolerância (`proxy_read_timeout`), começou a fechar as conexões ativas antes que o banco pudesse responder, derrubando completamente o teste de carga com **504 Gateway Time-out**.

---

## Próximos Passos (A Pivotagem)

Ficou provado que realizar cálculos matemáticos pesados de álgebra linear na camada de persistência (PostgreSQL) usando hardware extremamente limitado não é escalável para milhares de RPS (Requests Per Second).

A solução adotada na V2 (Branch Principal) abandona a busca vetorial no banco de dados e move a inteligência para a camada de aplicação:

- **Treinamento Offline:** Os 3 milhões de registros são processados fora do Docker utilizando `scikit-learn` para gerar uma Árvore de Decisão (Decision Tree Classifier).
- **Inferência em RAM (In-Memory):** O modelo compilado (`.pkl`) é carregado diretamente na memória RAM da API Python no momento do _startup_, resolvendo a regra de fraude em microssegundos (complexidade condicional `O(log N)` baseada em IF/ELSE), zerando a dependência de CPU e RAM do banco de dados na rota principal de validação.
