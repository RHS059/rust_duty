# Exact host-binding correction

Architecture observations are retained from the actual Windows environment, never guessed. Controller and Blender platform tuples are separately pinned; cross-role system/version/machine remain exact, while release is compared only within its role. The original failed result remains failed. Only environment retention, host-observation/provenance validation, dependency selection and source-only tests/metadata change. Existing process hash domains, source/math/grid/thresholds, addon profiles, denied overrides and private assets remain unchanged.

The retained command context environment hash is bound to a separately named controller_environment_sha256 field derived from the same actual environment dict as the unchanged adapter-domain hash. These hashes intentionally differ because the adapter canonical encoding includes a final newline. They must never be compared directly across domains.
