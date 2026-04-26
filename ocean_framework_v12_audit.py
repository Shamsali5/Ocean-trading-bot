"""Framework v1.2 audit trace helpers for transparent rule checking."""

from __future__ import annotations

from dataclasses import dataclass, field

from ocean_framework_v12_contract import normalize_tf


SEVERITY_LEVELS = ("INFO", "WARNING", "ERROR", "FATAL")
TIMEFRAME_PRIORITY = ("1d", "12h", "4h", "1h", "15m", "5m", "3m")
PARENT_CONTEXT_TFS = {"1d", "12h", "4h", "1h"}
LOW_EXECUTION_TFS = {"5m", "3m"}


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


def verify_timeframe_order(
    available_timeframes: list[str] | tuple[str, ...] | set[str],
    trace: FrameworkAuditTrace,
) -> dict[str, object]:
    """Verify highest-timeframe-first reading order and emit trace checks."""

    raw_timeframes = [str(item) for item in available_timeframes]
    normalized: list[str] = []
    for item in raw_timeframes:
        tf = normalize_tf(item)
        if tf not in normalized:
            normalized.append(tf)

    sorted_timeframes = sorted(
        normalized,
        key=lambda tf: (_tf_priority_index(tf), tf),
    )
    highest = sorted_timeframes[0] if sorted_timeframes else None
    first_read = normalized[0] if normalized else None

    trace.add_check(
        name="Highest timeframe detected",
        passed=highest is not None,
        severity="ERROR" if highest is None else "INFO",
        details=f"Highest timeframe: {highest or 'N/A'}",
        file="ocean_framework_v12_audit.py",
        function="verify_timeframe_order",
    )

    starts_from_highest = bool(highest is not None and first_read == highest)
    trace.add_check(
        name="Analysis starts from highest timeframe",
        passed=starts_from_highest,
        severity="ERROR" if not starts_from_highest else "INFO",
        details=f"First read timeframe: {first_read or 'N/A'}; expected: {highest or 'N/A'}",
        file="ocean_framework_v12_audit.py",
        function="verify_timeframe_order",
    )

    higher_context_available = any(tf in PARENT_CONTEXT_TFS for tf in normalized)
    starts_low = first_read in LOW_EXECUTION_TFS
    lower_before_higher = bool(higher_context_available and starts_low)
    trace.add_check(
        name="Lower timeframe not allowed to decide before higher context",
        passed=not lower_before_higher,
        severity="ERROR" if lower_before_higher else "INFO",
        details=(
            "Lower timeframe attempted to lead despite available higher context."
            if lower_before_higher
            else "Higher-timeframe context read before lower execution levels."
        ),
        file="ocean_framework_v12_audit.py",
        function="verify_timeframe_order",
    )

    return {
        "normalized_timeframes": normalized,
        "sorted_timeframes": sorted_timeframes,
        "highest_timeframe": highest,
        "first_read_timeframe": first_read,
        "higher_context_available": higher_context_available,
        "lower_before_higher": lower_before_higher,
    }


def _icon_for_check(check: FrameworkCheck) -> str:
    """Return icon marker for one check row."""

    if check.passed:
        return "✅"
    if check.severity == "WARNING":
        return "⚠️"
    return "❌"


def _tf_priority_index(tf: str) -> int:
    """Return timeframe priority index; unknown labels sort last."""

    try:
        return TIMEFRAME_PRIORITY.index(tf)
    except ValueError:
        return len(TIMEFRAME_PRIORITY) + 1
