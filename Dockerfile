FROM python:3.11-bullseye

RUN apt-get update
RUN apt-get install -y curl gnupg libglib2.0-0 libnss3 libatk-bridge2.0-0 libxss1 libasound2 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 libxdamage1 libxext6 libxfixes3 libxi6 libxtst6 libgtk-3-0 libdrm2 libgbm1 libxrandr2 libxrender1 libxshmfence1 libxinerama1 libatk1.0-0 libcups2 libpangocairo-1.0-0 libpango-1.0-0 libx11-6 libxcb-dri3-0 build-essential
RUN rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip
RUN pip install awslambdaric

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

RUN playwright install chromium

COPY . .

CMD ["python3", "-m", "awslambdaric", "handler.handler"]
