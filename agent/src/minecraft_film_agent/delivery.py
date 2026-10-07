"""Assemble only accepted exports, retaining their exact master provenance."""
import hashlib
import json
from pathlib import Path

from .edit import EditPlanError, execute_edit, load_edit_list
from .locking import RunLease, write_json
from .photography import file_hash


def assemble_delivery(edit: dict, *, workspace: Path, instance: Path,
                      exports: list[dict], evidence_dir: Path,
                      ffmpeg: Path, ffprobe: Path) -> dict:
    workspace=workspace.resolve(); instance=instance.resolve(); evidence_dir=evidence_dir.resolve()
    edit=load_edit_list(edit)
    if not evidence_dir.is_relative_to(workspace/'work'):
        raise EditPlanError('delivery evidence escapes workspace work/')
    by_path={}
    for export in exports:
        video=(workspace/export['output']).resolve()
        master=(instance/'replays'/f"{export['master_id']}.mcpr").resolve()
        if not video.is_relative_to(workspace/'assets/renders') or not master.is_relative_to(instance/'replays'):
            raise EditPlanError('export provenance path escapes ownership')
        if file_hash(video)!=export['output_hash'] or file_hash(master)!=export['master_hash']:
            raise EditPlanError('accepted export or its master changed')
        if video in by_path: raise EditPlanError('duplicate export proof')
        by_path[video]=export
    for clip in edit['video_clips']:
        source=(workspace/clip['source']).resolve()
        if source not in by_path: raise EditPlanError('edit references a video without accepted export proof')
    identity=hashlib.sha256(json.dumps({'edit':edit,'exports':exports},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    evidence_dir.parent.mkdir(parents=True,exist_ok=True)
    with RunLease(evidence_dir.with_name(evidence_dir.name+'.delivery.lease')):
        manifest=evidence_dir/'edit.json'
        if manifest.exists():
            prior=json.loads(manifest.read_text(encoding='utf-8'))
            if prior.get('status')!='succeeded' or prior.get('delivery_input_hash')!=identity:
                raise EditPlanError('delivery remains unresolved or its input identity changed')
            if file_hash(Path(prior['output']))!=prior['output_hash']:
                raise EditPlanError('published delivery changed')
            if any(file_hash(Path(path))!=digest for path,digest in prior['inputs'].items()):
                raise EditPlanError('accepted delivery inputs changed')
            return prior
        result=execute_edit(edit,workspace=workspace,evidence_dir=evidence_dir,ffmpeg=ffmpeg,ffprobe=ffprobe)
        result['delivery_input_hash']=identity
        result['export_proofs']=exports
        # The retained provenance is checked again after the edit, before calling
        # the delivery accepted. Any mutation leaves an explicit failed verdict.
        for export in exports:
            video=(workspace/export['output']).resolve()
            master=(instance/'replays'/f"{export['master_id']}.mcpr").resolve()
            if file_hash(video)!=export['output_hash'] or file_hash(master)!=export['master_hash']:
                result['status']='failed';result['error']='source/master changed during delivery'
                write_json(manifest,result)
                raise EditPlanError(result['error'])
        write_json(manifest,result)
        return result
