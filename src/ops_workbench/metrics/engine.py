"""DuckDB-backed metric aggregation with explicit availability states."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import TypeAlias

import duckdb

from ops_workbench.metrics.registry import MetricDefinition, MetricRegistry
from ops_workbench.models.canonical_schema import (
    DIMENSION_FIELDS,
    FACT_BUSINESS_DAILY_TABLE,
)
from ops_workbench.models.database import (
    DEFAULT_DATABASE_PATH,
    get_field_availability,
)

MetricValue: TypeAlias = int | Decimal
FilterValue: TypeAlias = str | Sequence[str]


class MetricStatus(StrEnum):
    """Availability state for a metric result."""

    AVAILABLE = "available"
    UNAVAILABLE_MISSING_FIELD = "unavailable_missing_field"
    UNAVAILABLE_DEPENDENCY = "unavailable_dependency"
    UNAVAILABLE_ZERO_DENOMINATOR = "unavailable_zero_denominator"
    UNAVAILABLE_NO_DATA = "unavailable_no_data"


@dataclass(frozen=True, slots=True)
class MetricResult:
    """A metric value together with its availability and calculation context."""

    metric_id: str
    name: str
    value: MetricValue | None
    status: MetricStatus
    format: str
    numerator_value: MetricValue | None = None
    denominator_value: MetricValue | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MetricGroupResult:
    """One dimension member and its structured metric result."""

    dimension: str
    dimension_value: str | None
    metric_id: str
    name: str
    value: MetricValue | None
    status: MetricStatus
    format: str
    numerator_value: MetricValue | None = None
    denominator_value: MetricValue | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class _AtomicAggregate:
    row_count: int
    non_null_count: int
    value: MetricValue | None


class MetricEngine:
    """Calculate registered metrics from the persisted canonical fact table."""

    def __init__(
        self,
        *,
        database_path: Path = DEFAULT_DATABASE_PATH,
        registry: MetricRegistry | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.registry = registry or MetricRegistry.from_yaml()

    def calculate_metric(
        self,
        metric_id: str,
        *,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        filters: Mapping[str, FilterValue] | None = None,
    ) -> MetricResult:
        """Calculate one metric over an optional date range and AND filters."""
        return self.calculate_metrics(
            (metric_id,),
            start_date=start_date,
            end_date=end_date,
            filters=filters,
        )[0]

    def calculate_metrics(
        self,
        metric_ids: Sequence[str],
        *,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        filters: Mapping[str, FilterValue] | None = None,
    ) -> tuple[MetricResult, ...]:
        """Calculate several metrics using one aggregate query."""
        requested = tuple(metric_ids)
        if not requested:
            return ()
        order = self.registry.dependency_order(requested)
        atomics = self._atomic_definitions(order)
        where_sql, parameters = self._build_where(
            start_date=start_date,
            end_date=end_date,
            filters=filters,
        )
        availability = self._load_availability()
        aggregates = self._query_aggregates(atomics, where_sql, parameters)
        calculated = self._calculate_order(order, aggregates, availability)
        return tuple(calculated[metric_id] for metric_id in requested)

    def calculate_metric_by_dimension(
        self,
        metric_id: str,
        dimension: str,
        *,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        filters: Mapping[str, FilterValue] | None = None,
    ) -> tuple[MetricGroupResult, ...]:
        """Calculate one metric for each member of a canonical dimension."""
        if dimension not in DIMENSION_FIELDS:
            raise ValueError(f"Invalid group-by dimension: {dimension}")
        grouped = self._calculate_metric_grouped(
            metric_id,
            (dimension,),
            start_date=start_date,
            end_date=end_date,
            filters=filters,
        )
        results: list[MetricGroupResult] = []
        for group_values, result in grouped:
            dimension_value = group_values[0]
            results.append(
                MetricGroupResult(
                    dimension=dimension,
                    dimension_value=dimension_value,
                    metric_id=result.metric_id,
                    name=result.name,
                    value=result.value,
                    status=result.status,
                    format=result.format,
                    numerator_value=result.numerator_value,
                    denominator_value=result.denominator_value,
                    reason=result.reason,
                )
            )
        return tuple(results)

    def _calculate_metric_grouped(
        self,
        metric_id: str,
        group_fields: tuple[str, ...],
        *,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        filters: Mapping[str, FilterValue] | None = None,
    ) -> tuple[tuple[tuple[object, ...], MetricResult], ...]:
        """Calculate one metric by one dimension or by date plus one dimension."""
        allowed_fields = {"date", *DIMENSION_FIELDS}
        if (
            not group_fields
            or len(group_fields) > 2
            or any(field not in allowed_fields for field in group_fields)
            or (len(group_fields) == 2 and group_fields[0] != "date")
        ):
            raise ValueError(f"Invalid metric grouping: {group_fields}")
        order = self.registry.dependency_order((metric_id,))
        atomics = self._atomic_definitions(order)
        where_sql, parameters = self._build_where(
            start_date=start_date,
            end_date=end_date,
            filters=filters,
        )
        availability = self._load_availability()
        grouped = self._query_grouped_aggregates(
            group_fields,
            atomics,
            where_sql,
            parameters,
        )
        return tuple(
            (
                group_values,
                self._calculate_order(order, aggregates, availability)[metric_id],
            )
            for group_values, aggregates in grouped
        )

    def _atomic_definitions(
        self,
        order: Sequence[str],
    ) -> tuple[MetricDefinition, ...]:
        return tuple(
            self.registry.get(metric_id)
            for metric_id in order
            if self.registry.get(metric_id).type == "atomic"
        )

    def _load_availability(self) -> dict[str, bool]:
        return {
            item.canonical_field: item.is_available
            for item in get_field_availability(database_path=self.database_path)
        }

    def _build_where(
        self,
        *,
        start_date: date | str | None,
        end_date: date | str | None,
        filters: Mapping[str, FilterValue] | None,
    ) -> tuple[str, list[object]]:
        clauses: list[str] = []
        parameters: list[object] = []
        if start_date is not None:
            clauses.append('"date" >= ?')
            parameters.append(start_date)
        if end_date is not None:
            clauses.append('"date" <= ?')
            parameters.append(end_date)
        for field, raw_value in (filters or {}).items():
            if field not in DIMENSION_FIELDS:
                raise ValueError(f"Invalid filter field: {field}")
            if isinstance(raw_value, str):
                clauses.append(f'"{field}" = ?')
                parameters.append(raw_value)
                continue
            if not isinstance(raw_value, Sequence):
                raise ValueError(f"Filter {field} must be a string or sequence of strings")
            values = tuple(raw_value)
            if not values or not all(isinstance(value, str) for value in values):
                raise ValueError(f"Filter {field} requires one or more string values")
            placeholders = ", ".join("?" for _ in values)
            clauses.append(f'"{field}" IN ({placeholders})')
            parameters.extend(values)
        if not clauses:
            return "", parameters
        return " WHERE " + " AND ".join(clauses), parameters

    def _aggregate_selects(
        self,
        atomics: Sequence[MetricDefinition],
    ) -> list[str]:
        selects = ['COUNT(*) AS "__row_count"']
        for definition in atomics:
            field = str(definition.field)
            selects.append(f'COUNT("{field}") AS "{definition.id}__count"')
            selects.append(f'SUM("{field}") AS "{definition.id}__sum"')
        return selects

    def _query_aggregates(
        self,
        atomics: Sequence[MetricDefinition],
        where_sql: str,
        parameters: Sequence[object],
    ) -> dict[str, _AtomicAggregate]:
        query = (
            "SELECT "
            + ", ".join(self._aggregate_selects(atomics))
            + f' FROM "{FACT_BUSINESS_DAILY_TABLE}"'
            + where_sql
        )
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            row = connection.execute(query, parameters).fetchone()
        if row is None:
            raise RuntimeError("Aggregate query returned no row")
        return self._unpack_aggregates(atomics, row)

    def _query_grouped_aggregates(
        self,
        group_fields: Sequence[str],
        atomics: Sequence[MetricDefinition],
        where_sql: str,
        parameters: Sequence[object],
    ) -> list[tuple[tuple[object, ...], dict[str, _AtomicAggregate]]]:
        group_sql = ", ".join(f'"{field}"' for field in group_fields)
        query = (
            f"SELECT {group_sql}, "
            + ", ".join(self._aggregate_selects(atomics))
            + f' FROM "{FACT_BUSINESS_DAILY_TABLE}"'
            + where_sql
            + f" GROUP BY {group_sql} ORDER BY {group_sql} NULLS LAST"
        )
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            rows = connection.execute(query, parameters).fetchall()
        group_count = len(group_fields)
        return [
            (
                tuple(row[:group_count]),
                self._unpack_aggregates(atomics, row[group_count:]),
            )
            for row in rows
        ]

    def _unpack_aggregates(
        self,
        atomics: Sequence[MetricDefinition],
        row: Sequence[object],
    ) -> dict[str, _AtomicAggregate]:
        row_count = int(row[0])
        return {
            definition.id: _AtomicAggregate(
                row_count=row_count,
                non_null_count=int(row[index * 2 + 1]),
                value=row[index * 2 + 2],
            )
            for index, definition in enumerate(atomics)
        }

    def _calculate_order(
        self,
        order: Sequence[str],
        aggregates: Mapping[str, _AtomicAggregate],
        availability: Mapping[str, bool],
    ) -> dict[str, MetricResult]:
        results: dict[str, MetricResult] = {}
        for metric_id in order:
            definition = self.registry.get(metric_id)
            if definition.type == "atomic":
                results[metric_id] = self._atomic_result(
                    definition,
                    aggregates[metric_id],
                    availability,
                )
            elif definition.type == "ratio":
                results[metric_id] = self._ratio_result(definition, results)
            else:
                results[metric_id] = self._difference_result(definition, results)
        return results

    def _atomic_result(
        self,
        definition: MetricDefinition,
        aggregate: _AtomicAggregate,
        availability: Mapping[str, bool],
    ) -> MetricResult:
        field = str(definition.field)
        if not availability.get(field, False):
            return self._unavailable(
                definition,
                MetricStatus.UNAVAILABLE_MISSING_FIELD,
                f"{field} is unavailable in current dataset",
            )
        if aggregate.row_count == 0 or aggregate.non_null_count == 0:
            return self._unavailable(
                definition,
                MetricStatus.UNAVAILABLE_NO_DATA,
                f"{field} has no data for the current selection",
            )
        return MetricResult(
            metric_id=definition.id,
            name=definition.name,
            value=aggregate.value,
            status=MetricStatus.AVAILABLE,
            format=definition.format,
        )

    def _ratio_result(
        self,
        definition: MetricDefinition,
        results: Mapping[str, MetricResult],
    ) -> MetricResult:
        numerator = results[str(definition.numerator)]
        denominator = results[str(definition.denominator)]
        unavailable = self._dependency_failure(definition, (numerator, denominator))
        if unavailable is not None:
            return unavailable
        if denominator.value == 0:
            return MetricResult(
                metric_id=definition.id,
                name=definition.name,
                value=None,
                status=MetricStatus.UNAVAILABLE_ZERO_DENOMINATOR,
                format=definition.format,
                numerator_value=numerator.value,
                denominator_value=denominator.value,
                reason=f"{definition.denominator} aggregates to zero",
            )
        value = Decimal(numerator.value) / Decimal(denominator.value)
        return MetricResult(
            metric_id=definition.id,
            name=definition.name,
            value=value,
            status=MetricStatus.AVAILABLE,
            format=definition.format,
            numerator_value=numerator.value,
            denominator_value=denominator.value,
        )

    def _difference_result(
        self,
        definition: MetricDefinition,
        results: Mapping[str, MetricResult],
    ) -> MetricResult:
        minuend = results[str(definition.minuend)]
        subtrahend = results[str(definition.subtrahend)]
        unavailable = self._dependency_failure(definition, (minuend, subtrahend))
        if unavailable is not None:
            return unavailable
        return MetricResult(
            metric_id=definition.id,
            name=definition.name,
            value=Decimal(minuend.value) - Decimal(subtrahend.value),
            status=MetricStatus.AVAILABLE,
            format=definition.format,
            numerator_value=minuend.value,
            denominator_value=subtrahend.value,
        )

    def _dependency_failure(
        self,
        definition: MetricDefinition,
        dependencies: Sequence[MetricResult],
    ) -> MetricResult | None:
        for dependency in dependencies:
            if dependency.status == MetricStatus.AVAILABLE:
                continue
            dependency_definition = self.registry.get(dependency.metric_id)
            status = (
                dependency.status
                if dependency_definition.type == "atomic"
                else MetricStatus.UNAVAILABLE_DEPENDENCY
            )
            return self._unavailable(
                definition,
                status,
                f"Dependency {dependency.metric_id} is unavailable: {dependency.status}",
            )
        return None

    @staticmethod
    def _unavailable(
        definition: MetricDefinition,
        status: MetricStatus,
        reason: str,
    ) -> MetricResult:
        return MetricResult(
            metric_id=definition.id,
            name=definition.name,
            value=None,
            status=status,
            format=definition.format,
            reason=reason,
        )
