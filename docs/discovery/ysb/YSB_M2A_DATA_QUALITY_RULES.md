# YSB M2A data quality rules

- `VALID`: current metric value exists and the merchant mapping is resolved.
- `MISSING`: current metric is NULL for the merchant-month.
- `INSUFFICIENT_HISTORY`: current value exists but the prior period required for a change is absent or invalid.
- `UNRESOLVED_MERCHANT`: staging merchant key is a name fallback without a verified ID mapping; cross-period changes are not calculated.
- `UNAVAILABLE_FOR_PERIOD`: reserved for a metric that is not supplied for the selected source period; it is not treated as zero.

Rules:

1. `month + merchant_key` must be unique.
2. NULL remains NULL; only explicit source zero remains 0.
3. MoM requires valid current and prior values; first observed month has no synthetic MoM.
4. Unresolved merchants remain in the mart but do not generate trend signals.
5. Coverage gaps are `DATA_QUALITY_ALERT`, never `BUSINESS_ALERT` by themselves.
6. Quality states must be visible beside every metric used for diagnosis.
