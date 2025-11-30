FROM python:3.11-slim
WORKDIR /app

# Install system deps for some packages
RUN apt-get update && apt-get install -y build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app
ENV PYTHONUNBUFFERED=1
EXPOSE 8501
CMD ["gunicorn", "web_app.app:app", "--bind", "0.0.0.0:8501", "--workers", "2"]
