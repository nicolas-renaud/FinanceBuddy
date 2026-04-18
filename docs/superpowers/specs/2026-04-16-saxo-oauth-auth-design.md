# Saxo OAuth Auth Design

Date: 2026-04-16

## Goal

FinanceBuddy should authenticate to Saxo's simulation OpenAPI without requiring a manually pasted access token for every crawl. The Saxo crawler should remain read-only, use OAuth correctly, and avoid storing brokerage passwords or secrets in the repository.

The normal user experience should be:

```bash
uv run financebuddy crawl \
  --data-dir ./data \
  --connector saxo \
  --saxo-source sim \
  --owner nico
```

If a usable token is already available, the crawl should run immediately. If no refresh token exists, or if the stored refresh token can no longer be used, FinanceBuddy should start the browser-based Saxo login flow automatically and continue the crawl after successful authorization.

## Non-Goals

- Do not automate Saxo username/password login.
- Do not store Saxo passwords.
- Do not support order placement or trading permissions.
- Do not implement institutional certificate-based authentication.
- Do not require a web-hosted redirect URL for local use.
- Do not put tokens, authorization codes, or app secrets in snapshots, event logs, or crawl-run metadata.

## OAuth Approach

Use Saxo's Authorization Code with PKCE flow for local FinanceBuddy auth.

PKCE is preferred because FinanceBuddy is a local CLI application and should not need a long-lived OAuth app secret. The Saxo app should be configured with:

- Grant type: PKCE
- Trading enabled: no
- Redirect URL: `http://localhost/financebuddy`

FinanceBuddy may use a concrete local callback URL with a port while running, for example:

```text
http://localhost:8765/financebuddy
```

The registered Saxo redirect URL should remain compatible with Saxo's validation rules. If Saxo rejects port-bearing registered redirect URLs, FinanceBuddy should register the portless localhost URL and use the runtime port in the authorization request only if Saxo accepts it for the app. The temporary HTTP listener should still bind only to loopback, not to external network interfaces.

## Runtime Flow

For `--connector saxo --saxo-source sim`, the CLI should resolve an access token in this order:

1. If `SAXO_ACCESS_TOKEN` is set, use it as an explicit override and preserve the current behavior.
2. Otherwise, load a stored token set for the Saxo profile.
3. If a refresh token is present, call Saxo's token endpoint with `grant_type=refresh_token`.
4. If refresh succeeds, save the returned token set and continue the crawl with the fresh access token.
5. If the refresh token is missing, expired, revoked, or rejected, start an interactive PKCE login unless disabled by CLI flags.
6. After login succeeds, save the token set and continue the crawl.
7. If interactive login is disabled and no usable token is available, fail with an actionable message.

The crawler should never see the refresh token directly. It should receive only a short-lived access token through `RuntimeCredentials`.

## Interactive Login Flow

The auth helper should:

1. Generate a cryptographically random `state`.
2. Generate a cryptographically random PKCE `code_verifier`.
3. Derive the S256 `code_challenge`.
4. Start a temporary HTTP listener bound to `127.0.0.1`.
5. Build the Saxo authorization URL using the app key, redirect URI, state, code challenge, and S256 challenge method.
6. Print the URL and try to open it in the user's browser when appropriate.
7. Receive the OAuth callback.
8. Validate that the returned `state` matches.
9. Exchange the authorization code and `code_verifier` for tokens at Saxo's token endpoint.
10. Save the returned token set securely.
11. Shut down the temporary listener.

If opening a browser is not available, FinanceBuddy should print the URL and wait for the callback. If the callback times out, it should fail without leaking the authorization URL query values beyond what the user already saw.

## Token Storage

Introduce a token-store abstraction so storage can evolve without coupling auth logic to one backend:

```text
get(profile_id) -> TokenSet | None
save(profile_id, token_set) -> None
delete(profile_id) -> None
```

Initial implementation:

