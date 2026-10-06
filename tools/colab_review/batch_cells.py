"""Stable-ID cells for explicit spin-up / run / preserve / spin-down batches."""
CUDA_SMOKE = '''# Optional one-shot synthetic GPU smoke. Set True for this A100 batch.
RUN_CUDA_SMOKE = False
cuda_smoke={'status':'not run','scope':'synthetic numerical smoke, not game animation approval'}
(OUTPUT/'cuda-smoke.json').unlink(missing_ok=True)
if RUN_CUDA_SMOKE:
    import time, torch
    if not torch.cuda.is_available(): raise RuntimeError('CUDA unavailable; no GPU execution claimed')
    device=torch.cuda.get_device_name(0)
    if 'A100' not in device: raise RuntimeError('This batch requests A100; actual device is '+device)
    n=4096
    t=np.arange(n,dtype=np.float64)/240.0
    a=np.column_stack((np.sin(t)*.1,np.cos(t)*.1,t*.001))
    b=a+np.array([.001,-.002,.0005],dtype=np.float64)
    synthetic_bytes=a.tobytes()+b.tobytes()+t.tobytes()
    doc={'schema':'rust-duty-contact-samples/v1','units':'metres','space':'evaluated-world',
         'source_sha256':review.digest(synthetic_bytes),
         'pairs':[{'name':'synthetic points only','time_seconds':t.tolist(),
                   'a':a.tolist(),'b':b.tolist(),'observed':[True]*n}]}
    torch.cuda.synchronize(); started=time.perf_counter()
    checked=review.contact_report(doc,use_cuda=True)
    torch.cuda.synchronize()
    cuda_smoke={'status':'passed','scope':'synthetic numerical smoke, not game animation approval',
                'device':device,'torch':torch.__version__,'cuda_runtime':torch.version.cuda,
                'samples':n,'elapsed_seconds_including_cpu_check':time.perf_counter()-started,
                'cpu_parity_rtol':1e-9,'cpu_parity_atol':1e-10,'result':checked}
    (OUTPUT/'cuda-smoke.json').write_text(json.dumps(cuda_smoke,indent=2,allow_nan=False))
print(json.dumps(cuda_smoke,indent=2))
'''
TEARDOWN = '''# Run separately AFTER the completed download is saved outside this runtime.
# Re-upload that downloaded ZIP as byte-level preservation evidence.
CONFIRM_TEARDOWN = False
if not CONFIRM_TEARDOWN:
    print('Runtime retained. Save the results ZIP, then set CONFIRM_TEARDOWN=True and run this cell.')
else:
    if 'ARCHIVE_SHA256' not in globals() or 'EXPORTED_OUTPUT_HASHES' not in globals():
        raise RuntimeError('Export the current results first; runtime retained')
    from google.colab import files, runtime
    print('Select the downloaded results ZIP. No teardown on cancel, error or mismatch.')
    saved_copy=files.upload()
    if len(saved_copy)!=1: raise ValueError('Select exactly one saved results ZIP; runtime retained')
    preservation=review.verify_preserved_archive(archive,OUTPUT,next(iter(saved_copy.values())),
                                                ARCHIVE_SHA256,EXPORTED_OUTPUT_HASHES)
    print('Verified saved copy:',preservation)
    print('Requesting runtime unassignment now. Verify removal under Runtime > Manage sessions.')
    runtime.unassign()
'''
TEARDOWN_DOC = '''## Preserve, then release this batch runtime
This notebook runs one bounded batch. Connect the selected A100 only when ready; run the optional synthetic CUDA smoke before the export cell. No keepalive, idle loop, automatic reconnect or recurring GPU reservation.

The export cell initiates a browser download; it does **not** prove the ZIP reached durable storage. Wait for the browser's download to finish, retain that file outside Colab, then run the guarded final cell with `CONFIRM_TEARDOWN=True`. Select the downloaded ZIP when prompted. The cell verifies the exact ZIP bytes and checks that outputs have not changed since export before requesting `runtime.unassign()`. Cancellation, mismatches and errors retain the runtime so you can recover the output. Only files in this review's OUTPUT directory are covered; preserve any unrelated runtime work separately before confirming.

After unassignment, verify the notebook disconnects AND its entry disappears from **Runtime → Manage sessions**. Disconnection alone is not proof of resource release. If it remains, use **Runtime → Disconnect and delete runtime** after preserving output; do not reconnect to check. There is no billing-finality or immediate host-deletion guarantee from a cell, and Colab can independently terminate sessions.

Official sources: [runtime.unassign implementation](https://github.com/googlecolab/colabtools/blob/main/google/colab/runtime.py), [asynchronous files.download implementation](https://github.com/googlecolab/colabtools/blob/main/google/colab/files.py), [Colab FAQ](https://research.google.com/colaboratory/faq.html). No new Drive permission or external upload destination is needed. Locally tested guards are not a claim of A100 or actual Colab teardown execution.
'''
# Include the tested guard in this cell so it also works in the already-uploaded
# v1 notebook without replacing its large embedded-module cell.
from pathlib import Path
_guard_source=(Path(__file__).parent/'review.py').read_text().split('def verify_preserved_archive(',1)[1]
TEARDOWN='import io, zipfile\nfrom pathlib import Path\nfrom review import digest\ndef verify_preserved_archive('+_guard_source+'\n'+TEARDOWN.replace('review.verify_preserved_archive(', 'verify_preserved_archive(')
