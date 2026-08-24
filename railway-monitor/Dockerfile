FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Keep the security-critical verifier dependency explicit at the deployment
# boundary so a stale cached requirements layer cannot produce a runtime image
# that accepts Pub/Sub traffic without OIDC verification support.
RUN pip install --no-cache-dir "google-auth>=2.40,<3"
# Fail the image build if the JWT verifier dependency is absent from the
# deployed runtime.  This prevents a production push from degrading to a
# generic ImportError after Pub/Sub delivery begins.
RUN python -c "from google.auth.transport.requests import Request; from google.oauth2 import id_token; print('google-auth OIDC runtime ready')"
COPY . .
# Verify the actual standalone image can import and execute the bundled
# canonical parser.  A missing generated bundle or dependency must fail the
# build instead of deploying a service that acknowledges mail but emits no
# observations.
RUN python -c "from email_router import parse_external_email; assert callable(parse_external_email), 'canonical external parser unavailable'; print('canonical external parser runtime ready')"

CMD ["python", "app.py"]
