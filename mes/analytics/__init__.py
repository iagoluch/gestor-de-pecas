"""Motores analíticos puros e reutilizáveis."""

from .physical_time import PhysicalInputSegment, consolidate_physical_time
from .oee import OEE_CONTRACT, OeeCalculation, calculate_oee, oee_seconds_by_category
from .rateio import allocate_duration
from .timeline import TimelineResult, TimelineSegment, build_operator_timeline

__all__ = [
    "PhysicalInputSegment",
    "OEE_CONTRACT",
    "OeeCalculation",
    "TimelineResult",
    "TimelineSegment",
    "allocate_duration",
    "consolidate_physical_time",
    "build_operator_timeline",
    "calculate_oee",
    "oee_seconds_by_category",
]
