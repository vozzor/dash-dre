FROM python:3.12-slim

WORKDIR /app

# dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copia o código
COPY . .

# Cloud Run injeta a variável PORT; gunicorn escuta nela
ENV PORT=8080
EXPOSE 8080

# gunicorn serve o Flask server do Dash
CMD ["gunicorn", "--workers=2", "--threads=4", "--bind=0.0.0.0:8080", "--timeout=120", "app:server"]
