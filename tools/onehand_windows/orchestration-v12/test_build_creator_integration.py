"""CPU-only cross-package contract test; no native tool or private asset input."""
import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
import build_rust
import workflow_core as w

class CreatorConsumerContract(unittest.TestCase):
    def test_created_report_is_accepted_by_frozen_consumer(self):
        parent=w.HERE.parent
        consumer_root=parent/'windows-runtime-consumer-v10'
        context_root=parent/'windows-context-preparation-v3'
        if not consumer_root.is_dir():consumer_root=parent/'runtime-consumer-reviewed';context_root=parent/'context-v3'
        self.assertTrue(consumer_root.is_dir() and context_root.is_dir(),'actual source dependency packages required for interface test')
        cc=w.module('candidate_context',context_root/'candidate_context.py',{})
        c=w.modules(consumer_root,('pinned_math','build_closure','runtime_context'))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';target=root/'target';candidate=root/'candidate'
            for p in (source,target,candidate):p.mkdir()
            (source/'Cargo.toml').write_bytes(b'synthetic only');crate=source/'main.rs';crate.write_bytes(b'synthetic only');sampler=target/'sample.exe';sampler.write_bytes(b'not a native executable')
            generated=target/'build'/'pkg'/'out'/'generated.rs';generated.parent.mkdir(parents=True);generated.write_bytes(b'synthetic compiler include')
            empty=target/'build'/'unused'/'out';empty.mkdir(parents=True)
            meta={'packages':[{'id':'pkg','manifest_path':str(source/'Cargo.toml'),'targets':[{'name':'sample','kind':['example'],'src_path':str(crate)}]}],'resolve':{'nodes':[{'id':'pkg','dependencies':[]}]}}
            artifact={'reason':'compiler-artifact','package_id':'pkg','target':meta['packages'][0]['targets'][0],'filenames':[str(sampler)],'executable':str(sampler)}
            events=[artifact,{'reason':'build-script-executed','out_dir':str(generated.parent)},{'reason':'build-script-executed','out_dir':str(empty)},{'reason':'build-finished','success':True}]
            messages=candidate/'cargo.jsonl';messages.write_text(''.join(json.dumps(v)+'\n' for v in events))
            process=candidate/'process.json';w.write_new(process,{'stdout':w.record(messages)})
            dep=target/'sample.d';dep.write_text('out: '+str(crate)+' '+str(generated)+'\n')
            source_files=w.inventory(source);build={'command':['synthetic cargo only'],'source_tree_sha256':w.digest(source_files),'dependency_closure':{'synthetic':True},'sampler':w.record(sampler),'build_process':w.record(process)}
            report=build_rust.compiler_report(build,w.record(process),events,target,source,c.build_closure.dep_info_paths,candidate)
            path=candidate/'compiler-inputs.json';w.write_new(path,report);build['compiler_inputs']=w.record(path)
            ctx=SimpleNamespace(cc=cc,candidate_root=candidate,root=lambda role:source)
            self.assertEqual(c.build_closure.verify(ctx,build,[(source,source_files)],meta,target),report)
            self.assertEqual(len(list((candidate/'build').glob('generated-*.json'))),1)
            generated.write_bytes(b'changed after build')
            with self.assertRaises(ValueError):c.build_closure.verify(ctx,build,[(source,source_files)],meta,target)

if __name__=='__main__':unittest.main()
