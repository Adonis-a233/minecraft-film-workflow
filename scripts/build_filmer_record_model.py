"""Local filming grip: turn just the phone to expose rear lens away from forearm."""
import argparse
import copy
import json
import zipfile
from pathlib import Path
from minecraft_film_agent.photography import file_hash


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--source-pack',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(args.source_pack) as source:
        original=json.loads(source.read('assets/kanjian2/models/actor/filmer/forearm_l_phone.json'))
        model=copy.deepcopy(original)
        for element in model['elements'][3:]:
            # Phone Y(pi) about its own center, while the arm/hand are untouched.
            lo,hi=element['from'][:],element['to'][:]
            for axis,center in ((0,8),(2,5.25)):
                element['from'][axis]=2*center-hi[axis];element['to'][axis]=2*center-lo[axis]
            faces=element['faces'];element['faces']={dict(north='south',south='north',east='west',west='east').get(k,k):v for k,v in faces.items()}
            for key in ('up','down'):element['faces'][key]['rotation']=(element['faces'][key].get('rotation',0)+180)%360
        assert model['elements'][:3]==original['elements'][:3]
        item=json.loads(source.read('assets/minecraft/models/item/stick.json'))
        if any(e.get('predicate',{}).get('custom_model_data')==72533 for e in item.get('overrides',[])):
            raise ValueError('CMD72533 already owned')
        item.setdefault('overrides',[]).append(dict(predicate=dict(custom_model_data=72533),model='kanjian2:actor/filmer/forearm_l_record'))
        item['overrides'].sort(key=lambda e:e.get('predicate',{}).get('custom_model_data',-1))
        output=args.output/'KJDS_Filmer_RecordGrip_candidate.zip'
        with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as pack:
            pack.writestr('pack.mcmeta',json.dumps({'pack':{'pack_format':34,'description':'Local filming grip CMD72533; requires v12; pending review'}}))
            pack.writestr('assets/kanjian2/models/actor/filmer/forearm_l_record.json',json.dumps(model))
            pack.writestr('assets/minecraft/models/item/stick.json',json.dumps(item))
        (args.output/'forearm_l_record.json').write_text(json.dumps(model,indent=2)+'\n')
    (args.output/'manifest.json').write_text(json.dumps(dict(source_sha256=file_hash(args.source_pack),pack=output.name,
        sha256=file_hash(output),custom_model_data=72533,original_arm_elements_preserved=3,
        phone_elements_rotated=3,lens_model_coordinates=[8.15,6.95,4.89],rear_lens_axis=[0,0,-1],
        human_review='pending',runtime_passed=False,installed=False,license='local derivative; original rights unchanged'),indent=2)+'\n')
    print(output)


if __name__=='__main__':main()
