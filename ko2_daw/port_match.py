"""Robust MIDI port matching for EP-133 / KO II devices."""

from __future__ import annotations

import re
from collections.abc import Iterable


KO2_TEXT_TOKENS = (
    "ep 133",
    "ep133",
    "ko ii",
    "k o ii",
    "koii",
    "ko2",
    "k o 2",
    "teenage engineering",
    "teenage eng",
)


def normalize_port_name(port_name: str) -> str:
    """Normalize a MIDI port name for fuzzy device matching."""

    lowered = str(port_name or "").casefold()
    lowered = lowered.replace("k.o.", "k o ")
    lowered = lowered.replace("k.o", "k o")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def compact_port_name(port_name: str) -> str:
    """Return a punctuation-free compact form used for EP133/KOII matching."""

    return normalize_port_name(port_name).replace(" ", "")


def looks_like_ko2_port(port_name: str) -> bool:
    """Return True if a visible MIDI port is likely the EP-133 / KO II."""

    normalized = normalize_port_name(port_name)
    compact = compact_port_name(port_name)
    if not normalized:
        return False
    if any(token in normalized for token in KO2_TEXT_TOKENS):
        return True
    if any(token in compact for token in ("ep133", "koii", "ko2", "ep1320")):
        return True
    if "teenage" in normalized and any(token in compact for token in ("ep", "ko", "midi")):
        return True
    return False


def unique_ports(ports: Iterable[str]) -> list[str]:
    """Return ports without duplicates while preserving order."""

    seen: set[str] = set()
    result: list[str] = []
    for port in ports:
        if port in seen:
            continue
        seen.add(port)
        result.append(port)
    return result


def collect_ko2_ports(
    input_ports: Iterable[str],
    output_ports: Iterable[str],
    reported_ports: Iterable[str] | None = None,
) -> list[str]:
    """Collect likely KO II ports from all known report sources."""

    reported = list(reported_ports or [])
    detected = [port for port in [*input_ports, *output_ports] if looks_like_ko2_port(port)]
    return unique_ports([*reported, *detected])


def select_ko2_output(output_ports: Iterable[str], candidates: Iterable[str] | None = None) -> str | None:
    """Select the best visible KO II output port."""

    outputs = list(output_ports)
    for candidate in candidates or []:
        if candidate in outputs:
            return candidate
    return next((port for port in outputs if looks_like_ko2_port(port)), None)


def select_ko2_input(input_ports: Iterable[str], candidates: Iterable[str] | None = None) -> str | None:
    """Select the best visible KO II input port."""

    inputs = list(input_ports)
    for candidate in candidates or []:
        if candidate in inputs:
            return candidate
    return next((port for port in inputs if looks_like_ko2_port(port)), None)


def enrich_midi_report(report: dict[str, object]) -> dict[str, object]:
    """Return a report with robustly recomputed KO II MIDI candidates."""

    enriched = dict(report)
    inputs = list(enriched.get("input_ports") or [])
    outputs = list(enriched.get("output_ports") or [])
    candidates = collect_ko2_ports(inputs, outputs, enriched.get("ko2_midi_ports") or [])
    enriched["ko2_midi_ports"] = candidates
    enriched["ko2_midi_ready"] = bool(select_ko2_output(outputs, candidates))
    if candidates and "hints" in enriched:
        enriched["hints"] = [
            hint
            for hint in list(enriched.get("hints") or [])
            if "No visible port name looks like KO II" not in str(hint)
        ]
    return enriched
