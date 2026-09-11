# YSB merchant mapping status

Crosswalk size: 118 merchant keys. ID_MATCHED=27; NAME_MATCHED=85; UNRESOLVED=6. Mapping success rate=94.92%.

The recent monthly table has 91 normalized names. 85 match a unique supplier ID in the historical GMV table; 6 do not. The historical GMV table has 112 IDs; 27 do not match a recent monthly name. These differences are retained as coverage differences, name/ID change candidates, or unresolved cases; no forced merge is performed.

## Mapping rules

`ID:<supplier_id>` is used when a unique ID is available; otherwise `NAME:<normalized_supplier_name>` is used for staging only and remains `UNRESOLVED`.

## Difference classification

- 6 recent-only names: `UNRESOLVED`; evidence is insufficient to distinguish new merchant, rename, ID change, or source coverage gap.
- 27 historical-only IDs: `ID_MATCHED` as identifiers but absent from the recent monthly source; evidence is insufficient to distinguish lost/退出 merchant from coverage filtering or source omission.
