"""Pure business rules shared by the server and the register's Device Agent.

No database, no I/O: the server feeds it rows from SQL Server, the agent from its
offline cache, so an offline sale is priced by exactly the same code (ADR-0017).
"""

__version__ = "0.8.0"


class CoreError(Exception):
    """A business-rule violation with a stable code and a Persian message."""

    def __init__(self, message: str, code: str, *, not_found: bool = False) -> None:
        super().__init__(message)
        self.message, self.code, self.not_found = message, code, not_found
