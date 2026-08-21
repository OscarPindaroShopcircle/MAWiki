I’ll verify both MCP implementations’ current protocol support and inspect your existing authentication flow so the two designs map onto your backend rather than staying abstract.

## First: “FastMCP” means two different things

There are now two related but separate libraries:

### Official MCP Python SDK

Package:

```toml
mcp = ">=2"
```

Its former high-level `FastMCP` class was renamed in v2:

```python
from mcp.server import MCPServer
```

Official SDK v2 is stable and supports:

- MCP `2026-07-28`
- Older 2025-era clients on the same endpoint
- Mounting into FastAPI/Starlette
- OAuth bearer-token validation through `TokenVerifier`
- `/mcp` Streamable HTTP

### Standalone FastMCP

Package:

```toml
fastmcp
```

Imported as:

```python
from fastmcp import FastMCP
```

As of now:

- FastMCP 3.x is stable but remains on the handshake/session-era protocol.
- FastMCP 4 supports `2026-07-28` and legacy clients simultaneously.
- FastMCP 4 is currently beta.
- FastMCP has substantially more convenient OAuth integrations, including `GoogleProvider`, OAuth proxying, and component-level authorization.

Your repository currently resolves:

```text
mcp       1.29.0
fastmcp   3.4.7
```

So your current dependencies do **not** provide the modern 2026 protocol. <ref_snippet file="/home/oscar/MAWiki/pyproject.toml" lines="35-36" />

For production today, your choices are:

| Choice | Protocol | Google OAuth convenience | Stability |
|---|---|---:|---:|
| Official `mcp` v2 | Modern + legacy | You provide an OAuth authorization server/verifier | Stable |
| FastMCP 3 | Legacy | Excellent | Stable |
| FastMCP 4 | Modern + legacy | Excellent | Beta |

If latest-protocol support is important, I would use **official SDK v2** unless you specifically need FastMCP’s Google OAuth proxy enough to accept a beta dependency.

---

# How MCP authentication differs from your current login

Your existing backend currently does this:

```text
Browser
  -> /auth/google
  -> Google
  -> /auth/callback
  -> MAWiki creates its own JWT
  -> Browser sends MAWiki JWT
```

The callback only admits:

- An existing application user
- An invited email
- The bootstrap administrator

<ref_snippet file="/home/oscar/MAWiki/src/backend/auth/service.py" lines="126-181" />

Your API then decodes the MAWiki JWT, loads the user from PostgreSQL, checks that the user is active, and optionally requires the `admin` role. <ref_snippet file="/home/oscar/MAWiki/src/backend/auth/dependencies.py" lines="119-195" />

This works for your browser, but it is **not yet an MCP-compatible OAuth authorization server**. Claude, ChatGPT, Codex, and similar clients cannot use `/auth/google` and receive your JWT automatically. They expect OAuth metadata, authorization, token, client-registration, PKCE, and protected-resource behavior.

You therefore need to distinguish:

- **Authentication:** Google proves who the person is.
- **MCP authorization:** Your server decides whether that Google identity may use MCP.
- **Knowledge authorization:** Your service decides which collections/documents/tools they may access.

---

# Scenario 1: every company Google user can use MCP

## Policy

```text
MCP access:
    verified Google Workspace member
    email domain = company.com
    application account not required

Management application:
    invited MAWiki user
    role = admin for curation
```

This gives you two authorization populations:

```text
Company employees
├── MCP search/read access
└── no management UI access by default

MAWiki administrators
├── MCP search/read access
└── management/curation access
```

## User flow

When someone adds the MCP to Claude, ChatGPT, or Codex:

```text
1. Client connects to https://kb.company.com/mcp
2. MCP responds 401 and advertises OAuth metadata
3. Client discovers the MCP authorization flow
4. Browser redirects to Google
5. User signs in using their company Workspace account
6. Google returns the verified identity
7. MCP auth layer verifies company membership/domain
8. Client receives an MCP access token
9. Client sends that token on every /mcp request
```

A cloud client such as ChatGPT or Claude needs your endpoint to be publicly reachable over HTTPS. Claude Code and Codex can use the same remote endpoint.

## Why direct Google OAuth needs a proxy

Google does not provide the MCP client-registration behavior needed by every MCP client. In particular, arbitrary MCP clients have different OAuth callback URLs, while Google expects callbacks to be registered beforehand.

FastMCP’s `GoogleProvider` solves this by acting as an OAuth proxy:

```text
MCP client
   ↕ MCP OAuth/DCR/CIMD
Your MCP OAuth proxy
   ↕ fixed registered OAuth callback
Google
```

Conceptually:

