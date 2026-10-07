"""OS-held run leases release on process death; evidence remains on disk."""
import json
import os
from pathlib import Path


class RunBusyError(RuntimeError):
    pass


class RunLease:
    def __init__(self, path: Path):
        self.path = path
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            stream.write(b" "); stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            stream.close()
            raise RunBusyError(f"run is held by another process: {self.path}") from error
        self.stream = stream
        try:
            stream.seek(0); stream.truncate()
            stream.write(json.dumps({"pid": os.getpid()}).encode())
            stream.flush(); os.fsync(stream.fileno())
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *args):
        self.stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()


def replace_evidence(source: Path, target: Path) -> None:
    """Retry only Windows sharing/access errors while retaining atomic replace."""
    import time
    for attempt in range(8):
        try:
            source.replace(target)
            return
        except PermissionError as error:
            if os.name != "nt" or getattr(error,"winerror",None) not in (5,32,33) or attempt == 7:
                raise
            time.sleep(.02 * (attempt+1))


def write_json(path: Path, value: dict | list) -> None:
    """Atomic evidence update; callers serialize writers with a RunLease."""
    temporary = path.with_name(path.name + ".writing")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush(); os.fsync(stream.fileno())
    replace_evidence(temporary,path)
