from django.core.cache import cache

from .models import Credential


def get_decrypted_token(user_id, service_name):
    """
    Fetches integration tokens from Redis memory.
    Only hits the DB for decryption if the cache has expired.
    """
    cache_key = f"token_{service_name}_{user_id}"
    token_data = cache.get(cache_key)

    if not token_data:
        try:
            # The database pull and decryption tax happens here
            cred = Credential.objects.get(owner_id=user_id, service=service_name)
            token_data = cred.data  # Automatically decrypted by your EncryptedJSONField

            # Cache the decrypted dictionary for 1 hour
            cache.set(cache_key, token_data, timeout=3600)
        except Credential.DoesNotExist:
            return None

    return token_data