```python
from fastmcp import FastMCP
from fastmcp.server.auth.providers.google import GoogleProvider

auth = GoogleProvider(
    client_id=...,
    client_secret=...,
    base_url="https://kb.company.com",
    required_scopes=["openid", "email", "profile"],
)

mcp = FastMCP("MAWiki", auth=auth)
```

You must additionally enforce:

- `email_verified == true`
- Google hosted-domain claim `hd == "company.com"`
- Appropriate issuer and audience
- Optionally an explicit email/domain allowlist

Do not authorize based only on `email.endswith("@company.com")`. The signed/validated hosted-domain and verified-email claims should be checked.

Setting the Google OAuth consent screen to **Internal** provides another useful organization-level restriction, but I would still enforce the domain server-side.

## Your database involvement

For this scenario, an MCP user does not need a `UserModel` row. The authenticated principal can be represented by:

```text
provider = google
subject = Google stable subject ID
email = employee@company.com
```

Use the Google subject as the durable identity and email for display/auditing.

Every tool can call the existing KB service directly:

```python
@mcp.tool()
async def search_knowledge(query: str):
    principal = get_authenticated_principal()
    return await kb_service.search(
        query=query,
        actor=principal,
    )
```

The MCP should expose mostly read operations:

- Search knowledge
- Retrieve document
- List available collections
- Possibly provide citations

Keep curation operations in the admin API unless you have a concrete reason to let models mutate the KB.

## Advantages

- Every employee can use Claude, ChatGPT, Codex, or Claude Code.
- No application onboarding is required for readers.
- Administrators remain a much smaller group.
- Deleting an employee from Google Workspace removes future login access.
- Clean separation between consumption and curation.

## Disadvantages

- You cannot use the current invitation table to control MCP access.
- Every organization member gets whatever MCP-readable knowledge you expose.
- Collection-level authorization needs an additional group/ACL policy if not all knowledge is company-wide.
- You need a proper MCP OAuth proxy or a standards-compliant authorization server.

---

# Scenario 2: only existing MAWiki users can use MCP

## Policy

```text
MCP access:
    valid Google identity
    AND matching active UserModel exists

Management:
    active UserModel
    AND appropriate role
```

This reuses your current application membership as an allowlist. Your current database already contains the relevant fields:

```text
email
role
is_active
```

<ref_snippet file="/home/oscar/MAWiki/src/backend/users/models.py" lines="9-15" />

## Recommended flow

Use Google to authenticate, but check application membership on every MCP request:

```text
1. MCP client starts OAuth flow
2. User signs in with Google
3. MCP validates the resulting token
4. MCP extracts Google subject and verified email
5. MCP looks up the application user
6. Request is allowed only when:
      user exists
      user.is_active is true
      provider identity/email matches
7. UserModel ID becomes the application principal
```

Conceptually:

```python
async def authorize_mcp_user(token) -> User:
    identity = validate_google_identity(token)

    user = await users_service.find_by_email(identity.email)
    if user is None or not user.is_active:
        raise PermissionError("MCP access is not enabled")

    return user
```

Ideally, look up the existing provider link by Google’s stable `sub`, with verified email as the initial linking mechanism. This is stronger than using email as the permanent identity.

## Tool-level authorization

Once the user is resolved, your existing role model applies naturally:

```text
member:
    search
    read documents
    list accessible collections

admin:
    everything above
    possibly trigger ingestion
    possibly update metadata
```

I would still avoid exposing destructive curation tools initially. If you eventually do, separate scopes and roles:

```text
OAuth scopes:
    kb:read
    kb:write

Application roles:
    member
    admin
```

A request must pass both:

```text
token has kb:write
AND
database user has admin role
```

Scopes are coarse authorization granted during OAuth. Database roles and collection ACLs are your current authoritative policy.

## Immediate deactivation

Because your existing authentication dependency loads the user from PostgreSQL on each API request, disabling `is_active` takes effect immediately. <ref_snippet file="/home/oscar/MAWiki/src/backend/auth/dependencies.py" lines="176-186" />

Use the same behavior for MCP:

```text
Access token is cryptographically valid
BUT
UserModel.is_active == false
→ deny
```

If you add caching, use a short TTL or explicit invalidation so removing access does not take hours.

## Do not simply reuse your current JWT

It is technically possible to make your current MAWiki JWT the bearer token accepted by `/mcp`, but external clients need a standards-compliant way to obtain it.

Your current endpoints are not sufficient:

```text
/auth/google
/auth/callback
/auth/refresh
```

To turn MAWiki into an OAuth authorization server, you would also need to correctly implement and secure:

- OAuth authorization endpoint
- OAuth token endpoint
- PKCE
- Client registration or CIMD
- Authorization-server metadata
- Protected-resource metadata
- Redirect URI validation
- Client binding
- OAuth consent
- Revocation
- Issuer and audience handling
- Refresh-token storage/rotation
- Multiple MCP client types

