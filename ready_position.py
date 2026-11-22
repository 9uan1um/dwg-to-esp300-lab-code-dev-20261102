"""Persistent ESP300 HOME-frame position; no serial connection or motion here."""
import copy
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from esp300_connection import ESP300_AXES, ESP300_AXIS_SIGNS


def validate_position(position):
    if not isinstance(position, dict) or set(position) != set('xyz'):
        raise ValueError('기계 HOME 기준 X, Y, Z가 모두 필요합니다.')
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) for v in position.values()):
        raise ValueError('XYZ는 유한한 숫자여야 합니다. 이동 한계는 실행 전 별도 검사합니다.')
    return {name: float(position[name]) for name in 'xyz'}


class ReadyPositionStore:
    def __init__(self, path):
        self.path = Path(path)
        self.value = None
        self.error = None
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('schema') != 1 or data.get('frame') != 'esp300-home-mm':
                raise ValueError('지원하지 않는 설정 위치 형식입니다.')
            data['position'] = validate_position(data.get('position'))
            self.value = data
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self.error = f'설정 위치를 읽지 못했습니다: {exc}'

    def status(self):
        return {'saved': copy.deepcopy(self.value), 'error': self.error}

    def save(self, position, source):
        data = dict(schema=1, frame='esp300-home-mm', position=validate_position(position),
                    source=source, updatedAt=datetime.now(timezone.utc).isoformat())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix=self.path.name + '.', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        self.value, self.error = data, None
        return self.status()


def prepare_ready_locked(jog, body):
    """Freeze one selected-axis move from measured raw position under the jog lock."""
    axes = body.get('axes')
    if axes not in ('xy', 'z', 'xyz'):
        raise ValueError('Ready axes must be xy, z or xyz.')
    jog._require_no_sensor_home_locked()
    jog._require_no_run_locked()
    jog._require_manual_still_locked()
    if not jog.connected:
        raise RuntimeError('장비를 먼저 연결하세요.')
    if body.get('mode') != ('mock' if jog.dry_run else 'live'):
        raise RuntimeError('화면과 장비의 Live/Dry run 모드가 다릅니다.')
    saved = jog.ready_position.value
    if saved is None:
        raise RuntimeError(jog.ready_position.error or '설정 위치가 없습니다.')
    measured = jog._read_run_pose_locked(check_ready=True)
    target_raw = {**measured, **{n: saved['position'][n] for n in axes}}
    target = {n: jog._local_of(n, value) for n, value in target_raw.items()}
    distance = math.sqrt(sum((target_raw[n] - measured[n]) ** 2 for n in axes))
    return [dict(from3=[jog._local_of(n, measured[n]) for n in 'xyz'],
                 to3=[target[n] for n in 'xyz'], duration=max(distance, .05), speedMmS=1.0,
                 kind='ready_' + axes, layer='ready', readyMove=True, readySelected=axes,
                 readyRaw=target_raw, readyContext=jog._run_context_locked(),
                 readyAxisMap=(dict(ESP300_AXES), dict(ESP300_AXIS_SIGNS)))]
