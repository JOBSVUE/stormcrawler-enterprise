# Use a modern Python base. Default port set to 8001 to avoid extractor's 8000.
FROM python:3.12-bookworm

ENV PYTHONUNBUFFERED=1 \
    PORT=8001 \
    HEADLESS=1 \
    BROWSER=chromium

# Install minimal OS deps; playwright install --with-deps will add browser deps too
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    wget \
    gnupg \
    libnss3 \
    libxss1 \
    libasound2 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# install python deps
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip
RUN pip install --no-cache-dir -r /app/requirements.txt

# Install playwright browsers and required OS deps in one step
RUN python -m playwright install --with-deps

# Copy application files
COPY app.py /app/app.py
COPY entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

EXPOSE ${PORT}

ENTRYPOINT ["/app/entrypoint.sh"]
