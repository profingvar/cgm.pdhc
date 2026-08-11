import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    BOOTSTRAP_API_KEY = os.environ.get('BOOTSTRAP_API_KEY')
    BOOTSTRAP_PROVIDER_NAME = os.environ.get('BOOTSTRAP_PROVIDER_NAME', 'System Administrator')

    # Instance identity
    PROVIDER_GUID = os.environ.get('PROVIDER_GUID')
    PROVIDER_NAME = os.environ.get('PROVIDER_NAME')

    # Upstream service that receives provider reports. NOTE: despite the name,
    # /provider/report, /provider/feed and /download live on the GATEWAY, not
    # request.pdhc — the default must point at gateway.pdhc.se (the live
    # container already overrides to this; the old request.pdhc default would
    # 404 every submission on a fresh deploy). Var name kept for the override.
    REQUEST_SERVICE_URL = os.environ.get('REQUEST_SERVICE_URL', 'https://gateway.pdhc.se/api/v1')
    SSO_API_KEY = os.environ.get('SSO_API_KEY')  # legacy — kept for backward compat
    PROVIDER_TOKEN = os.environ.get('PROVIDER_TOKEN')  # PAT issued by request.pdhc

    # Push reception
    PUSH_SECRET = os.environ.get('PUSH_SECRET')  # shared secret for validating inbound pushes

    # Gateway receipt ingestion
    GATEWAY_SERVICE_KEY = os.environ.get('GATEWAY_SERVICE_KEY')  # internal key for gateway.pdhc receipts

    # Sync settings
    SYNC_INTERVAL_SECONDS = int(os.environ.get('SYNC_INTERVAL_SECONDS', '60'))
    SYNC_ENABLED = os.environ.get('SYNC_ENABLED', 'false').lower() in ('true', '1', 'yes')


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    BOOTSTRAP_API_KEY = 'test-bootstrap-key'
    PROVIDER_GUID = 'test-instance-guid'
    PROVIDER_NAME = 'Test CGM Provider Instance'
    REQUEST_SERVICE_URL = 'http://mock-request-service/api/v1'
    SSO_API_KEY = 'test-sso-key'
    PROVIDER_TOKEN = 'test-provider-token'
    PUSH_SECRET = 'test-push-secret'
    GATEWAY_SERVICE_KEY = 'test-gateway-key'
    SYNC_ENABLED = False
