# Periodic-core scope v3, with unresolved envelope retained

Declared before scoring the final clean-core candidate. This narrows the source interval only for evaluating the repeating loop. It does not erase or rescore the failed full-window v2 metrics. The user-directed architecture separates blend_in / loop / blend_out; Aella owns the nonperiodic direction/carry settling envelope.

All v2 thresholds, frozen geometry scales, cuff anchor, phase constraints, contact gates, and60-point motion-only rubric remain unchanged. Do not put an observed settling envelope into a repeated loop. Stop searching alternative cycles to obtain desired amplitudes.

## Frozen core ranges

Half-open unique frames, followed by an endpoint witness at the exclusive end:

- Forward, R2: [48,86), PTS[12288,22016), seconds[0.800000,1.433333),38frames
- Backward, R2: [211,256), PTS[54016,65536), seconds[3.516667,4.266667),45frames
- Left, R2: [886,935), PTS[226816,239360), seconds[14.766667,15.583333),49frames
- Right, R1: [361,410), PTS[92416,104960), seconds[6.016667,6.833333),49frames

Timebase1/15360; source60/1fps. These ranges contain no declared failed tracker samples. Right [388,437) was rejected because it includes unusable muzzle frames[418,429). The earlier right[375,424) candidate was superseded to avoid the same issue, not to hide its full-window failure.

## How to describe a result

A periodic-core score measures native-asset motion transfer against that exact observed authoring cycle. It is an in-sample fit/reference comparison with independently measured rendered/captured output, not a held-out generalization claim. Show each Action's score, support and comparable sample coverage, failed clauses and contact status. Never promote a periodic-core80% result into a full-window, mean-pose, whole-body or runtime pass.

Retain candidate_v04_motion_v2_metrics.json and the original pose-rubric result. Right's fully usable core has approximately8px muzzle-Y variation, compared with25px across the initial full R1 window. The discrepancy is settling/nonperiodic change and tracker uncertainty, not permission to enlarge every cycle. The R2 right[720,786) settling diagnostic also remains unfulfilled by a pure loop.

## Runtime handoff still required

Aella must compare the first-person envelope over the original primary/secondary windows and adjacent native transition brackets, fit blend_in/blend_out behavior to supported visible onset/settle timing, and verify30/60fps start/stop/reversal/ADS. Input-event onset is hidden, so do not equate video transition times with unknown button timestamps. Carry offsets and mean body/weapon proportions remain separate from recurring loop motion.

No runtime transitions, ADS walking results, or exported production selection are certified by this source-loop review.
