"""Flask CLI commands for sync management."""
import click
from flask import current_app
from flask.cli import AppGroup

sync_cli = AppGroup('sync', help='Manage request subscription sync.')


@sync_cli.command('run')
def sync_run():
    """Run one sync cycle."""
    from .services.subscription import RequestSubscriptionService

    svc = RequestSubscriptionService(app=current_app._get_current_object())
    provider_guid = current_app.config.get('PROVIDER_GUID')

    if not provider_guid:
        click.echo('Error: PROVIDER_GUID not configured in .env')
        return

    click.echo(f'Syncing for provider {provider_guid}...')
    try:
        new, updated, skipped = svc.sync()
        click.echo(f'Sync complete: {new} new, {updated} updated, {skipped} skipped')
    except Exception as e:
        click.echo(f'Sync failed: {e}')


@sync_cli.command('status')
def sync_status():
    """Show current sync status."""
    from .services.subscription import RequestSubscriptionService

    svc = RequestSubscriptionService(app=current_app._get_current_object())
    status = svc.get_status()

    if not status.get('configured'):
        click.echo('Sync not configured: PROVIDER_GUID not set')
        return

    click.echo(f"Provider:        {status.get('provider_name', '—')}")
    click.echo(f"GUID:            {status.get('provider_guid')}")
    click.echo(f"Sync enabled:    {status.get('sync_enabled')}")
    click.echo(f"Upstream URL:    {status.get('request_service_url')}")
    click.echo(f"Last sync:       {status.get('last_sync_at', 'never')}")
    click.echo(f"Requests synced: {status.get('requests_synced', 0)}")
    click.echo(f"Last error:      {status.get('last_error', 'none')}")


@sync_cli.command('reset')
def sync_reset():
    """Reset sync cursor to re-sync all requests."""
    from .models import SyncState
    from .extensions import db

    provider_guid = current_app.config.get('PROVIDER_GUID')
    if not provider_guid:
        click.echo('Error: PROVIDER_GUID not configured')
        return

    state = SyncState.query.filter_by(provider_guid=provider_guid).first()
    if state:
        state.last_sync_at = None
        state.last_sync_cursor = None
        state.last_error = None
        db.session.commit()
        click.echo(f'Sync cursor reset for {provider_guid}. Next sync will fetch all requests.')
    else:
        click.echo('No sync state found — nothing to reset.')
