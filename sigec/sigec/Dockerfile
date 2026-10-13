FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
ENV DB_PATH=/data/sigec.db PORT=8000
RUN mkdir /data
VOLUME /data
CMD ["sh","-c","gunicorn -w 1 --threads 4 -b 0.0.0.0:${PORT} app:app"]
