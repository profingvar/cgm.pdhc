from datetime import timezone
from zoneinfo import ZoneInfo

from flask import Flask
from .extensions import db, migrate
from config import Config

# Models store timestamps as UTC (explicit tzinfo or naive-UTC — see
# careplan_cache.py / api_key.py). Templates want local wall-clock time for
# display. Default format matches the majority of |local(...) callsites.
_LOCAL_TZ = ZoneInfo('Europe/Stockholm')


def _format_local(value, fmt='%Y-%m-%d %H:%M:%S'):
    """Jinja filter: UTC datetime -> Europe/Stockholm formatted string."""
    if value is None:
        return ''
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_LOCAL_TZ).strftime(fmt)


def create_app(config_class=Config):
    app = Flask(
        __name__,
        static_folder='../static',
        template_folder='../templates',
    )
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)

    # Jinja filter used across templates (dashboard, tasks, receipts, audit, ...).
    app.add_template_filter(_format_local, 'local')

    from .api import api_bp
    app.register_blueprint(api_bp, url_prefix='/api/v1')

    from .web import web_bp
    app.register_blueprint(web_bp)

    from .errors import register_error_handlers
    register_error_handlers(app)

    from .cli import sync_cli
    app.cli.add_command(sync_cli)

    # Key-based user authentication
    app.config.setdefault('KEYAUTH_PORTAL_NAME', 'CGM Portal')
    app.config.setdefault('KEYAUTH_DASHBOARD_ENDPOINT', 'web.dashboard')
    app.config.setdefault('KEYAUTH_BOOTSTRAP_USER', 'admin')
    if app.config.get('BOOTSTRAP_API_KEY'):
        app.config.setdefault('KEYAUTH_BOOTSTRAP_KEY', app.config['BOOTSTRAP_API_KEY'])

    from pdhc_keyauth import init_keyauth
    init_keyauth(app, db)

    @app.route('/api/v1/health')
    def health():
        from flask import jsonify
        from sqlalchemy import text
        db_ok = False
        try:
            db.session.execute(text('SELECT 1'))
            db_ok = True
        except Exception:
            pass
        status = 'ok' if db_ok else 'degraded'
        code = 200 if db_ok else 503
        resp = jsonify({
            'status': status,
            'database': 'connected' if db_ok else 'unavailable',
            'service': 'cgm.pdhc',
        })
        # Allow www.pdhc.se/services.html to read the JSON body cross-origin
        # so it can drive real status/DB dots (ticket #70 / CLAUDE.md §10).
        # Specific origin + Vary: Origin (not "*") stays spec-compliant if we
        # ever enable Allow-Credentials.
        resp.headers['Access-Control-Allow-Origin'] = 'https://www.pdhc.se'
        resp.headers['Access-Control-Allow-Methods'] = 'GET'
        resp.headers['Vary'] = 'Origin'
        resp.headers['Cache-Control'] = 'no-store'
        return resp, code

    with app.app_context():
        _bootstrap_admin(app)

    # Start background sync if enabled (not in testing)
    if app.config.get('SYNC_ENABLED') and not app.config.get('TESTING'):
        _start_background_sync(app)

    return app


def _start_background_sync(app):
    from .services.subscription import RequestSubscriptionService
    from .services.sync_scheduler import SyncScheduler

    svc = RequestSubscriptionService(app=app)
    scheduler = SyncScheduler(app=app, subscription_service=svc)
    scheduler.start()
    app.extensions['sync_scheduler'] = scheduler


def _bootstrap_admin(app):
    """Create bootstrap provider + API key on first run if table exists."""
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    if not inspector.has_table('providers'):
        return

    from .models import Provider, ApiKey
    bootstrap_key = app.config.get('BOOTSTRAP_API_KEY')
    if not bootstrap_key:
        return

    existing = Provider.query.filter_by(name=app.config['BOOTSTRAP_PROVIDER_NAME']).first()
    if existing:
        return

    import uuid
    provider = Provider(
        guid=app.config.get('PROVIDER_GUID') or str(uuid.uuid4()),
        name=app.config['BOOTSTRAP_PROVIDER_NAME'],
        is_active=True,
    )
    db.session.add(provider)
    db.session.flush()

    api_key = ApiKey.create(
        provider_guid=provider.guid,
        raw_key=bootstrap_key,
        scopes='read,write',
        label='bootstrap',
    )
    db.session.add(api_key)
    db.session.commit()
