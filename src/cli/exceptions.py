class ModuleExistsException(Exception):
    """Raised when the target module already exists."""


class InvalidModuleNameException(ValueError):
    """Raised when a module name is not a valid Python package name."""