- Store tokens under the configured data directory, outside snapshots.
- Suggested path: `<data-dir>/secrets/saxo/<profile_id>.json`.
- Create directories with restrictive permissions.
- Write token files with `0600` permissions.
- Do not commit token files.

The stored token set should include:

- `access_token`, if useful for reuse before expiry
- `refresh_token`
- `expires_at`
- `refresh_token_expires_at`, if Saxo provides enough information
- token type
- Saxo environment, initially `sim`
- app key identifier or hash to avoid reusing tokens with the wrong app

Future storage backends can include macOS Keychain or 1Password. The first implementation should keep the interface small enough to add those later.

## 1Password Use

1Password is appropriate for long-lived app configuration and optional token storage. It should not be used to let FinanceBuddy replay the user's Saxo password.

For PKCE, FinanceBuddy needs only the app key. This can be supplied by:

- `SAXO_APP_KEY`
- a CLI option such as `--saxo-app-key`
- a future config profile
- `op run` environment injection

Example:

```bash
op run --env-file .env.1password -- uv run financebuddy crawl \
  --data-dir ./data \
  --connector saxo \
  --saxo-source sim \
  --owner nico
```

For the current Authorization Code app that has an app secret, FinanceBuddy could support `SAXO_APP_SECRET` later, but PKCE should be the primary path.

## CLI Behavior

Add an explicit auth command for setup and troubleshooting:

```bash
uv run financebuddy saxo-auth login \
  --data-dir ./data \
  --owner nico
```

The crawl command should also be able to trigger login automatically:

```bash
uv run financebuddy crawl \
  --data-dir ./data \
  --connector saxo \
  --saxo-source sim \
  --owner nico
```

Add a non-interactive guard for automation:

```bash
uv run financebuddy crawl \
  --data-dir ./data \
  --connector saxo \
  --saxo-source sim \
  --owner nico \
  --no-auth-login
```

With `--no-auth-login`, FinanceBuddy should refresh existing tokens if possible but must not start browser login. If no valid token is available, it should fail clearly.

## Security Requirements

- Keep trading disabled in the Saxo developer app.
- Bind the local callback listener to `127.0.0.1`.
- Validate OAuth `state`.
- Use high-entropy random values for `state` and PKCE verifier.
- Do not log tokens, refresh tokens, app secrets, authorization codes, or full callback URLs.
- Redact sensitive values from exceptions and CLI output.
- Store refresh tokens outside snapshots and outside SQLite event-log/projection tables.
- Keep access tokens in memory unless persisting them is needed for expiry tracking.
- Never send Saxo credentials to FinanceBuddy.
- Preserve `SAXO_ACCESS_TOKEN` as an explicit override for development and emergency use.

## Error Handling

FinanceBuddy should distinguish these cases:

- Missing `SAXO_APP_KEY`: explain how to provide it.
- No stored token and login disabled: explain to run without `--no-auth-login` or run `saxo-auth login`.
- Refresh token rejected: delete or replace the invalid token only after a successful new login, or ask the user to reauthorize.
- Callback timeout: fail without altering the existing stored token.
- OAuth state mismatch: reject the callback and fail the login.
- Saxo token endpoint error: show status and a redacted message.

## Testing

Add tests for:

- PKCE verifier and challenge generation.
- Authorization URL construction.
- State validation on callback.
- Token refresh success.
- Expired/rejected refresh token triggering interactive login when allowed.
- Expired/rejected refresh token failing when `--no-auth-login` is set.
- `SAXO_ACCESS_TOKEN` override preserving current behavior.
- Token store file permissions and profile scoping.
- CLI Saxo crawl receiving only an access token in `RuntimeCredentials`.

Network calls should be mocked. Tests should not contact Saxo.

## Open Decisions

- Whether the initial token store is file-only or uses macOS Keychain when available.
- Whether the local callback port is fixed, configurable, or chosen dynamically.
- Whether FinanceBuddy should open the browser automatically or only print the URL by default.
- Whether to support the existing Authorization Code app with `SAXO_APP_SECRET` in the first implementation, or require a PKCE app.
