class McpSessionAccessDeniedException(PermissionError):
    """Raised when an MCP session belongs to another authenticated principal."""
