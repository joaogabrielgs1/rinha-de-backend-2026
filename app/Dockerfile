FROM python:3.11-slim

WORKDIR /app

# Avisa o Docker para entrar na pasta "app/" da sua máquina e copiar o txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o resto do código da pasta "app/" para dentro do container
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]