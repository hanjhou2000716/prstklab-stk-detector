FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Fail the image build if the JWT verifier dependency is absent from the
# deployed runtime.  This prevents a production push from degrading to a
# generic ImportError after Pub/Sub delivery begins.
RUN python -c "from google.auth.transport.requests import Request; from google.oauth2 import id_token; print('google-auth OIDC runtime ready')"
COPY . .

CMD ["python", "app.py"]
