# Actual CPU Colab batch

Completed 2026-10-04 with actual Jump r7 source/native receiver-point data;
`synthetic=false`, `score=null`. Result ZIP was saved, SHA256 and ZIP CRC checked,
then the runtime deleted. Parent observed Manage sessions with no active sessions
at 19:30:45UTC. No GPU was allocated for this batch.

`jump-r7-colab-report.json` is the unmodified JSON from the preserved Colab ZIP.
`executed_compare.py` preserves the exact embedded source that ran, SHA256
`14a1f523709ea6f4221508e2138df1764c1cf91a4f880178b38cb325fbfd993c`.
The current reusable module adds only report metadata and removes empty legends.
All numerical fields and exact input hashes match the local run: aggregate,
landmark traces/coverage, events, axis, native joins, unsupported findings and
registration. Video-byte verification remains false in the JSON-only Colab run;
the separate local run supplied and verified the original source/archive bytes.

The public summary retains uncertainty and unsupported evidence. A 4.85 px landing/
recovery baseline RMS for one receiver corner is useful diagnostic feedback;
it does not establish a full-weapon match or an 80% score. No account notebook,
authentication context, private model, source video, or native model PNG is included.

Current tooling validation: 40 tests pass; synthetic CPU notebook smoke also passes.
The actual real-data Colab result is separately preserved here. Prior independent
Elara Jump r6=78 remains unchanged; r7 remains unscored.
