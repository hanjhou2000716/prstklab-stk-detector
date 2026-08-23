FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Fail the image build if the JWT verifier dependency is absent from the
# deployed runtime.  This prevents a production push from degrading to a
# generic ImportError after Pub/Sub delivery begins.
RUN python -c "import google.auth, google.oauth2.id_token; print('google-auth runtime ready')"
COPY . .

CMD ["python", "app.py"]
