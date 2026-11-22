export function createReadyControls({document, request, onStatus, onRun, refresh}) {
  const ids = ['readyXY', 'readyZ', 'readyXYZ', 'readyX', 'readyY', 'readyPositionZ',
    'readySave', 'readyCapture', 'readySavedText', 'readyStatus'];
  const el = Object.fromEntries(ids.map(id => [id, document.getElementById(id)]));
  const fields = [el.readyX, el.readyY, el.readyPositionZ];
  let state = null, pending = false, savedKey = null, dirty = false, notice = '';
  const fmt = p => `X ${p.x.toFixed(5)} / Y ${p.y.toFixed(5)} / Z ${p.z.toFixed(5)} mm`;
  function values() {
    if (fields.some(f => f.value.trim() === '')) throw new Error('X, Y, Z를 모두 입력하세요.');
    const position = Object.fromEntries('xyz'.split('').map((n, i) => [n, Number(fields[i].value)]));
    if (Object.values(position).some(v => !Number.isFinite(v))) {
      throw new Error('XYZ에 유한한 숫자를 입력하세요.');
    }
    return position;
  }
  function render() {
    const busy = pending || !state || state.connectionPreparation?.active || state.run?.running
      || state.sensorHome?.running || state.manualMotion?.active;
    const unavailable = busy || !state?.connected || !!state?.telemetryError;
    const saved = state?.ready?.saved;
    for (const button of [el.readyXY, el.readyZ, el.readyXYZ]) {
      button.disabled = unavailable || dirty || !saved || !!state?.manualMotion?.error;
    }
    fields.forEach(f => { f.disabled = !!busy; });
    el.readySave.disabled = !!busy;
    el.readyCapture.disabled = unavailable || !!state?.dryRun;
    el.readySavedText.textContent = saved ? `설정 위치 · 기계 HOME 기준: ${fmt(saved.position)}`
      : state?.ready?.error || '설정 위치 불러오는 중…';
    const run = state?.ready?.run;
    el.readyStatus.textContent = notice || (pending ? '요청 중…'
      : dirty ? '입력값을 저장한 후 이동하세요.'
      : !state?.ready ? 'Ready 기능을 사용하려면 프로그램을 재시작하세요.'
      : run?.running ? `${run.readyAxes.toUpperCase()} 이동 중 · Stop run으로 정지`
      : run?.error ? `${run.readyAxes.toUpperCase()}: ${run.error}`
      : run?.done ? `${run.readyAxes.toUpperCase()} 도착 확인 완료`
      : '기계 HOME 기준 설정 위치로 이동');
  }
  function update(data) {
    state = data;
    const key = JSON.stringify(data.ready?.saved);
    if (!pending && key !== savedKey && data.ready?.saved) {
      savedKey = key;
      fields.forEach((f, i) => { f.value = String(data.ready.saved.position['xyz'[i]]); });
      dirty = false;
    }
    render();
  }
  async function action(kind, axes) {
    if (pending) return;
    let body;
    try {
      if (kind === 'save') body = {position: values()};
      else {
        if (!state?.connected) throw new Error('장비를 먼저 연결하세요.');
        if (kind === 'move' && dirty) throw new Error('입력값을 먼저 저장하세요.');
        body = {mode: state.dryRun ? 'mock' : 'live'};
        if (axes) body.axes = axes;
      }
      pending = true; notice = ''; render();
      const result = await request(`/api/jog/ready/${kind}`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
      });
      pending = false;
      if (kind === 'move') {
        state = {...state, run: result, ready: {...state.ready, run: result}};
        onRun(result);
        render();
      } else {
        savedKey = null; // Refill fields only after successful persistence.
        update(result);
        onStatus(result);
        notice = '설정 위치 저장 완료';
        render();
      }
      await refresh();
    } catch (error) {
      pending = false; notice = error.message; render();
    }
  }
  fields.forEach(f => f.addEventListener('input', () => {
    dirty = true; notice = ''; render();
  }));
  for (const [id, axes] of [['readyXY', 'xy'], ['readyZ', 'z'], ['readyXYZ', 'xyz']]) {
    el[id].addEventListener('click', () => action('move', axes));
  }
  el.readySave.addEventListener('click', () => action('save'));
  el.readyCapture.addEventListener('click', () => action('capture'));
  render();
  return {update};
}
