"""Run explicitly independent candidate packages, retaining every human review gate."""
import argparse, json, os, subprocess, sys, time
from pathlib import Path
from minecraft_film_agent.locking import RunLease, write_json
from minecraft_film_agent.bridge_client import CinematicBridgeClient, CinematicBridgeConfig
from minecraft_film_agent.photography import ReplayPhotography
from launch_game import build_command

def main():
    ap=argparse.ArgumentParser();ap.add_argument('queue',type=Path);args=ap.parse_args()
    root=Path(__file__).resolve().parents[1]; path=args.queue.resolve()
    spec=json.loads(path.read_text(encoding='utf-8'));state_path=path.with_suffix('.progress.json')
    result={'tasks':{},'human_approvals_written':0}
    with RunLease(path.with_suffix('.lock')):
        for task in spec['tasks']:
            if task.get('depends_on') or task.get('independent') is not True:
                result['tasks'][task['id']]={'status':'blocked_upstream_review_required'};continue
            folder=(root/task['package']).resolve()
            if not folder.is_relative_to(root/'work'):raise ValueError('package must be under work')
            journal=folder/'capture-journal.json'
            if journal.exists():
                prior=json.loads(journal.read_text())
                result['tasks'][task['id']]={'status':prior['status'],'action':'retained_existing_run; inspect before recovery'}
                write_json(state_path,result);continue
            capture=json.loads((folder/'capture.json').read_text());instance=Path(capture['instance'])
            plan=json.loads((folder/'actor-plan.json').read_text());proc=None
            try:
                import socket
                with socket.socket() as probe:
                    if probe.connect_ex(('127.0.0.1',25575))==0:raise RuntimeError('bridge already active; inspect owned session')
                command,_=build_command(Path(task['version_dir']).resolve(),'CineProbe',working_dir=instance,quick_play_singleplayer=plan['world'])
                env={**os.environ,'MINECRAFT_FILM_PROJECT_ROOT':str(root),
                     'PATH':str(root/'tools/ffmpeg/bin')+os.pathsep+os.environ.get('PATH','')}
                with (folder/'queue-game.log').open('x',encoding='utf-8') as log:
                    proc=subprocess.Popen(command,cwd=instance,stdout=log,stderr=subprocess.STDOUT,env=env)
                done=subprocess.run([sys.executable,str(root/'scripts/capture_actor_candidate.py'),str(folder)],env=env,check=False)
                status=json.loads(journal.read_text())['status'] if journal.exists() else 'failed_before_recording'
                result['tasks'][task['id']]={'status':status,'exit_code':done.returncode,'pid':proc.pid}
            except Exception as error:
                result['tasks'][task['id']]={'status':'blocked','error':str(error)}
            finally:
                write_json(state_path,result)
                if proc is not None and proc.poll() is None:
                    # Close only the window of the process launched by this queue.
                    # If a take/render is unresolved, leave it alive for status inspection.
                    entry=result['tasks'].get(task['id'],{})
                    if entry.get('status') not in ('needs_review','failed_before_recording'):
                        raise RuntimeError('unresolved operation retained; inspect before advancing the queue')
                    subprocess.run(['powershell','-NoProfile','-Command',f'(Get-Process -Id {proc.pid}).CloseMainWindow()'],check=True)
                    proc.wait(timeout=60)
        write_json(state_path,result)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
