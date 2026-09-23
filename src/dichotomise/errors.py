"""DichotomiseError and the stage-specific errors raised across the pipeline."""

from __future__ import annotations


class DichotomiseError(Exception):
    """Base class for every error dichotomise raises deliberately."""


class NotDicomError(DichotomiseError):
    """Raised when a file that was expected to be DICOM cannot be read as one."""


class DestinationExistsError(DichotomiseError):
    """Raised rather than overwriting a folder or file that already exists."""


class RelabelError(DichotomiseError):
    """Raised when a subject cannot be safely relabelled or sanitised."""


class PolicyNotFoundError(DichotomiseError):
    """Raised when --sanitise-level names a policy file that does not exist."""


class NoDicomFilesFoundError(DichotomiseError):
    """Raised when a source directory has no readable DICOM files under it."""


class UnsafeSourceError(DichotomiseError):
    """Raised when a source directory contains something unsafe to copy, e.g. a symlink."""


class NamingCollisionError(DichotomiseError):
    """Raised when two different scan files would end up with the same rectified name."""


class FinaliseVerificationError(DichotomiseError):
    """Raised when the finished output does not match what was expected before archiving."""
