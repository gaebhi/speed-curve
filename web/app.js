const $ = id => document.getElementById(id);
const state = {job:null, easing:'ease-in', busy:false, preview:false, output:false, poll:null, graph:null};
const descriptions = {
  'ease-in':'처음엔 천천히 변하고, 끝으로 갈수록 빠르게 변해요.',
  'ease-out':'초반에 빠르게 변하고, 끝으로 갈수록 부드럽게 변해요.',
  'ease-in-out':'시작과 끝은 부드럽게, 중간에서 빠르게 변해요.'
};
function speed(p, a, b, kind) {
  const e = kind === 'ease-in' ? p*p : kind === 'ease-out' ? 1-(1-p)**2 : p < .5 ? 2*p*p : 1-2*(1-p)**2;
  return a+(b-a)*e;
}
function settings() {
  const start = Number($('startSpeed').value), end = Number($('endSpeed').value);
  if (![start,end].every(v=>Number.isFinite(v)&&v>=.1&&v<=8)) return null;
  return {start,end,easing:state.easing,audio:$('keepAudio').checked};
}
function seconds(n) { return n < 60 ? n.toFixed(2) : `${Math.floor(n/60)}:${(n%60).toFixed(2).padStart(5,'0')}`; }
function notify(text, info=false) { $('notice').textContent=text; $('notice').className=`notice${info?' info':''}`; $('notice').hidden=!text; }
function estimate(s) {
  const steps=1200; let integral=0;
  for (let i=0;i<=steps;i++) integral+=(i===0||i===steps ? 0.5 : 1)/speed(i/steps,s.start,s.end,s.easing);
  return integral/steps*(state.job?.duration||1);
}
function drawGraph() {
  const s=settings();
  $('exportButton').disabled=state.busy||!state.job||!s;
  if (!s) { $('curveRange').textContent='0.1~8배 사이로 입력'; return; }
  const min=0, max=Math.max(s.start,s.end)*1.17, x0=31,x1=431,y0=12,y1=157;
  const xy=p=>[x0+(x1-x0)*p,y1-(speed(p,s.start,s.end,s.easing)-min)/(max-min)*(y1-y0)];
  state.graph=xy;
  let grid='';
  for (let i=0;i<4;i++) { const y=y1-(y1-y0)*i/3; const v=max*i/3; grid+=`<line x1="31" y1="${y}" x2="431" y2="${y}" stroke="#2c352e" stroke-dasharray="3 5"/><text x="0" y="${y+3}" fill="#708171" font-size="9">${v.toFixed(1)}×</text>`; }
  for(let i=1;i<4;i++){const x=x0+(x1-x0)*i/4;grid+=`<line x1="${x}" y1="12" x2="${x}" y2="157" stroke="#242c26" stroke-dasharray="3 5"/>`;}
  $('grid').innerHTML=grid;
  let d='';for(let i=0;i<=120;i++){const [x,y]=xy(i/120);d+=`${i?'L':'M'}${x.toFixed(2)} ${y.toFixed(2)} `;}
  $('curve').setAttribute('d',d);$('area').setAttribute('d',`${d}L${x1} ${y1}L${x0} ${y1}Z`);
  [['startDot',0],['endDot',1]].forEach(([id,p])=>{const [x,y]=xy(p);$(id).setAttribute('cx',x);$(id).setAttribute('cy',y);});
  $('curveRange').textContent=`${s.start.toFixed(1)}× → ${s.end.toFixed(1)}×`;
  $('curveGraph').setAttribute('aria-label',`${descriptions[s.easing]} 시작 ${s.start}배, 끝 ${s.end}배`);
  $('easingHint').textContent=s.start===s.end?'시작과 끝이 같아서 일정한 배속으로 재생해요.':descriptions[s.easing];
  if(state.job){const out=estimate(s);$('sourceDuration').innerHTML=`${seconds(state.job.duration)}<small>초</small>`;$('outputDuration').innerHTML=`${seconds(out)}<small>초</small>`;const delta=state.job.duration-out;$('timeDifference').textContent=Math.abs(delta)<.05?'길이 동일':`${Math.abs(delta).toFixed(1)}초 ${delta>0?'짧게':'길게'}`;}
  try{localStorage.setItem('speed-curve-settings',JSON.stringify(s));}catch{}
}
function setBusy(busy){state.busy=busy;['startSpeed','endSpeed','keepAudio','resetButton','changeFile','fileInput'].forEach(id=>$(id).disabled=busy||(id==='keepAudio'&&state.job&&!state.job.audio));document.querySelectorAll('.easing').forEach(b=>b.disabled=busy);$('exportButton').querySelector('span').textContent=busy?'내보내는 중…':'MP4 내보내기';drawGraph();}
function setProgress(label,value){$('progressArea').hidden=false;$('progressLabel').textContent=label;$('progressPercent').textContent=`${Math.round(value)}%`;$('progress').value=value;}
function stopPreview(){state.preview=false;$('video').pause();$('video').playbackRate=1;$('previewButton').innerHTML='<span>▷</span> 속도 미리보기';$('liveSpeed').textContent='1.00×';$('playhead').setAttribute('visibility','hidden');}
function showSource(){if(!state.job)return;stopPreview();state.output=false;$('video').src=`/api/source/${state.job.id}`;$('previewBadge').textContent='원본 영상';$('originalButton').hidden=true;}
async function upload(file){
  if(!file||state.busy)return;
  stopPreview();notify('');$('resultArea').hidden=true;setBusy(true);$('cancelButton').hidden=true;setProgress('영상 불러오는 중',0);
  try{
    const job=await new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST',`/api/upload?name=${encodeURIComponent(file.name)}`);xhr.setRequestHeader('Content-Type','application/octet-stream');xhr.upload.onprogress=e=>{if(e.lengthComputable)setProgress('영상 불러오는 중',e.loaded/e.total*100);};xhr.onload=()=>{let data;try{data=JSON.parse(xhr.responseText);}catch{reject(new Error('서버 응답을 읽을 수 없습니다.'));return;}xhr.status<300?resolve(data):reject(new Error(data.error||'영상을 불러오지 못했습니다.'));};xhr.onerror=()=>reject(new Error('로컬 도구와 연결이 끊겼습니다. 실행.cmd로 다시 열어 주세요.'));xhr.send(file);});
    state.job=job;$('dropZone').hidden=true;$('videoWrap').hidden=false;$('fileBar').hidden=false;$('fileName').textContent=job.name;$('fileDetails').textContent=`${job.width} × ${job.height} · ${job.fps.toFixed(2).replace(/\.00$/,'')}fps · ${(file.size/1024/1024).toFixed(1)}MB`;$('mediaType').textContent=job.audio?'영상 + 오디오':'오디오 없음';$('previewButton').disabled=false;$('keepAudio').disabled=!job.audio;$('audioHint').textContent=job.audio?'음높이를 유지하며 함께 변속':'원본에 오디오 트랙이 없어요';$('previewNote').textContent='미리보기를 누르면 선택한 곡선으로 재생해요.';showSource();drawGraph();
  }catch(e){notify(e.message);}finally{$('progressArea').hidden=true;setBusy(false);$('fileInput').value='';}
}
async function jsonRequest(url,body){const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw new Error(data.error||'요청 실패');return data;}
async function poll(){
  try{
    const response=await fetch(`/api/jobs/${state.job.id}`,{cache:'no-store'});if(!response.ok)throw new Error('작업 상태를 읽지 못했습니다.');const job=await response.json();state.job={...state.job,...job};
    setProgress(job.status==='queued'?'변환 준비 중':'MP4 만드는 중',job.progress*100);
    if(job.status==='done'){$('progressArea').hidden=true;setBusy(false);$('resultArea').hidden=false;$('downloadButton').href=job.output_url;$('downloadButton').download=job.output_name;$('resultInfo').textContent=`${seconds(job.expected_duration)}초 · MP4 · ${job.audio&&$('keepAudio').checked?'오디오 포함':'무음'}`;return;}
    if(job.status==='error')throw new Error(`변환에 실패했어요.\n${job.error}`);
    if(job.status==='cancelled'){$('progressArea').hidden=true;setBusy(false);notify('내보내기를 중지했어요.',true);return;}
    state.poll=setTimeout(poll,650);
  }catch(e){setBusy(false);$('progressArea').hidden=true;notify(e.message);}
}
async function exportVideo(){const s=settings();if(!s||!state.job||state.busy)return;stopPreview();notify('');$('resultArea').hidden=true;setBusy(true);$('cancelButton').hidden=false;setProgress('변환 준비 중',0);try{await jsonRequest('/api/render',{job_id:state.job.id,...s});poll();}catch(e){setBusy(false);$('progressArea').hidden=true;notify(e.message);}}
$('fileInput').addEventListener('change',e=>upload(e.target.files[0]));
$('dropZone').addEventListener('click',()=>{if(!state.busy)$('fileInput').click();});
$('dropZone').addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();$('fileInput').click();}});
$('changeFile').addEventListener('click',()=>$('fileInput').click());
document.addEventListener('dragover',e=>{e.preventDefault();if(!state.busy)$('dropZone').classList.add('dragging');});
document.addEventListener('dragleave',e=>{if(!e.relatedTarget)$('dropZone').classList.remove('dragging');});
document.addEventListener('drop',e=>{e.preventDefault();$('dropZone').classList.remove('dragging');upload(e.dataTransfer.files[0]);});
function settingsChanged(){if(state.output)showSource();$('resultArea').hidden=true;drawGraph();}
['startSpeed','endSpeed','keepAudio'].forEach(id=>$(id).addEventListener('input',settingsChanged));
document.querySelectorAll('.easing').forEach(button=>button.addEventListener('click',()=>{state.easing=button.dataset.easing;document.querySelectorAll('.easing').forEach(b=>{b.classList.toggle('active',b===button);b.setAttribute('aria-pressed',String(b===button));});settingsChanged();}));
$('resetButton').addEventListener('click',()=>{$('startSpeed').value=1;$('endSpeed').value=4;document.querySelector('[data-easing="ease-in"]').click();});
$('exportButton').addEventListener('click',exportVideo);
$('cancelButton').addEventListener('click',async()=>{try{$('cancelButton').disabled=true;await jsonRequest('/api/cancel',{job_id:state.job.id});}catch(e){notify(e.message);}finally{$('cancelButton').disabled=false;}});
$('previewButton').addEventListener('click',async()=>{if(!state.job)return;if(state.preview){stopPreview();return;}if(state.output)showSource();const s=settings();if(!s){notify('시작·끝 배속을 0.1~8 사이로 입력해 주세요.');return;}state.preview=true;$('video').currentTime=0;$('video').playbackRate=s.start;$('video').preservesPitch=true;$('previewBadge').textContent='속도 곡선 미리보기';$('previewButton').innerHTML='<span>Ⅱ</span> 미리보기 중지';try{await $('video').play();}catch(e){stopPreview();notify('이 형식은 브라우저 미리보기를 지원하지 않을 수 있어요. MP4 내보내기는 사용할 수 있습니다.',true);}});
$('originalButton').addEventListener('click',showSource);
$('resultPreview').addEventListener('click',()=>{stopPreview();state.output=true;$('video').src=state.job.preview_url;$('previewBadge').textContent='완성된 MP4';$('originalButton').hidden=false;$('video').play().catch(()=>{});});
$('video').addEventListener('ended',()=>{if(state.preview)stopPreview();});
$('video').addEventListener('error',()=>{if(state.job)notify('이 파일은 브라우저에서 미리보기가 어려울 수 있어요. MP4 내보내기는 계속 사용할 수 있습니다.',true);});
function tick(){if(state.preview&&state.job){const s=settings();if(s){const p=Math.min(1,$('video').currentTime/state.job.duration),v=speed(p,s.start,s.end,s.easing);$('video').playbackRate=v;$('liveSpeed').textContent=`${v.toFixed(2)}×`;if(state.graph){const [x,y]=state.graph(p);$('playhead').setAttribute('cx',x);$('playhead').setAttribute('cy',y);$('playhead').setAttribute('visibility','visible');}}}requestAnimationFrame(tick);}requestAnimationFrame(tick);
try{const saved=JSON.parse(localStorage.getItem('speed-curve-settings'));if(saved&&['ease-in','ease-out','ease-in-out'].includes(saved.easing)&&[saved.start,saved.end].every(v=>Number.isFinite(v)&&v>=.1&&v<=8)){$('startSpeed').value=saved.start;$('endSpeed').value=saved.end;state.easing=saved.easing;document.querySelectorAll('.easing').forEach(b=>{const active=b.dataset.easing===state.easing;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});}}catch{}
drawGraph();fetch('/api/health').then(r=>r.json()).then(health=>{if(!health.ready)notify('FFmpeg를 찾을 수 없습니다. 실행 안내를 확인해 주세요.');}).catch(()=>notify('로컬 도구에 연결할 수 없습니다. 실행.cmd로 열어 주세요.'));
