from fastmcp.server.auth import AuthContext


def workspace_auth_check(domain: str):
    normalized_domain = domain.casefold()

    def check(context: AuthContext) -> bool:
        token = context.token
        if token is None:
            return False
        claims = token.claims
        user_data = claims.get("google_user_data")
        if not isinstance(user_data, dict):
            return False
        email_verified = claims.get("email_verified")
        return (
            bool(claims.get("sub"))
            and bool(claims.get("email"))
            and (email_verified is True or email_verified == "true")
        ) and user_data.get("hd", "").casefold() == normalized_domain

    return check
