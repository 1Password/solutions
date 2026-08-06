# syntax=docker/dockerfile:1
FROM python:3.12-slim

# 1Password's Python SDK ships a native extension; slim images need libssl.
# python:3.12-slim already includes a compatible OpenSSL, so no extra apt
# packages are required, but we keep the image current for CVE hygiene.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY delinea-csv-to-1p-vault.py .

# Run as a non-root user. The script only ever reads a CSV you mount in and
# talks outbound to 1Password's API -- it doesn't need root.
RUN useradd --create-home --uid 1000 importer
USER importer

# Directory for mounting your Delinea CSV export in at runtime.
VOLUME ["/data"]

# `docker run delinea-to-1password --csv /data/secrets-export.csv [...]`
ENTRYPOINT ["python", "delinea-csv-to-1p-vault.py"]
CMD ["--help"]