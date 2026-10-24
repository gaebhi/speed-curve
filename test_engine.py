"""Checks timing derivatives and renders actual files with moving video and audio."""
import json
import math
import subprocess
import tempfile
from pathlib import Path

from curve import EASINGS, output_time, speed_at, validate
from server import FFMPEG, FFPROBE, probe, render


def test_mapping():
    for easing in EASINGS:
        for start, end in ((1, 4), (4, 1), (.1, 8), (8, .1), (2, 2)):
            validate(start, end, easing)
            assert speed_at(0, start, end, easing) == start
            assert abs(speed_at(1, start, end, easing) - end) < 1e-12
            assert output_time(0, 7, start, end, easing) == 0
            previous = 0
            for i in range(1, 100):
                p = i / 100
                mapped = output_time(p, 7, start, end, easing)
                assert mapped > previous
                h = 1e-6
                derivative = (output_time(p+h, 7, start, end, easing)
                              - output_time(p-h, 7, start, end, easing)) / (2*h)
                assert math.isclose(derivative, 7 / speed_at(p, start, end, easing), rel_tol=2e-5)
                previous = mapped
            n = 20000
            numeric = sum((.5 if i in (0, n) else 1) / speed_at(i/n, start, end, easing)
                          for i in range(n+1)) / n * 7
            assert math.isclose(numeric, output_time(1, 7, start, end, easing), rel_tol=1e-6)
    for bad in (0, -1, 9, float('nan'), float('inf')):
        try:
            validate(bad, 1, 'ease-in')
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid speed accepted')
    print('PASS exact time mapping, acceleration/deceleration, constant speed and limits')


def test_ffmpeg():
    assert FFMPEG and FFPROBE
    test_root = Path(__file__).resolve().parent / 'test-output'
    test_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='speed-curve-test-', dir=test_root) as temporary:
        base = Path(temporary)
        assert base.resolve().parent == test_root.resolve()
        source = base / 'source.mp4'
        subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'testsrc2=size=320x180:rate=30:duration=3', '-f', 'lavfi', '-i',
                        'sine=frequency=440:sample_rate=48000:duration=3', '-c:v', 'libx264',
                        '-preset', 'ultrafast', '-c:a', 'aac', '-shortest', str(source)], check=True)
        metadata = probe(source)
        cases = [(kind, 1, 4, True) for kind in EASINGS]
        cases += [('ease-in', 4, 1, True), ('ease-in-out', .25, 1, True),
                  ('ease-in', 2, 2, False), ('ease-out', .1, .1, True)]
        for index, (kind, start, end, audio) in enumerate(cases):
            folder = base / str(index)
            folder.mkdir()
            job = dict(metadata, folder=folder, source=source, id=str(index), name='test.mp4',
                       status='queued', progress=0, cancel=False)
            render(job, dict(start=start, end=end, easing=kind, audio=audio))
            assert job['status'] == 'done', job.get('error')
            actual = probe(job['output'])
            expected = output_time(1, metadata['duration'], start, end, kind)
            assert abs(actual['duration']-expected) < .08, (kind, actual['duration'], expected)
            assert actual['audio'] == audio
            details = json.loads(subprocess.check_output([FFPROBE, '-v', 'error', '-show_streams',
                                                          '-of', 'json', str(job['output'])]))
            for stream in details['streams']:
                assert abs(float(stream.get('duration', expected))-expected) < .09
            subprocess.run([FFMPEG, '-v', 'error', '-i', str(job['output']), '-f', 'null', '-'],
                           check=True, capture_output=True)
            print(f'PASS render {kind} {start}x->{end}x audio={audio}: {actual["duration"]:.3f}s')


if __name__ == '__main__':
    test_mapping()
    test_ffmpeg()
