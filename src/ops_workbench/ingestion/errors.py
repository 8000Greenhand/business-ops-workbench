"""Explicit exceptions raised while reading local source files."""


class SourceFileError(Exception):
    """Base class for local source-file failures."""


class SourceFileNotFoundError(SourceFileError):
    """Raised when a requested source file does not exist."""


class EmptySourceFileError(SourceFileError):
    """Raised when a source file contains no data rows."""


class UnsupportedSourceFormatError(SourceFileError):
    """Raised when no reader exists for a file extension."""


class InvalidSourceFileError(SourceFileError):
    """Raised when a supported file cannot be parsed."""


class SheetNotFoundError(SourceFileError):
    """Raised when a requested workbook sheet does not exist."""
