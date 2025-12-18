FROM python:3.12.3-slim

WORKDIR /app

RUN apt-get update \
 && apt-get install -y ffmpeg \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DOWNLOAD_DIR=/app/downloads
RUN mkdir -p $DOWNLOAD_DIR

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
