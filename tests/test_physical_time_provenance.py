"""Proveniência do consolidado de tempo físico: origem e regra aplicada.

Os campos novos (`source_refs`, `rule`) são só explicação; totais, chaves e
ordem do resultado de `consolidate_physical_time` não podem mudar.
"""

from datetime import datetime, timedelta

from mes.analytics.physical_time import PhysicalInputSegment, consolidate_physical_time
from mes.domain import EventCategory, StopClassification

T0 = datetime(2026, 10, 1, 8, 0, 0)


def _seg(category, start_min, end_min, ref, classification=None, resource="LASER1"):
    return PhysicalInputSegment(
        resource=resource,
        sector="Corte",
        category=category,
        start=T0 + timedelta(minutes=start_min),
        end=T0 + timedelta(minutes=end_min),
        source_ref=ref,
        stop_classification=classification,
    )


def test_single_source_keeps_ref():
    result = consolidate_physical_time(
        [_seg(EventCategory.NO_DEMAND, 0, 60, "estado_recurso:7")]
    )
    (segment,) = result["segments"]
    assert segment.source_refs == ("estado_recurso:7",)
    assert segment.rule is None
    assert result["totals"] == {EventCategory.NO_DEMAND: 3600.0}


def test_production_prevails_records_rule():
    result = consolidate_physical_time([
        _seg(EventCategory.PRODUCTION, 0, 60, "estado_recurso:1"),
        _seg(EventCategory.DOWNTIME, 0, 60, "estado_recurso:2"),
    ])
    (segment,) = result["segments"]
    assert segment.category is EventCategory.PRODUCTION
    assert segment.source_refs == ("estado_recurso:1", "estado_recurso:2")
    assert segment.rule == "production_prevailed"
    assert result["totals"] == {EventCategory.PRODUCTION: 3600.0}


def test_state_conflict_records_rule():
    result = consolidate_physical_time([
        _seg(EventCategory.DOWNTIME, 0, 60, "estado_recurso:3"),
        _seg(EventCategory.NO_DEMAND, 0, 60, "estado_recurso:4"),
    ])
    (segment,) = result["segments"]
    assert segment.category is EventCategory.UNKNOWN
    assert segment.state_conflict is True
    assert segment.rule == "state_conflict"
    assert segment.source_refs == ("estado_recurso:3", "estado_recurso:4")
    assert result["totals"] == {EventCategory.UNKNOWN: 3600.0}


def test_divergent_stop_classification_records_rule():
    result = consolidate_physical_time([
        _seg(EventCategory.DOWNTIME, 0, 60, "estado_recurso:5", StopClassification.PLANNED),
        _seg(EventCategory.DOWNTIME, 0, 60, "estado_recurso:6", StopClassification.UNPLANNED),
    ])
    (segment,) = result["segments"]
    assert segment.category is EventCategory.DOWNTIME
    assert segment.stop_classification is StopClassification.UNPLANNED
    assert segment.rule == "reclassified_to_unplanned"
    assert segment.source_refs == ("estado_recurso:5", "estado_recurso:6")
    assert result["totals"] == {EventCategory.DOWNTIME: 3600.0}
    assert result["totals_by_stop_classification"] == {
        EventCategory.DOWNTIME: {StopClassification.UNPLANNED: 3600.0}
    }


def test_agreeing_sources_have_refs_but_no_rule():
    result = consolidate_physical_time([
        _seg(EventCategory.PRODUCTION, 0, 60, "estado_recurso:8"),
        _seg(EventCategory.PRODUCTION, 30, 90, "estado_recurso:9"),
    ])
    refs = [(s.source_refs, s.rule) for s in result["segments"]]
    assert refs == [
        (("estado_recurso:8",), None),
        (("estado_recurso:8", "estado_recurso:9"), None),
        (("estado_recurso:9",), None),
    ]
    assert result["physical_seconds"] == 5400.0
    assert result["overlap_seconds"] == 1800.0


def test_missing_source_ref_is_omitted():
    result = consolidate_physical_time([
        _seg(EventCategory.QUEUE, 0, 60, None),
    ])
    (segment,) = result["segments"]
    assert segment.source_refs == ()
