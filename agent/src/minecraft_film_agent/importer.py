"""Sponge block import through typed keep-writes, with complete readback proof."""
import json
import re
from pathlib import Path
from .assets import verify_asset
from .locking import RunLease, write_json
from .photography import ReplayPhotography, file_hash
from .production_models import GameStateV2
from .schematic import load_schematic

AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}


class ImportError(RuntimeError):
    pass


def import_schematic(*, workspace: Path, client, asset_id: str, run_id: str,
                     world: str, player: str, origin: tuple[int,int,int],
                     build_region: dict, evidence_dir: Path, data_version: int, preserve_state: bool = False) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}",run_id) or run_id in (".",".."):
        raise ImportError("invalid run id")
    if data_version != 3955: raise ImportError("pinned Minecraft 1.21.1 requires DataVersion 3955")
    workspace=workspace.resolve(); evidence_dir=evidence_dir.resolve()
    if not evidence_dir.is_relative_to(workspace/"work"):
        raise ImportError("import evidence must stay inside workspace work/")
    record=verify_asset(workspace,asset_id)
    if record["kind"]!="schematic": raise ImportError("asset is not a schematic")
    if record["import_method"]!="bridge-keep": raise ImportError("asset import_method must explicitly select bridge-keep")
    source=workspace/record["target"]["path"]; digest=file_hash(source)
    data=load_schematic(source); summary=data.summary
    if summary.data_version!=data_version or record.get("data_version")!=data_version:
        raise ImportError("DataVersion mismatch; explicit conversion is required")
    if record.get("dependencies"):
        raise ImportError("dependency-bearing assets require explicit compatibility verification")
    if summary.block_entities or summary.entities or summary.has_biomes:
        raise ImportError("block entities, entities and biome imports are unsupported; no writes made")
    if summary.block_count>4096: raise ImportError("bridge import limit is 4096 non-air blocks")
    if len(origin)!=3 or any(type(v) is not int for v in origin): raise ImportError("invalid origin")
    bounds=[]
    for axis in ("x","y","z"):
        a,b=build_region["start"][axis],build_region["end"][axis]
        if type(a) is not int or type(b) is not int: raise ImportError("invalid region bounds")
        bounds.append((min(a,b),max(a,b)))
    if __import__('math').prod(b-a+1 for a,b in bounds)>262144: raise ImportError("region too large")
    photo=ReplayPhotography(client,run_id,timeout=30)
    def ready():
        result=photo.require("preflight","bridge.get_game_state",{}).result
        state=GameStateV2.model_validate(result)
        reason=state.pre_write_gate(expected_save=world,expected_dimension="minecraft:overworld",expected_player=player)
        if reason: raise ImportError(reason)
    versions=photo.require("versions","bridge.get_runtime_versions",{}).result
    if versions.get("minecraft")!="1.21.1": raise ImportError("pinned Minecraft runtime mismatch")
    ready()
    for axis, size, offset, (lo,hi) in zip(origin,(summary.width,summary.height,summary.length),summary.offset,bounds):
        if axis+offset<lo or axis+offset+size-1>hi: raise ImportError("schematic volume escapes declared build_region")
    canonical={}
    for i,block in enumerate(summary.palette):
        response=photo.require(f"palette-{i}","world.get_block",{"x":origin[0],"y":origin[1],"z":origin[2],"validate_block":block}).result
        if response.get("block_state_valid") is not True: raise ImportError(f"unknown or invalid block state: {block}")
        canonical[block]=response["canonical_state"]
    cells=[]
    for index,state in enumerate(data.states):
        if state.split("[",1)[0] in AIR: continue
        x=index%summary.width; z=(index//summary.width)%summary.length; y=index//(summary.width*summary.length)
        point=[origin[0]+summary.offset[0]+x,origin[1]+summary.offset[1]+y,origin[2]+summary.offset[2]+z]
        if not (-30000000<=point[0]<=30000000 and -64<=point[1]<=319 and -30000000<=point[2]<=30000000):
            raise ImportError("schematic escapes world bounds")
        if not all(a<=v<=b for v,(a,b) in zip(point,bounds)): raise ImportError("schematic escapes declared build_region")
        cells.append({"x":point[0],"y":point[1],"z":point[2],"block":state,"expected_state":canonical[state]})
    identity={"asset_id":asset_id,"source_hash":digest,"run_id":run_id,"world":world,"player":player,"origin":list(origin),"build_region":build_region,"cells":cells,"method":"bridge-keep"}
    if preserve_state: identity["preserve_state"]=True
    evidence_dir.mkdir(parents=True,exist_ok=True); manifest=evidence_dir/"import.json"
    with RunLease(evidence_dir/"import.lease"):
        if manifest.exists():
            report=json.loads(manifest.read_text(encoding="utf-8"))
            if report["identity"]!=identity: raise ImportError("import identity changed")
        else:
            report={"identity":identity,"summary":summary.model_dump(mode="json"),"status":"preflight","operations":{}}
            write_json(manifest,report)
        try:
            # Verify the entire target before the first mutation; existing blocks
            # may be accepted only with this run's persisted succeeded proof.
            for i,cell in enumerate(cells):
                observed=photo.require(f"target-{i}","world.get_block",{k:cell[k] for k in ("x","y","z")}).result
                prior=report["operations"].get(str(i))
                if prior and prior["status"]!="succeeded": raise ImportError("unresolved import write; no automatic replay")
                expected=cell["expected_state"] if prior else None
                if expected is None and observed["block"] not in AIR: raise ImportError(f"target cell {i} is occupied; no import writes made")
                if expected is not None and observed.get("block_state")!=expected: raise ImportError("previously imported state drifted")
            report["status"]="running";write_json(manifest,report)
            i=0
            while i<len(cells):
                cell=cells[i]
                if str(i) in report["operations"]:
                    i+=1; continue
                end=i+1
                if preserve_state and '[' not in cell['block']:
                    while end<len(cells):
                        previous,next_cell=cells[end-1],cells[end]
                        if str(end) in report['operations'] or next_cell['block']!=cell['block'] or next_cell['y']!=cell['y'] or next_cell['z']!=cell['z'] or next_cell['x']!=previous['x']+1:break
                        end+=1
                if end-i<3:end=i+1
                ready()
                if file_hash(source)!=digest: raise ImportError("source changed before write")
                key=f"{run_id}/block-{i}"
                for index in range(i,end):report["operations"][str(index)]={"status":"running","key":key}
                write_json(manifest,report)
                params={**{k:cell[k] for k in ("x","y","z","block")},"build_region":build_region}
                if preserve_state: params["preserve_state"]=True
                method='world.set_block_keep'
                if end>i+1:
                    method='world.fill_keep';params={'start':{k:cell[k] for k in ('x','y','z')},'end':{k:cells[end-1][k] for k in ('x','y','z')},'block':cell['block'],'build_region':build_region,'preserve_state':True}
                submitted=photo.call(f"block-{i}",method,params)
                terminal=client.await_world_op_v3(run_id,key,submitted,timeout_seconds=30,poll_interval_seconds=.05)
                for index in range(i,end):report["operations"][str(index)]={"status":terminal.status,"key":key,"response":terminal.model_dump(mode="json")}
                write_json(manifest,report)
                if terminal.status!="succeeded": raise ImportError(f"block write {i} is {terminal.status}")
                i=end
            for i,cell in enumerate(cells):
                actual=photo.require(f"verify-{i}","world.get_block",{k:cell[k] for k in ("x","y","z")}).result
                if actual.get("block_state")!=cell["expected_state"]: raise ImportError(f"final state mismatch at block {i}")
            verify_asset(workspace,asset_id)
            report["status"]="succeeded";report["verified_blocks"]=len(cells);write_json(manifest,report)
        except BaseException as error:
            report["status"]="blocked";report["error"]=str(error);write_json(manifest,report);raise
    return report
