"""Measure observed take trajectories; never turn numeric checks into visual approval."""
import argparse
import collections
import json
import math
from pathlib import Path
from minecraft_film_agent.photography import file_hash


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('package',type=Path)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    plan=json.loads((args.package/'actor-plan.json').read_text())
    summary=json.loads((args.package/'trace-summary.json').read_text())
    trace=Path(summary['trace']);rows=[json.loads(l) for l in trace.read_text().splitlines()]
    groups=collections.defaultdict(list)
    for row in rows:groups[row['actor_id']].append(row)
    if set(groups)!={a['actor_id'] for a in plan['actors']}:raise ValueError('actor trace set differs')
    report=dict(run_id=plan['run_id'],trace_sha256=file_hash(trace),rows=len(rows),
                scope='authoritative positions, joint steps and contact timing; no visual or story acceptance',
                human_review='pending',actors={})
    for name,frames in groups.items():
        if [r['planned_tick'] for r in frames]!=list(range(plan['duration_ticks'])):
            raise ValueError('incomplete/duplicate tick sequence: '+name)
        changes=[];contacts=[];bones=[]
        for before,after in zip(frames,frames[1:]):
            previous={p['part']:p for p in before['visual']['parts']}
            for part in after['visual']['parts']:
                a=previous[part['part']]['local_rotation'];b=part['local_rotation']
                dot=abs(sum(x*y for x,y in zip(a,b)))/math.sqrt(sum(x*x for x in a)*sum(x*x for x in b))
                angle=math.degrees(2*math.acos(min(1,dot)))
                changes.append(dict(degrees=angle,tick=after['planned_tick'],part=part['part'],
                                    from_action=before['action'],action=after['action']))
        for frame in frames:
            proof=frame['visual'].get('support_contact')
            if proof:
                if proof.get('contact_established',True):
                    contacts.append(dict(tick=frame['planned_tick'],error=proof['error'],target_actor=proof['actor_ref']))
                bones.extend(abs(proof[k]-.375) for k in ('upper_length','forearm_length'))
        report['actors'][name]=dict(max_joint_steps=sorted(changes,key=lambda p:p['degrees'],reverse=True)[:12],
                                   first_established_contact=contacts[0] if contacts else None,
                                   max_established_contact_error=max((c['error'] for c in contacts),default=None),
                                   max_contact_bone_length_error=max(bones,default=None))
    with args.output.open('x',encoding='utf-8') as out:json.dump(report,out,indent=2)
    print(args.output)


if __name__=='__main__':main()
