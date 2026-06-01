from ..errors import APIError


class GuidedResponseService:

    @staticmethod
    def validate_observations(observations, transactions):
        """Validate observations against careplan transaction requirements."""
        errors = []
        tx_map = {t['transaction_guid']: t for t in transactions}
        submitted_guids = set()

        for obs in observations:
            tx_guid = obs.get('transaction_guid')
            if not tx_guid:
                errors.append({'field': 'transaction_guid', 'message': 'Missing transaction_guid'})
                continue

            submitted_guids.add(tx_guid)
            tx = tx_map.get(tx_guid)
            if not tx:
                errors.append({
                    'field': 'transaction_guid',
                    'value': tx_guid,
                    'message': 'Unknown transaction',
                })
                continue

            if not obs.get('value') and obs.get('value') != 0:
                errors.append({
                    'transaction_guid': tx_guid,
                    'concept_name': tx.get('concept_name', ''),
                    'message': 'Value is required',
                })

            if tx.get('response_type') == 'categorical' and tx.get('valueset_values'):
                valid_values = [v['code'] if isinstance(v, dict) else v for v in tx['valueset_values']]
                if obs.get('value') not in valid_values:
                    errors.append({
                        'transaction_guid': tx_guid,
                        'concept_name': tx.get('concept_name', ''),
                        'message': f'Value must be one of: {valid_values}',
                    })

        # Check required transactions
        for tx_guid, tx in tx_map.items():
            if tx.get('required') and tx_guid not in submitted_guids:
                errors.append({
                    'transaction_guid': tx_guid,
                    'concept_name': tx.get('concept_name', ''),
                    'message': 'Required observation missing',
                })

        if errors:
            raise APIError(
                'Observation validation failed',
                code='VALIDATION_ERROR',
                status_code=422,
                details=errors,
            )

    @staticmethod
    def build_payload(observations):
        """Normalize observations into minimal submission payload.

        Only provider-generated fields are included. Gateway derives
        concept_guid, unit, ranges, etc. from the SR's transaction map.
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        normalized = []
        for obs in observations:
            entry = {
                'transaction_guid': obs['transaction_guid'],
                'value': obs['value'],
                'recorded_at': obs.get('recorded_at', now),
            }
            if obs.get('notes'):
                entry['notes'] = obs['notes']
            normalized.append(entry)
        return {'observations': normalized}
