from guardian.models import KIND_WASTE, Finding

SUBJECT_LIMIT = 100  # SNS rejects longer subjects


def split_findings(findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """Return (waste, review). Waste is certain; review needs a human's judgment."""
    waste = [f for f in findings if f.kind == KIND_WASTE]
    review = [f for f in findings if f.kind != KIND_WASTE]
    return waste, review


def _total(findings: list[Finding]) -> float:
    return sum(f.estimated_monthly_cost_usd for f in findings)


def _review_cost(review: list[Finding]) -> str:
    """Cost text for review items. An unknown price is never shown as $0."""
    known = [f for f in review if f.price_source != "unknown"]
    unknown = len(review) - len(known)
    if not known:
        return "cost unknown"
    text = f"up to ~${_total(known):.2f}/month"
    if unknown:
        text += f", plus {unknown} of unknown cost"
    return text


def summarize(findings: list[Finding]) -> str:
    """One-line summary that never mixes certain waste with 'please review' items."""
    waste, review = split_findings(findings)
    text = f"{len(waste)} waste finding(s), ~${_total(waste):.2f}/month"
    if review:
        text += f"; {len(review)} to review ({_review_cost(review)})"
    return text


def format_spend_section(rows) -> str:
    """Human-readable usage-by-service table. Shared by the CLI and the email report."""
    lines = ["Gross usage, last 30 days (credits and tax excluded):"]
    for row in rows:
        checks = (
            f"checks: {', '.join(row.scanners)}" if row.scanners else "no scanner yet"
        )
        lines.append(f"  {row.service:45} ${row.usd:>8.2f}  {checks}")

    unscanned = sum(row.usd for row in rows if not row.scanners)
    lines.append("")
    lines.append(f"${unscanned:.2f} of usage is in services with no scanner yet.")
    lines.append(
        "A scanner checks one waste pattern in a service; it does not explain "
        "all spending there."
    )
    return "\n".join(lines)


def _finding_lines(f: Finding) -> list[str]:
    if f.price_source == "unknown":
        cost = "cost unknown (no live price available)"
    else:
        cost = f"~${f.estimated_monthly_cost_usd:.2f}/month ({f.price_source} price)"
    lines = [
        f"- [{f.resource_type}] {f.resource_id} ({f.region})",
        f"    {f.reason}",
        f"    {cost}",
    ]
    if f.details:
        lines.append("    " + ", ".join(f"{k}={v}" for k, v in f.details.items()))
    return lines


def format_report(
    findings: list[Finding],
    errors: dict[str, str],
    regions: list[str],
    spend_rows=None,
    spend_error: str | None = None,
) -> tuple[str, str]:
    """Return (subject, body) for the notification."""
    waste, review = split_findings(findings)

    if waste and review:
        subject = (
            f"Cost Guardian: {len(waste)} finding(s), ~${_total(waste):.2f}/month; "
            f"{len(review)} to review"
        )
    elif waste:
        subject = f"Cost Guardian: {len(waste)} finding(s), ~${_total(waste):.2f}/month"
    elif review:
        subject = f"Cost Guardian: {len(review)} item(s) to review"
    elif errors or spend_error:
        subject = "Cost Guardian: scan finished with errors"
    else:
        subject = "Cost Guardian: all clear"

    lines = [
        "Cloud Cost Guardian report",
        f"Regions scanned: {', '.join(regions)}",
        "",
    ]

    if waste:
        lines.append(f"Findings ({len(waste)}, ~${_total(waste):.2f}/month):")
        for f in waste:
            lines.extend(_finding_lines(f))
    else:
        lines.append("No wasted resources found by the active scanners.")
    lines.append("")

    if review:
        lines.append(f"Worth reviewing ({len(review)}, {_review_cost(review)}):")
        lines.append(
            "These are heuristics that need your judgment; "
            "they are not necessarily waste."
        )
        for f in review:
            lines.extend(_finding_lines(f))
        lines.append("")

    if errors:
        lines.append("Scanners that could not run (their areas were NOT checked):")
        for name, error in errors.items():
            lines.append(f"- {name}: {error}")
        lines.append("")

    if spend_rows is not None:
        lines.append(format_spend_section(spend_rows))
        lines.append("")
    elif spend_error:
        lines.append(f"Could not read spend from Cost Explorer: {spend_error}")
        lines.append("")

    lines.append('Prices marked "estimated" are approximations, not quotes.')
    lines.append("This report is read-only: Guardian changed nothing in your account.")

    return subject[:SUBJECT_LIMIT], "\n".join(lines)
