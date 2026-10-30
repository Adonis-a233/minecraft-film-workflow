"""One event guide mix for phone/monitor derivatives; temporary voices, not final sound."""
import argparse
import json
import math
import random
import struct
import subprocess
import wave
from pathlib import Path
from minecraft_film_agent.photography import file_hash


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('package',type=Path)
    ap.add_argument('--voices',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1]
    ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe'
    plan=json.loads((args.package/'actor-plan.json').read_text())
    trace=Path(json.loads((args.package/'trace-summary.json').read_text())['trace'])
    rows=[json.loads(l) for l in trace.read_text().splitlines()]
    board=[r for r in rows if r['actor_id']=='CH06' and r.get('board',{}).get('released_at_tick',-1)>=0]
    impact=next(r['planned_tick'] for r in board if abs(r['board']['y']-r['board']['floor'])<1e-6)
    rng=random.Random(20261030);sr=48000;samples=[]
    for i in range(int(.65*sr)):
        t=i/sr
        v=.43*math.sin(2*math.pi*67*t)*math.exp(-t*13)+.17*rng.uniform(-1,1)*math.exp(-t*24)
        samples.append(int(max(-1,min(1,v))*32767))
    impact_path=args.output/'synthetic-board-impact.wav'
    with wave.open(str(impact_path),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(sr);w.writeframes(struct.pack('<'+'h'*len(samples),*samples))
    settings=[('route',.5,'CH06'),('filmer-push',10.6,'CH06'),('worker-up',13.2,'CH04'),
              ('elder-wait',16.5,'CH05'),('cow-away',20.,'CH07')]
    manifest=dict(status='temporary_guide_not_final_sound',human_review='pending',
                  run_id=plan['run_id'],master_hash=json.loads((args.package/'master.json').read_text())['master_hash'],
                  trace_sha256=file_hash(trace),event_seconds=plan['duration_ticks']/20,
                  limitations=['Installed Microsoft temporary voices reused as individual original-speed lines.',
                               'New take mouth frames are not synchronized to these voices.',
                               'Warning vocal, footsteps, bag/cloth and environmental bed still missing.',
                               'Synthetic board thud is an editorial placeholder, not recorded location sound.'],cues=[])
    command=[str(ffmpeg),'-hide_banner','-loglevel','error','-nostdin']
    for name,at,actor in settings:
        source=args.voices/(name+'.wav')
        with wave.open(str(source)) as w:duration=w.getnframes()/w.getframerate()
        command+=['-i',str(source)]
        manifest['cues'].append(dict(id=name,actor=actor,at_seconds=at,duration_seconds=duration,
                                     source=str(source),sha256=file_hash(source),speed=1))
    command+=['-i',str(impact_path)]
    delays=[at for _,at,_ in settings]+[impact/20]
    filters=[f'[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,adelay={round(at*1000)}|{round(at*1000)}[a{i}]' for i,at in enumerate(delays)]
    filters.append(''.join(f'[a{i}]' for i in range(len(delays)))+f'amix=inputs={len(delays)}:normalize=0,apad,atrim=0:{plan["duration_ticks"]/20},alimiter=limit=0.95:latency=1[out]')
    output=args.output/'event-guide.wav'
    subprocess.run(command+['-filter_complex',';'.join(filters),'-map','[out]','-c:a','pcm_s16le','-ar','48000',str(output)],check=True)
    manifest['cues'].append(dict(id='board-impact',at_tick=impact,at_seconds=impact/20,
                                 evidence='first observed board center at declared floor',source_sha256=file_hash(impact_path)))
    manifest['audio_sha256']=file_hash(output)
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(output)


if __name__=='__main__':main()