That is not a small addition, and authentication infrastructure is a poor place to build custom protocol machinery.

Instead, choose one of:

### Option A: Google OAuth proxy plus database authorization

```text
Google authenticates
FastMCP OAuth proxy handles MCP clients
MAWiki DB decides membership and permissions
```

This is the simplest fit for your current code.

### Option B: Dedicated authorization server

Use Keycloak, Auth0, WorkOS, Descope, or another MCP-compatible authorization server:

```text
Google Workspace
      ↓ federation
Authorization server
      ↓ OAuth access token
MCP resource server
      ↓ membership lookup
MAWiki database
```

Then official MCP SDK v2 only needs a `TokenVerifier`.

This is more infrastructure, but cleaner if you need enterprise lifecycle management, groups, service accounts, or several protected internal applications.

---

# How to integrate authorization with the mounted FastAPI app

Both interfaces should resolve to the same application principal:

```text
FastAPI request
    MAWiki JWT
       ↓
    UserModel

MCP request
    OAuth bearer token
       ↓
    Google identity
       ↓
    optional UserModel lookup
```

Do not force the MCP ASGI application through `Depends(get_current_user)`. Mounted ASGI applications do not naturally use FastAPI route dependencies in the same manner.

Instead, extract reusable services:

```text
auth/
├── dependencies.py        FastAPI transport adapter
├── mcp.py                 MCP token/principal adapter
├── service.py             Shared identity/user lookup
└── policy.py              Shared permission decisions
```

For example:

```python
async def resolve_application_user(
    db: AsyncSession,
    *,
    provider: str,
    provider_sub: str,
    email: str,
) -> User:
    ...
```

Then:

```text
FastAPI dependency → resolve user → policy
MCP auth check    → resolve user → same policy
```

The KB service should accept an explicit actor:

```python
await kb_service.search(
    query=query,
    actor=current_actor,
)
```

That prevents authorization from being hidden inside HTTP-specific globals and makes the same service safe for REST and MCP.

## Mounting structure

The resulting application can remain:

```text
https://kb.company.com/auth/...        Existing application login
https://kb.company.com/api/...         Management API
https://kb.company.com/mcp             MCP endpoint
https://kb.company.com/.well-known/... MCP OAuth metadata
```

The well-known and OAuth proxy routes must be available where clients expect them. Do not blindly mount every OAuth route beneath `/mcp`; metadata and callbacks often need root-level or specifically advertised paths.

Your existing `create_app()` already has a central lifespan and router registration point where the MCP ASGI lifecycle can eventually be composed. <ref_snippet file="/home/oscar/MAWiki/src/backend/server.py" lines="15-32" /> <ref_snippet file="/home/oscar/MAWiki/src/backend/server.py" lines="56-90" />

---

# Which scenario I recommend

For a company knowledge base, I recommend a **hybrid version of scenario 1**:

```text
All verified company Google users:
    MCP search/read

Invited MAWiki users:
    management UI access

MAWiki admins:
    curation

No MCP write tools initially
```

This matches the real distinction between:

- Knowledge consumers: most of the company
- Knowledge curators: a small invited group

Only choose scenario 2 if the knowledge itself is restricted to a specific subset of employees, or if application deactivation must independently revoke MCP access even while the person remains in Google Workspace.

A useful future extension is:

```text
Company Google identity required
AND
one of:
    company-wide collection
    permitted Google group
    matching MAWiki ACL
```

That gives broad onboarding without making every collection universally visible.

## Practical library choice

Given your requirements:

### If latest MCP protocol is mandatory now

Use:

```text
Official mcp SDK v2
+ established OAuth authorization server
+ custom TokenVerifier
+ MAWiki DB authorization check
```

### If direct Google SSO and easy multi-client OAuth are the priority

Use:

```text
FastMCP GoogleProvider
```

Then either:

- Stay on stable FastMCP 3 temporarily, or
- Exact-pin FastMCP 4 beta and test all target clients carefully.

I would not upgrade the current repository to an unbounded `fastmcp>=4` while it is beta. Exact-pin it if selected.

Sources:

- [Official SDK v2 migration guide](https://py.sdk.modelcontextprotocol.io/v2/migration/)
- [Official SDK v2 authorization](https://py.sdk.modelcontextprotocol.io/v2/run/authorization/)
- [FastMCP 4 protocol notes](https://gofastmcp.com/development/v4-notes/protocol-2026)
- [FastMCP Google/OAuth proxy](https://gofastmcp.com/servers/auth/oauth-proxy)
- [FastMCP authorization checks](https://gofastmcp.com/servers/authorization)
- [Claude Code remote MCP authentication](https://code.claude.com/docs/en/mcp)
- [Codex MCP documentation](https://developers.openai.com/codex/mcp)
