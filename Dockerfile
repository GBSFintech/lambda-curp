FROM python:3.11-bullseye

# Instala dependencias del sistema
RUN apt-get update && apt-get install -y \
    wget gnupg ca-certificates curl unzip \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2 \
    libxshmfence1 libxss1 libxtst6 libnss3 libx11-xcb1 libgtk-3-0 \
    libxcb1 libx11-6 libxext6 fonts-liberation \
    && apt-get clean

# Crear directorio de trabajo
WORKDIR /app

# Copiar requerimientos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps

# Copiar el código
COPY . .

# Exponer el puerto
EXPOSE 8000

# Comando por defecto
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
