"""Checks audible markers follow the video time map instead of only trimming length."""
import array
import math
import subprocess
import tempfile
import wave
from pathlib import Path

from curve import output_time
from server import FFMPEG, probe, render

test_root = Path(__file__).resolve().parent / 'test-output'
test_root.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='audio-sync-', dir=test_root) as temporary:
    base = Path(temporary)
    assert base.resolve().parent == test_root.resolve()
    rate, centers = 48000, (.6, 1.5, 2.4)
    samples = array.array('h')
    for i in range(3 * rate):
        t = i / rate
        center = min(centers, key=lambda c: abs(t-c))
        distance = abs(t-center)
        amplitude = max(0, 1-distance/.045)
        samples.append(int(24000 * amplitude * math.sin(2*math.pi*440*t)))
    with wave.open(str(base/'marks.wav'), 'wb') as stream:
        stream.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        stream.writeframes(samples.tobytes())
    source = base/'source.mp4'
    subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'testsrc2=size=320x180:rate=30:duration=3', '-i', str(base/'marks.wav'),
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-shortest', str(source)], check=True)
    for start, end, kind in ((1, 4, 'ease-in'), (4, 1, 'ease-out'), (.5, 2, 'ease-in-out')):
        folder = base/f'{start}-{end}'
        folder.mkdir()
        job = dict(probe(source), folder=folder, source=source, id='sync', name='sync.mp4', cancel=False)
        render(job, dict(start=start, end=end, easing=kind, audio=True))
        assert job['status'] == 'done', job.get('error')
        raw = subprocess.check_output([FFMPEG, '-v', 'error', '-i', str(job['output']),
                                       '-vn', '-ac', '1', '-ar', str(rate), '-f', 'f32le', '-'])
        decoded = array.array('f', raw)
        bin_size = 240
        active = []
        for index in range(0, len(decoded), bin_size):
            chunk = decoded[index:index+bin_size]
            rms = math.sqrt(sum(v*v for v in chunk)/len(chunk))
            if rms > .025:
                active.append((index+bin_size/2)/rate)
        groups = []
        for moment in active:
            if not groups or moment-groups[-1][-1] > .05:
                groups.append([])
            groups[-1].append(moment)
        detected = [(g[0]+g[-1])/2 for g in groups]
        expected = [output_time(c/3, 3, start, end, kind) for c in centers]
        assert len(detected) == 3, (kind, detected)
        errors = [abs(a-b) for a,b in zip(detected, expected)]
        assert max(errors) < .12, (kind, detected, expected, errors)
        print(f'PASS audible sync {kind} {start}->{end}, max error {max(errors):.3f}s')
