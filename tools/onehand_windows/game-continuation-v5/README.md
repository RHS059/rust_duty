# Windows game continuation v5: Windows profile dependency successor

Preparation only. The exact PR77 baseline is game-continuation-v4 at commit
01e3d821d197799a342b7738b84e835b11197f24. All package bytes are independently
pinned; dependency changes are limited to the reviewed source successor chain.

The only production changes are the exact orchestration-v7 package pin and the
versioned game-continuation-v5 preflight prefix. The transport test dependency
follows producer-v5. All 65 original continuation test methods and all 11 real
adapter transport test methods remain byte-identical. Game, audio, build,
source-selection, math, DX12 and process/resource logic are unchanged.

The exact features remain audio,legacy-macroquad,wgpu-runtime. Full source,
vendor, compiler/linker/SDK provenance, both context/environment hash domains,
same-candidate 4240/67/12/offkey proof, 30/60 Hz native-window DX12 capture and
capture-before-delivery gates remain mandatory. No test result is Windows or
animation evidence. No native execution, rendering, downloads, installations,
CI, publication or private-asset work is performed here.

The admission template is disabled with null source revision, source spec and
independent review. It is not acceptance. Public defaults remain inactive.
Source-only files target tools/onehand_windows/game-continuation-v5/. An exact
reviewed workflow and fresh independent admission remain separate requirements.
