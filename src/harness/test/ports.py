import socket

from .state import EnvironmentMode, PortState


def is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            sock.connect((host, port))
            return False
        except ConnectionRefusedError, OSError, TimeoutError:
            return True


def find_free_port(start: int = 5432, excluded: set[int] | None = None) -> int:
    excluded = excluded or set()
    for port in range(start, start + 100):
        if port not in excluded and is_port_free(port):
            return port
    raise RuntimeError(f"No free port found in range {start}-{start + 99}")


def allocate(
    mode: EnvironmentMode,
    database: int = 0,
    backend: int = 0,
    openwebui: int = 0,
) -> PortState:
    chosen: set[int] = set()

    def select(requested: int, start: int, name: str) -> int:
        port = requested or find_free_port(start, chosen)
        if port in chosen or not is_port_free(port):
            raise RuntimeError(f"Port {port} is not available for {name}")
        chosen.add(port)
        return port

    database_port = select(database, 5432, "database")
    if mode == EnvironmentMode.LOCAL:
        return PortState(database=database_port)
    return PortState(
        database=database_port,
        backend=select(backend, 8000, "backend"),
        openwebui=select(openwebui, 3000, "openwebui"),
    )
