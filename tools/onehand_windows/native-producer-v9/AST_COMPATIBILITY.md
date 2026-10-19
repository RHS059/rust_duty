# Exact compatibility boundary

The old package hashes ast.dump(ast.parse(fragment_source), include_attributes=False). Those stored hashes are CPython 3.12 representations. Official CPython 3.11.9 and 3.12.10 use byte-identical ast.dump function source (SHA256 4b95454fe77ff21364dde3f5ca99ec64c7123dab419e556809fc35aee74e11c7), but their AST schemas differ.

Sources:
- https://github.com/python/cpython/blob/v3.11.9/Parser/Python.asdl
- https://github.com/python/cpython/blob/v3.12.10/Parser/Python.asdl
- https://github.com/python/cpython/blob/v3.11.9/Lib/ast.py
- https://github.com/python/cpython/blob/v3.12.10/Lib/ast.py

All 73 kinds/ordered field layouts used by the frozen fragments were checked against both tagged ASDL sources. The only field-layout delta within this inventory is an appended type_params list on FunctionDef and ClassDef. There are 35 FunctionDef and 2 ClassDef nodes across 28 fragments. The other 6 fragments have no such nodes. AsyncFunctionDef and new type-alias/type-parameter syntax are outside the frozen grammar and are rejected.

GeometryBytes is the first frozen record, from onehand-runtime-20261016-r2/native-rigid-v2/rigid_bytes.py. Its source SHA256 is 619a04300ad81a963a691998ff3f09cc30f7fa8a01918c0c7ff5bcae4d858d9d and its unchanged original AST SHA256 is 80d957bc2dd8bd03ec9c7504da81355d105ba7b0ead9e9c558ddad9f81f3ee14. Removing only the three empty 3.12 fields produces the source-derived 3.11-schema hash 71c575fdf63bceb5a84269d99f8f8e96d2a11bce6b75ed74a6ea1017ea4e2a13, a 48-byte dump difference. That latter hash is a schema-projection observation, not an actual 3.11 parser result. The public failed receipt names the assertion, not the fragment; first-record identity is a deterministic source/schema inference.

The serializer accepts only CPython 3.11/3.12. It validates node identity, exact ordered fields, presence of all fields, absence of unexpected attributes and empty list-valued type_params. Only on 3.11 does it deep-copy the tree and append the known empty fields for serialization. It never removes a field or changes a body/value, and the original AST hash must still match. Existing source hashes and whole-original-file hashes remain mandatory. The unchanged Relocate class still permits only two obsolete search-path removals and one recipe identity replacement, with exact counts.

The unchanged AUDITED_FRAGMENTS.json SHA256 is 3a2d0c7ea5fcc0dfab7ec615dbb78e0b7d9f907c1d1a48bc2f90da14933952b5. No source/AST pins have been recalculated to bless a changed function. The interpreter gate rejects 3.13 and other versions rather than guessing at their serializer behavior.

The broader read-only audit found a second set of 31 AST hashes in runtime-consumer pinned_math.py. They are evaluated only by the already pinned CPython 3.12 controller; no native 3.11 support is added there. Addon source inspection uses exact raw-file and universal-newline inspect domains separately; live code objects are compared only against code compiled by that same interpreter. Canonical JSON sites retain their existing key/order/separator/NaN and newline domains. No changes to those contracts are made by this producer repair.

Required next evidence: source-only regression receipts from actual CPython 3.11.9 and 3.12.10, produced before installing/opening Blender. An actual native candidate must still pass all unchanged process, host, source, math and game proof gates afterward.
