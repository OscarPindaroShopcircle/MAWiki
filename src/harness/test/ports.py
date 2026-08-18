"""Find a free TCP port on localhost."""

import socket


def is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    """Return True if nothing is listening on `host:port`."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((host, port))
            return False
        except ConnectionRefusedError, OSError, TimeoutError:
            return True


def find_free_port(start: int = 5432, max_attempts: int = 100) -> int:
    """Return the first free port starting from `start`.

    Raises RuntimeError if no port is free within `max_attempts`.
    """
    for port in range(start, start + max_attempts):
        if is_port_free(port):
            return port
    raise RuntimeError(
        f"No free port found in range {start}-{start + max_attempts - 1}"
    )
