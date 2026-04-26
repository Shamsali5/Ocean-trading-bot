"""Framework v1.2 audit trace helpers for transparent rule checking."""

from __future__ import annotations

from dataclasses import dataclass, field


SEVERITY_LEVELS = ("INFO", "WARNING", "ERROR", "FATAL")


@dataclass(slots=True)
class FrameworkCheck:
    """Single framework verification row."""

    name: str
    passed: bool
    severity: str  # "INFO", "WARNING", "ERROR", "FATAL"
    details: str
    file: str | None = None
    function: str | None = None

    def __post_init__(self) -> None:
        """Normalize severity to known values."""

        value = str(self.severity).strip().upper()
        self.severity = value if value in SEVERITY_LEVELS else "INFO"


@dataclass(slots=True)
class FrameworkAuditTrace:
    """Audit container recording all framework checks for one analysis."""

    symbol: str
    timestamp: str
    checks: list[FrameworkCheck] = field(default_factory=list)

    def add_check(
        self,
        name: str,
        passed: bool,
        severity: str = "INFO",
        details: str = "",
        file: str | None = None,
        function: str | None = None,
    ) -> None:
        """Append one framework check row."""

        self.checks.append(
            FrameworkCheck(
                name=name,
                passed=bool(passed),
                severity=severity,
                details=details,
                file=file,
                function=function,
            )
        )

    def has_errors(self) -> bool:
        """Return true when at least one failed ERROR/FATAL check exists."""

        return any(
            (not check.passed) and check.severity in {"ERROR", "FATAL"}
            for check in self.checks
        )

    def has_fatal(self) -> bool:
        """Return true when at least one failed FATAL check exists."""

        return any(
            (not check.passed) and check.severity == "FATAL"
            for check in self.checks
        )

    def failed_checks(self) -> list[FrameworkCheck]:
        """Return all failed checks in insertion order."""

        return [check for check in self.checks if not check.passed]

    def render_plain_text(self) -> str:
        """Render trace using human-friendly plain text format."""

        lines = [
            "FRAMEWORK v1.2 AUDIT TRACE",
            f"Symbol: {self.symbol}",
            f"Timestamp: {self.timestamp}",
            "",
        ]
        for check in self.checks:
            icon = _icon_for_check(check)
            lines.extend(
                [
                    f"{icon} {check.name}",
                    f"Severity: {check.severity}",
                    f"Details: {check.details}",
                    f"File: {check.file if check.file else 'N/A'}",
                    f"Function: {check.function if check.function else 'N/A'}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip()


def assert_or_wait(
    trace: FrameworkAuditTrace,
    condition: bool,
    check_name: str,
    reason: str,
) -> bool:
    """Record failed ERROR check when condition is false, then return condition."""

    if not condition:
        trace.add_check(
            name=check_name,
            passed=False,
            severity="ERROR",
            details=reason,
        )
    return condition


def _icon_for_check(check: FrameworkCheck) -> str:
    """Return icon marker for one check row."""

    if check.passed:
        return "✅"
    if check.severity == "WARNING":
        return "⚠️"
    return "❌"
