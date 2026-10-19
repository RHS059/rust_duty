"""Exact v2 integrity interface. Native execution additionally requires review.

The correction review is pinned; actual Windows smoke and native input/host
admission remain required. There is no allow/skip/fixture production option.
"""
import ast,json
from pathlib import Path
from pinned_code import file_sha,isolated_module,require
TRANSPORT_PINS_SHA='d9ef5486cbd7d80ec8d4c9d37c556ff7d13d8dc0147cbd7e6244a4154ca79751'
TRANSPORT_SHA='256125ea044c738ac316da841a5acad9c39b1fc2b1666cc4a09ce81828bd191e'
SMOKE_AUDIT_SHA='0a10a58145fb2d6d9348ecc8a61d0ad2f8f318e7f644a9b46ce9716d386d6b17'
SMOKE_SUMMARY_SHA='b14b01a539920f34eec064a1bec1ec2799840c31e89a36e841831a3960c90fa2'
WINDOWS_JOB_SHA='d628c4f7d3136dde11cf6c9d5ba35f3d12302bfd2522918fe1f0229a40f1ba1e'
# Source correction acceptance only. Actual Windows smoke is a separate input.
REVIEW_ACCEPTANCE_SHA='820c10f716aadfb3ee9f7e3e3c8e176b446df0568f4196dce4fd0b7c08cf6527'

def verify_transport(ctx, *, production):
    root=ctx.root('process_adapter');deps=ctx.raw['dependencies']
    require(deps['transport_pins_sha256']==TRANSPORT_PINS_SHA and file_sha(root/'PINS.json')==TRANSPORT_PINS_SHA,'exact frozen v2 transport required')
    pins=ctx.cc.strict_json(root/'PINS.json')
    for name,record in pins['files'].items():
        require(Path(name).name==name and file_sha(root/name)==record['sha256'],'v2 transport closure differs: '+name)
    require(file_sha(root/'owned_process.py')==TRANSPORT_SHA and file_sha(root/'windows_job.py')==WINDOWS_JOB_SHA,'v2 reviewed code differs')
    if production:
        require(deps['transport_review_sha256']==REVIEW_ACCEPTANCE_SHA and ctx.pin('transport_review').sha256==REVIEW_ACCEPTANCE_SHA,'transport review pin differs')
        review=ctx.cc.strict_json(ctx.pin('transport_review').verify())
        require(review['source_pins_sha256']==TRANSPORT_PINS_SHA and review['blocking_findings']==[],'source correction review differs')
        require(ctx.pin('transport_smoke').sha256==SMOKE_AUDIT_SHA and ctx.pin('transport_smoke_summary').sha256==SMOKE_SUMMARY_SHA,'exact independently audited Windows smoke inputs required')
        smoke=ctx.cc.strict_json(ctx.pin('transport_smoke').verify())
        summary=ctx.cc.strict_json(ctx.pin('transport_smoke_summary').verify())
        for key,expected in {'schema':'windows-owned-process-independent-audit/v1','passed':True,'scope':'actual Windows Python process transport only',
                             'animation_proof':False,'run_id':38871908839,'merge_sha':'990a27ede8a793bdf534bacd5271a62d84c9beaa',
                             'summary_sha256':SMOKE_SUMMARY_SHA,'adapter_pins_sha256':TRANSPORT_PINS_SHA,
                             'adapter_build_sha256':'8f0df884fc16cf3299db83c5f32477c28b624607ff8b60c4473892ababf241b2',
                             'tests_run':78,'posix_only_skipped':2,'native_windows_test_count':4}.items():
            ctx.cc.exact(smoke.get(key),expected,'actual Windows smoke audit '+key)
        skips=[{'test':'test_owned_process.TransportTests.test_own_descendant_cleanup_foreign_process_survives','reason':'Linux process-group cleanup test'},
               {'test':'test_owned_process.TransportTests.test_signal_exit','reason':'POSIX signal exit test'}]
        for key,expected in {'schema':'rust-duty-owned-process-tests/v1','tests_run':78,'failures':0,'errors':0,'skipped':skips,
                             'all_executed_tests_passed':True,'actual_windows_transport_smoke_passed':True,
                             'actual_windows_animation_proof':False,'blender_game_or_assets_executed':False,
                             'source_revision':smoke['merge_sha'],'native_windows_tests_defined':4,'pins_verified':True}.items():
            ctx.cc.exact(summary.get(key),expected,'actual Windows smoke '+key)
        require(summary['host']=='Windows-2022Server-10.0.20348-SP0','actual Windows summary host required')
    # Keep helper imports private, including the delayed Windows resource import.
    job=isolated_module('windows_job',root/'windows_job.py',{})
    return isolated_module('owned_process',root/'owned_process.py',{'windows_job':job})
