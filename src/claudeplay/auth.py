'''github oauth for the gateway: fastmcp's oauth proxy plus an allow-list on the numeric github user id'''

import hashlib
import logging
from pathlib import Path

from cryptography.fernet import Fernet
from fastmcp.server.auth import AccessToken, AuthContext, TokenVerifier
from fastmcp.server.auth.jwt_issuer import derive_jwt_key
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.providers.github import GitHubTokenVerifier
from fastmcp.server.middleware import AuthMiddleware
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from . import config

log = logging.getLogger('claudeplay.auth')

GITHUB_AUTHORIZE = 'https://github.com/login/oauth/authorize'
GITHUB_TOKEN = 'https://github.com/login/oauth/access_token'
# read:user is enough to identify the account; the default 'user' scope also grants profile writes
GITHUB_SCOPES = ['read:user']
MIN_KEY_LENGTH = 32


class AllowListVerifier(TokenVerifier):
    ''' accepts a token only when the wrapped verifier accepts it AND its github user id is allowed '''

    def __init__(self, inner: TokenVerifier, allowed_ids: set[int]):
        super().__init__(required_scopes=inner.required_scopes)
        self._inner = inner
        self._allowed = frozenset(allowed_ids)

    async def verify_token(self, token: str) -> AccessToken | None:
        verified = await self._inner.verify_token(token)
        if verified is None:
            return None
        if not is_allowed(verified, self._allowed):
            # the numeric id is public information and is what you need to diagnose a lockout
            log.warning('rejected github user id %s (not in allow-list)', verified.subject)
            return None
        return verified


def is_allowed(token: AccessToken | None, allowed_ids: frozenset[int] | set[int]) -> bool:
    ''' true only for a token whose subject is exactly one of the allowed numeric ids '''
    if token is None or not token.subject:
        return False
    try:
        return int(token.subject) in allowed_ids
    except ValueError:
        return False


def allow_list_check(allowed_ids: set[int]):
    ''' second layer: an AuthMiddleware check on the token claims, in case a verifier is swapped out '''
    allowed = frozenset(allowed_ids)

    def check(ctx: AuthContext) -> bool:
        return is_allowed(ctx.token, allowed)

    return check


def token_store(directory: Path, signing_key: str) -> FernetEncryptionWrapper:
    ''' encrypted on-disk store for client registrations and tokens, keyed off the signing key '''
    key = derive_jwt_key(high_entropy_material=signing_key, salt='claudeplay-storage-encryption-key')
    # fernet wants 32 url-safe base64 bytes, which derive_jwt_key already returns
    fingerprint = hashlib.sha256(key).hexdigest()[:12]
    directory = directory / fingerprint
    directory.mkdir(parents=True, exist_ok=True)
    store = FileTreeStore(
        data_directory=directory,
        key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(directory),
        collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(directory),
    )
    return FernetEncryptionWrapper(key_value=store, fernet=Fernet(key=key), raise_on_decryption_error=False)


def build(
    auth_cfg: config.AuthConfig,
    base_url: str,
    store_dir: Path | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[OAuthProxy, AuthMiddleware]:
    ''' the oauth proxy fronting github and the middleware enforcing the allow-list '''
    client_id = config.expand(auth_cfg.client_id, environ)
    client_secret = config.expand(auth_cfg.client_secret, environ)
    signing_key = config.expand(auth_cfg.jwt_signing_key, environ)
    if not client_id or not client_secret:
        raise config.ConfigError('auth: client_id and client_secret are required')
    if len(signing_key) < MIN_KEY_LENGTH:
        raise config.ConfigError(f'auth: jwt_signing_key must be at least {MIN_KEY_LENGTH} characters')
    allowed = {i for i in auth_cfg.allowed_user_ids if i > 0}
    if not allowed:
        # an empty allow-list would lock everyone out, but a missing one must never mean "allow all"
        raise config.ConfigError('auth: allowed_user_ids must contain your numeric github user id')

    github = GitHubTokenVerifier(
        required_scopes=GITHUB_SCOPES,
        # one verification costs two github api calls, so cache briefly
        cache_ttl_seconds=300,
    )
    provider = OAuthProxy(
        upstream_authorization_endpoint=GITHUB_AUTHORIZE,
        upstream_token_endpoint=GITHUB_TOKEN,
        upstream_client_id=client_id,
        upstream_client_secret=client_secret,
        token_verifier=AllowListVerifier(github, allowed),
        base_url=base_url,
        redirect_path='/auth/callback',
        jwt_signing_key=signing_key,
        client_storage=token_store(store_dir or config.data_dir() / 'oauth', signing_key),
        valid_scopes=GITHUB_SCOPES,
        require_authorization_consent=True,
    )
    return provider, AuthMiddleware(auth=allow_list_check(allowed))
