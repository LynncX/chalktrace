'use strict';
const $ = id => document.getElementById(id);
const clone = value => structuredClone(value);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uid = () => 'O' + crypto.randomUUID().replaceAll('-', '').slice(0, 16);
const clock = s => `${String(Math.floor(s / 60)).padStart(2, '0')}:${(s % 60).toFixed(2).padStart(5, '0')}`;
const labels = {todo:'待标',draft:'草稿',done:'完成',full:'完整',partial:'部分遮挡',hidden:'完全遮挡',uncertain:'不确定',unchanged:'不变',added:'追加',erased:'擦除',rewritten:'重写'};
let state = null, index = 0, selected = null, tool = 'select', points = [], gesture = null;
let undoStack = [], redoStack = [], dirty = false, saveTimer = null, saving = null, changeSerial = 0, blocked = false;
let merged = new Set(), tab = 'item';
const frameInfo = () => state.dataset.frames[index];
const frame = () => state.annotation.frames[frameInfo().id];
const observation = () => frame().observations.find(o => o.id === selected);
const taskURL = action => `/api/tasks/${encodeURIComponent(state.dataset.id)}${action ? '/' + action : ''}`;
function notice(message = '', error = false) { $('notice').textContent = message; $('notice').className = error ? 'error' : ''; $('notice').style.display = message ? 'block' : 'none'; }
async function api(url, data) {
  const response = await fetch(url, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) { const error = new Error(result.error || '请求失败'); error.status = response.status; throw error; }
  return result;
}
function markDirty() {
  dirty = true; changeSerial++;
  $('saved').textContent = blocked ? '保存冲突：请导出草稿' : '待保存…';
  clearTimeout(saveTimer);
  if (!blocked) saveTimer = setTimeout(() => save().catch(e => notice(e.message, true)), 650);
}
function checkpoint() {
  undoStack.push(clone(state.annotation));
  if (undoStack.length > 80) undoStack.shift();
  redoStack = [];
}
function mutate(fn, rerender = true) {
  checkpoint();
  try { fn(); } catch(e) { state.annotation=undoStack.pop(); render(); notice(e.message,true); return; }
  if (frame().status === 'done') frame().status = 'draft';
  markDirty();
  if (rerender) render();
}
async function save() {
  clearTimeout(saveTimer);
  if (blocked) throw new Error('保存冲突：请先导出本页草稿，再重新载入任务');
  if (saving) { await saving; if (dirty) return save(); return; }
  if (!state || !dirty) return;
  const serial = changeSerial, snapshot = clone(state.annotation);
  $('saved').textContent = '保存中…';
  saving = api(taskURL('save'), snapshot);
  try {
    const result = await saving;
    state.annotation.revision = result.revision;
    state.annotation.saved_at = result.saved_at;
    dirty = changeSerial !== serial;
    $('saved').textContent = dirty ? '待保存…' : `✓ 已保存 · r${result.revision}`;
    if (dirty) saveTimer = setTimeout(() => save().catch(e => notice(e.message, true)), 300);
  } catch (e) {
    if (e.status === 409) blocked = true;
    $('saved').textContent = blocked ? '保存冲突 · 请导出草稿' : '保存失败 · 草稿仍在本页';
    notice(e.message, true); throw e;
  } finally { saving = null; }
}
function restore(snapshot, destination) {
  destination.push(clone(state.annotation));
  const revision = state.annotation.revision;
  state.annotation = snapshot; state.annotation.revision = revision;
  selected = null; markDirty(); render();
}
function nextTrack() {
  const sid = frame().scene_id;
  let n = 1;
  while (state.annotation.tracks[`${sid}-L${String(n).padStart(3,'0')}`]) n++;
  return `${sid}-L${String(n).padStart(3,'0')}`;
}
function newObservation(regions = [], text = '', source = null) {
  const tid = nextTrack();
  state.annotation.tracks[tid] = {scene_id:frame().scene_id,versions:{V001:text}};
  const obs = {id:uid(),track_id:tid,version_id:'V001',visible_text:text,regions:clone(regions),visibility:regions.length?'full':'hidden',change:'unchanged',confirmed:false,source};
  frame().observations.push(obs); selected = obs.id; return obs;
}
function imageURL(fid) { return taskURL('image/' + fid); }
async function refreshTasks() {
  const tasks = await api('/api/tasks');
  $('tasks').innerHTML = '<option value="">选择任务</option>' + tasks.map(t => `<option value="${esc(t.id)}">${esc(t.title)} · ${t.done}/${t.frames}</option>`).join('');
  if (state) $('tasks').value = state.dataset.id;
}
async function openTask(id) {
  if (!id) return;
  await save();
  state = await api('/api/tasks/' + encodeURIComponent(id));
  index = 0; selected = null; undoStack = []; redoStack = []; dirty = false; blocked = false;
  $('workspace').hidden = false; $('empty').hidden = true;
  $('saved').textContent = `✓ 已保存 · r${state.annotation.revision}`;
  localStorage.setItem('annotation-task', id);
  $('tasks').value = id;
  $('video-details').open = false;
  $('video').removeAttribute('src'); $('video').load();
  notice(); render();
}
function options(values, current) { return values.map(([v,l]) => `<option value="${esc(v)}" ${v===current?'selected':''}>${esc(l)}</option>`).join(''); }
function setTool(value) {
  tool = value; points = []; gesture = null;
  document.querySelectorAll('[data-tool]').forEach(b => b.classList.toggle('active', b.dataset.tool === tool));
  $('tool-hint').textContent = {select:'拖动顶点调整区域；拖动区域内部移动。点击 OCR 虚线框可接受预测。',rect:'在当前帧拖拽画框，建立新的物理文字行。',region:'拖拽画框，加入当前条目的另一个可见片段。',replace:'拖拽画框，替换当前条目的可见区域。',occlusion:'逐点点击绘制教师遮挡多边形，Enter 完成；Esc 取消。',board:'依次点击白板四角，Enter 完成；将应用于当前场景。'}[tool];
  if (state) renderCanvas();
}
function render() {
  const f = frameInfo(), a = frame(), frames = state.dataset.frames;
  $('progress').textContent = `${Object.values(state.annotation.frames).filter(v=>v.status==='done').length}/${frames.length}`;
  let lastScene = '';
  $('frame-list').innerHTML = frames.map((v,i) => {
    const sid = state.annotation.frames[v.id].scene_id;
    const head = sid !== lastScene ? `<div class="scene-heading">${esc(sid)} · ${esc(state.annotation.scenes[sid].name)}</div>` : '';
    lastScene = sid;
    return head + `<div class="frame-card ${i===index?'active':''}" data-index="${i}"><img src="${imageURL(v.id)}" loading="lazy" alt="${clock(v.time)}"><div class="frame-meta"><span>${clock(v.time)}</span><span>${labels[state.annotation.frames[v.id].status]}${v.origin==='supplement'?' ＋':''}</span></div></div>`;
  }).join('');
  $('filmstrip').innerHTML = frames.map((v,i)=>`<button data-index="${i}" class="${i===index?'active':''}"><img src="${imageURL(v.id)}" loading="lazy" alt="">${clock(v.time)}</button>`).join('');
  $('reference').innerHTML = '<option value="">无参考帧</option>' + frames.slice(0,index).map(v=>`<option value="${v.id}" ${a.reference_id===v.id?'selected':''}>${clock(v.time)} · ${v.id}</option>`).join('');
  $('current-title').textContent = `当前帧 ${clock(f.time)}`;
  $('scene-label').textContent = `${a.scene_id} · ${labels[a.status]}`;
  const ref = frames.find(v=>v.id===a.reference_id);
  $('reference-title').textContent = ref ? `参考帧 ${clock(ref.time)}` : '无参考帧';
  $('reference-wrap').hidden = !ref;
  if (ref) $('reference-image').src = imageURL(ref.id);
  $('current-image').src = imageURL(f.id);
  $('position').textContent = `${index+1} / ${frames.length} · 原帧 ${f.number}`;
  $('coordinates').textContent = `原始帧坐标 ${state.dataset.video.width} × ${state.dataset.video.height}`;
  $('prev').disabled = index === 0; $('next').disabled = index === frames.length-1;
  $('undo').disabled = !undoStack.length; $('redo').disabled = !redoStack.length;
  $('previous-items').innerHTML = ref ? '<span class="hint">继承参考帧条目：</span>' + state.annotation.frames[ref.id].observations.map(o=>`<button data-inherit="${esc(o.id)}">${esc(o.track_id)}</button>`).join('') : '';
  renderItems(); renderInspector(); renderFramePanel(); renderCanvas();
}
function renderItems() {
  $('items').innerHTML = frame().observations.map(o=>`<div class="item-row ${o.id===selected?'active':''}" data-observation="${o.id}"><input type="checkbox" data-merge="${o.id}" ${merged.has(o.id)?'checked':''} aria-label="选中合并"><b>${esc(o.track_id)}</b><span class="badge ${o.confirmed?'ok':''}">${o.confirmed?'已确认':'待确认'}</span><p>${esc(o.visible_text || '（无可见文字）')}</p><span class="hint">${labels[o.visibility]} · ${o.regions.length} 个区域 · ${o.version_id}</span></div>`).join('') + (frame().observations.length>1?'<button id="merge-items">合并勾选条目</button>':'');
  const preds = state.predictions[frameInfo().id] || [];
  $('prediction-count').textContent = preds.length;
  $('predictions').innerHTML = preds.map((p,i)=>`<div class="pred-row"><span class="badge">${esc(p.source)} · ${Number(p.score).toFixed(2)}</span><p>${esc(p.text)}</p><button data-accept="${i}">接受为条目</button><button data-append="${i}">加入选中条目</button></div>`).join('');
}
function renderInspector() {
  const o = observation();
  if (!o) { $('item-panel').innerHTML = '<p class="hint">选择一个条目或接受 OCR 预标注。文字框工具可补漏标；参考帧条目按钮可继承身份。</p>'; return; }
  const track = state.annotation.tracks[o.track_id];
  $('item-panel').innerHTML = `<span class="badge ${o.confirmed?'ok':''}">${o.confirmed?'已确认':'待确认'}</span><label>条目 ID<select id="track-id">${options(Object.entries(state.annotation.tracks).filter(([,t])=>t.scene_id===frame().scene_id).map(([id])=>[id,id]),o.track_id)}</select></label><div class="actions"><button id="unlink">分配新 ID</button><button id="delete-item" class="danger">删除条目</button></div><label>内容版本<select id="version-id">${options(Object.entries(track.versions).map(([v,t])=>[v,`${v} · ${t.slice(0,28)}`]),o.version_id)}</select></label><label>版本文字（同 ID / 版本共享）<textarea id="version-text" rows="2">${esc(track.versions[o.version_id])}</textarea></label><button id="new-version">＋ 追加 / 擦除后新版本</button><label>当前帧实际可见文字<textarea id="visible-text" rows="3">${esc(o.visible_text)}</textarea></label><label>可见性<select id="visibility">${options(['full','partial','hidden','uncertain'].map(v=>[v,labels[v]]),o.visibility)}</select></label><label>内容变化<select id="item-change">${options(['unchanged','added','erased','rewritten','uncertain'].map(v=>[v,labels[v]]),o.change)}</select></label><div class="actions"><button id="add-region">＋ 可见片段</button><button id="redraw-region">重画本行</button><button id="split-item">拆成两行</button><button id="clear-regions">清空区域</button><button id="remove-region">删除选中区域</button></div><p class="hint">${o.regions.length} 个可见区域；若 OCR 合并了两行，请重画当前行，再新建另一行。</p><label class="checkline"><input id="confirmed" type="checkbox" ${o.confirmed?'checked':''}>已核验文字、区域与身份</label>`;
  const bind = (id, fn) => $(id).addEventListener('change', e => mutate(()=> { fn(e.target.value); o.confirmed=false; }));
  bind('track-id', value => {
    if (frame().observations.some(x=>x.id!==o.id && x.track_id===value)) throw new Error('当前帧已有此条目，请使用合并');
    o.track_id=value; o.version_id=Object.keys(state.annotation.tracks[value].versions).at(-1);
  });
  bind('version-id', v=>o.version_id=v);
  bind('version-text', v=>{track.versions[o.version_id]=v;for(const f of Object.values(state.annotation.frames)){for(const x of f.observations)if(x.track_id===o.track_id&&x.version_id===o.version_id){x.confirmed=false;if(f.status==='done')f.status='draft';}}});
  bind('visible-text', v=>o.visible_text=v);
  bind('visibility', v=> {o.visibility=v; if(v==='hidden'){o.regions=[];o.visible_text='';}});
  bind('item-change', v=>o.change=v);
  $('confirmed').onchange = e=>mutate(()=>o.confirmed=e.target.checked);
  $('unlink').onclick = ()=>mutate(()=>{ const tid=nextTrack(); state.annotation.tracks[tid]={scene_id:frame().scene_id,versions:{V001:track.versions[o.version_id]}}; o.track_id=tid; o.version_id='V001'; o.confirmed=false; });
  $('delete-item').onclick = ()=>mutate(()=>{frame().observations=frame().observations.filter(x=>x.id!==o.id);selected=null;});
  $('new-version').onclick = ()=>mutate(()=>{let n=1;while(track.versions[`V${String(n).padStart(3,'0')}`]!==undefined)n++;o.version_id=`V${String(n).padStart(3,'0')}`;track.versions[o.version_id]=o.visible_text;o.change='added';o.confirmed=false;});
  $('add-region').onclick = ()=>setTool('region');
  $('redraw-region').onclick = ()=>setTool('replace');
  $('split-item').onclick = ()=>splitItem();
  $('clear-regions').onclick = ()=>mutate(()=>{o.regions=[];o.confirmed=false;});
  $('remove-region').onclick = ()=>mutate(()=>{if(selectedRegion!==null)o.regions.splice(selectedRegion,1);selectedRegion=null;o.confirmed=false;});
}
function renderFramePanel() {
  const a=frame(), sid=a.scene_id;
  $('frame-panel').innerHTML = `<label>场景<select id="scene">${options(Object.entries(state.annotation.scenes).map(([id,s])=>[id,`${id} · ${s.name}`]),sid)}</select></label><button id="new-scene">新建场景</button><p class="hint">切场景前先清空或重新关联本帧条目。白板区域由同场景帧共享。</p><label>清晰度<select id="quality">${options([['clear','清晰'],['blur','模糊'],['uncertain','无法判断']],a.quality)}</select></label><label>人工 OCR 决策<select id="ocr-decision">${options([['recognize','应识别'],['skip','可跳过'],['uncertain','不确定']],a.ocr_decision)}</select></label><label>相对所选参考帧的变化</label>${[['unchanged','无变化'],['added','新增'],['erased','擦除'],['modified','修改 / 重写'],['cut','切镜头'],['uncertain','不确定']].map(([v,l])=>`<label class="checkline"><input type="checkbox" data-event="${v}" ${a.events.includes(v)?'checked':''} ${!a.reference_id?'disabled':''}>${l}</label>`).join('')}<label>遮挡区域</label><div id="occlusion-list">${a.occluders.map((_,i)=>`<div class="occlusion-row"><span>教师区域 ${i+1}</span><button data-delete-occlusion="${i}">删除</button></div>`).join('')}</div><p class="hint" id="coverage"></p><label>备注<textarea id="frame-note" rows="2">${esc(a.note)}</textarea></label><label class="checkline"><input id="reviewed" type="checkbox" ${a.reviewed?'checked':''}>已核验本帧、漏标及参考帧变化</label>`;
  $('scene').onchange = e => {
    if(a.observations.length){notice('请先清空或重新分配本帧条目，再切换场景',true);e.target.value=sid;return;}
    mutate(()=>{a.scene_id=e.target.value;a.reference_id=null;a.events=[];a.reviewed=false;});
  };
  $('new-scene').onclick = ()=>{
    if(a.observations.length)return notice('请先清空本帧条目再新建场景',true);
    mutate(()=>{let n=1;while(state.annotation.scenes[`S${String(n).padStart(2,'0')}`])n++;const id=`S${String(n).padStart(2,'0')}`;state.annotation.scenes[id]={name:id,board:clone(state.annotation.scenes[sid].board)};a.scene_id=id;a.reference_id=null;a.events=[];a.reviewed=false;});
  };
  $('quality').onchange=e=>mutate(()=>{a.quality=e.target.value;a.reviewed=false;});
  $('ocr-decision').onchange=e=>mutate(()=>{a.ocr_decision=e.target.value;a.reviewed=false;});
  $('frame-note').onchange=e=>mutate(()=>a.note=e.target.value);
  $('reviewed').onchange=e=>mutate(()=>a.reviewed=e.target.checked);
  $('frame-panel').querySelectorAll('[data-event]').forEach(el=>el.onchange=()=>mutate(()=>{const value=el.dataset.event;if(value==='unchanged')a.events=el.checked?['unchanged']:[];else{a.events=a.events.filter(v=>v!=='unchanged'&&v!==value);if(el.checked)a.events.push(value);}a.reviewed=false;}));
  $('frame-panel').querySelectorAll('[data-delete-occlusion]').forEach(el=>el.onclick=()=>mutate(()=>{a.occluders.splice(Number(el.dataset.deleteOcclusion),1);a.reviewed=false;}));
  coverage();
}
function coverage() {
  // 相同栅格上的并集 / 白板面积，避免重叠区域重复计数。
  const {width,height}=state.dataset.video, scale=Math.min(1,640/width), w=Math.round(width*scale),h=Math.round(height*scale);
  const board=document.createElement('canvas');board.width=w;board.height=h;
  const mask=document.createElement('canvas');mask.width=w;mask.height=h;
  const draw=(ctx,p)=>{ctx.beginPath();p.forEach(([x,y],i)=>i?ctx.lineTo(x*scale,y*scale):ctx.moveTo(x*scale,y*scale));ctx.closePath();ctx.fill();};
  draw(board.getContext('2d'),state.annotation.scenes[frame().scene_id].board);
  frame().occluders.forEach(p=>draw(mask.getContext('2d'),p));
  const b=board.getContext('2d').getImageData(0,0,w,h).data,m=mask.getContext('2d').getImageData(0,0,w,h).data;
  let total=0,covered=0;for(let i=3;i<b.length;i+=4)if(b[i]>127){total++;if(m[i]>127)covered++;}
  $('coverage').textContent=`白板遮挡比例约 ${total?(covered/total*100).toFixed(1):0}%（粗多边形并集估计）`;
}
let selectedRegion = null;
function polygonMarkup(poly,attrs){return `<polygon points="${poly.map(p=>p.join(',')).join(' ')}" ${attrs}/>`;}
function renderCanvas() {
  const {width,height}=state.dataset.video, a=frame();
  [$('canvas'),$('reference-svg')].forEach(el=>el.setAttribute('viewBox',`0 0 ${width} ${height}`));
  const zoom=Number($('zoom').value);$('current-wrap').style.width=`${zoom*100}%`;
  let html=polygonMarkup(state.annotation.scenes[a.scene_id].board,'fill="none" stroke="#65899c" stroke-width="1" stroke-dasharray="7 5" data-kind="board"');
  if($('show-occlusion').checked)a.occluders.forEach((p,i)=>{html+=polygonMarkup(p,`fill="#e4a12744" stroke="#e4a127" stroke-width="2" data-kind="occlusion" data-region="${i}"`);if(tool==='select')html+=handles(p,'occlusion',i);});
  if($('show-predictions').checked)(state.predictions[frameInfo().id]||[]).forEach((p,i)=>p.regions.forEach(poly=>html+=polygonMarkup(poly,`fill="#5274bc0a" stroke="#5274bc" stroke-width="1" stroke-dasharray="5 4" data-kind="prediction" data-prediction="${i}"`)));
  a.observations.forEach(o=>o.regions.forEach((p,i)=>{
    html+=polygonMarkup(p,`fill="${o.id===selected?'#00887922':'#00887908'}" stroke="#008879" stroke-width="${o.id===selected?2:1}" data-kind="observation" data-observation="${o.id}" data-region="${i}"`);
    if(o.id===selected){html+=`<text x="${p[0][0]}" y="${Math.max(18,p[0][1]-5)}">${esc(o.track_id)}</text>`;if(tool==='select')html+=handles(p,'observation',i,o.id);}
  }));
  if(points.length)html+=`<polyline points="${points.map(p=>p.join(',')).join(' ')}" fill="none" stroke="#d98400" stroke-width="2" vector-effect="non-scaling-stroke"/>`;
  $('canvas').innerHTML=html;
  const ref=a.reference_id?state.annotation.frames[a.reference_id]:null;
  $('reference-svg').innerHTML=ref?ref.observations.map(o=>o.regions.map(p=>polygonMarkup(p,'fill="#00887910" stroke="#008879" stroke-width="1"')).join('')).join(''):'';
}
function handles(poly,kind,region,oid='') {
  const radius=state.dataset.video.width/Math.max(1,$('canvas').getBoundingClientRect().width)*4;
  return poly.map(([x,y],i)=>`<circle cx="${x}" cy="${y}" r="${radius}" fill="white" stroke="${kind==='occlusion'?'#d98400':'#008879'}" data-kind="${kind}" data-region="${region}" data-observation="${oid}" data-vertex="${i}"/>`).join('');
}
function coordinate(event) {
  const p=new DOMPoint(event.clientX,event.clientY).matrixTransform($('canvas').getScreenCTM().inverse());
  return [Math.max(0,Math.min(state.dataset.video.width,p.x)),Math.max(0,Math.min(state.dataset.video.height,p.y))];
}
function acceptPrediction(i, append=false) {
  const p=(state.predictions[frameInfo().id]||[])[i];if(!p)return;
  if(append&&!observation())return notice('先选择要合入的条目',true);
  mutate(()=>{if(append){const o=observation();o.regions.push(...clone(p.regions));o.visible_text+=(o.visible_text?' ':'')+p.text;o.confirmed=false;}else newObservation(p.regions,p.text,{...p});});
}
$('canvas').addEventListener('pointerdown',e=>{
  if(!state||e.button!==0)return;
  const p=coordinate(e), el=e.target;
  if(tool==='occlusion'||tool==='board'){points.push(p);renderCanvas();return;}
  if(['rect','region','replace'].includes(tool)){
    if(['region','replace'].includes(tool)&&!observation())return notice('先选择条目再添加可见片段',true);
    gesture={type:'draw',start:p};points=[p,p];$('canvas').setPointerCapture(e.pointerId);return;
  }
  if(el.dataset.kind==='prediction'){acceptPrediction(Number(el.dataset.prediction));return;}
  if(el.dataset.kind==='observation'||el.dataset.kind==='occlusion'){
    if(el.dataset.kind==='observation'){selected=el.dataset.observation;selectedRegion=Number(el.dataset.region);}
    const poly=el.dataset.kind==='occlusion'?frame().occluders[Number(el.dataset.region)]:observation().regions[Number(el.dataset.region)];
    checkpoint();gesture={type:'edit',kind:el.dataset.kind,region:Number(el.dataset.region),vertex:el.dataset.vertex===undefined?null:Number(el.dataset.vertex),start:p,original:clone(poly)};
    $('canvas').setPointerCapture(e.pointerId);renderItems();renderInspector();renderCanvas();
  }else{selected=null;selectedRegion=null;renderItems();renderInspector();renderCanvas();}
});
$('canvas').addEventListener('pointermove',e=>{
  if(!gesture)return;
  const p=coordinate(e),g=gesture;
  if(g.type==='draw'){points=[g.start,[p[0],g.start[1]],p,[g.start[0],p[1]],g.start];renderCanvas();return;}
  const poly=g.kind==='occlusion'?frame().occluders[g.region]:observation().regions[g.region];
  if(g.vertex!==null)poly[g.vertex]=p;
  else{const {width,height}=state.dataset.video;const xs=g.original.map(q=>q[0]),ys=g.original.map(q=>q[1]);const dx=Math.max(-Math.min(...xs),Math.min(width-Math.max(...xs),p[0]-g.start[0])),dy=Math.max(-Math.min(...ys),Math.min(height-Math.max(...ys),p[1]-g.start[1]));poly.splice(0,poly.length,...g.original.map(([x,y])=>[x+dx,y+dy]));}
  renderCanvas();
});
$('canvas').addEventListener('pointerup',e=>{
  if(!gesture)return;
  const g=gesture;gesture=null;
  if(g.type==='draw'){
    const p=coordinate(e),[x,y]=g.start;
    if(Math.abs(p[0]-x)<3||Math.abs(p[1]-y)<3){points=[];renderCanvas();return;}
    const poly=[[Math.min(x,p[0]),Math.min(y,p[1])],[Math.max(x,p[0]),Math.min(y,p[1])],[Math.max(x,p[0]),Math.max(y,p[1])],[Math.min(x,p[0]),Math.max(y,p[1])]];
    mutate(()=>{if(['region','replace'].includes(tool)){if(tool==='replace')observation().regions=[poly];else observation().regions.push(poly);observation().confirmed=false;}else newObservation([poly]);});
    setTool('select');
  }else{if(g.kind==='observation')observation().confirmed=false;frame().reviewed=false;if(frame().status==='done')frame().status='draft';markDirty();render();}
});
function finishPolygon(){
  if(!state||!['occlusion','board'].includes(tool))return;
  if(points.length<3 || (tool==='board'&&points.length!==4))return notice('遮挡至少三个点；白板必须四个点',true);
  mutate(()=>{if(tool==='board'){state.annotation.scenes[frame().scene_id].board=clone(points);for(const f of Object.values(state.annotation.frames))if(f.scene_id===frame().scene_id){f.reviewed=false;if(f.status==='done')f.status='draft';}}else frame().occluders.push(clone(points));frame().reviewed=false;});setTool('select');
}
async function navigate(i){if(!state||i<0||i>=state.dataset.frames.length)return;await save();index=i;selected=null;selectedRegion=null;merged.clear();setTool('select');notice();render();}
function inherit(id){
  const ref=state.annotation.frames[frame().reference_id],source=ref?.observations.find(o=>o.id===id);if(!source)return;
  if(state.annotation.tracks[source.track_id].scene_id!==frame().scene_id)return notice('不同场景不能继承条目',true);
  if(frame().observations.some(o=>o.track_id===source.track_id))return notice('本帧已有此条目，可直接编辑或加入可见片段',true);
  mutate(()=>{const o=clone(source);o.id=uid();o.confirmed=false;o.change='unchanged';o.source={inherited_from:frame().reference_id};frame().observations.push(o);selected=o.id;});
}
function mergeItems(){
  const chosen=frame().observations.filter(o=>merged.has(o.id));if(chosen.length<2)return notice('至少勾选两个条目',true);
  mutate(()=>{const target=chosen[0];target.regions=chosen.flatMap(o=>o.regions);target.visible_text=chosen.map(o=>o.visible_text).join(' ');target.confirmed=false;frame().observations=frame().observations.filter(o=>!merged.has(o.id)||o===target);selected=target.id;merged.clear();});
}
function splitItem(){
  const o=observation();if(!o||!o.regions.length)return;
  const ys=o.regions.flat().map(p=>p[1]),suggested=(Math.min(...ys)+Math.max(...ys))/2;
  const raw=prompt('沿水平线拆为上下两条物理行。输入原图 y 坐标；拆分后分别修订文字与身份。',suggested.toFixed(1));
  if(raw===null)return;
  const cut=Number(raw);if(!Number.isFinite(cut)||cut<=Math.min(...ys)||cut>=Math.max(...ys))return notice('分割线必须穿过文字区域',true);
  const clip=(poly,upper)=>{
    const output=[];let previous=poly.at(-1),inside=p=>upper?p[1]<=cut:p[1]>=cut;
    for(const point of poly){
      if(inside(point)!==inside(previous)){const t=(cut-previous[1])/(point[1]-previous[1]);output.push([previous[0]+t*(point[0]-previous[0]),cut]);}
      if(inside(point))output.push([...point]);previous=point;
    }
    return output.length>=3?output:null;
  };
  const upper=o.regions.map(p=>clip(p,true)).filter(Boolean),lower=o.regions.map(p=>clip(p,false)).filter(Boolean);
  if(!upper.length||!lower.length)return notice('分割结果没有形成上下两个区域',true);
  mutate(()=>{o.regions=upper;o.confirmed=false;const lines=o.visible_text.split('\n'),multiline=lines.length>1;if(multiline)o.visible_text=lines.shift();newObservation(lower,multiline?lines.join('\n'):o.visible_text,{split_from:o.id});});
  notice('已拆为两个待确认条目，请分别修订文字；跨帧身份不会自动推断');
}
async function busy(button,fn){const text=button.textContent;button.disabled=true;button.textContent='处理中…';try{await fn();}catch(e){notice(e.message,true);}finally{button.disabled=false;button.textContent=text;}}
function download(value,name){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
// 委托事件：列表随标注更新重新渲染。
document.addEventListener('click',e=>{
  const target=e.target.closest('button,.frame-card,.item-row');if(!target)return;
  if(target.dataset.index!==undefined)navigate(Number(target.dataset.index)).catch(e=>notice(e.message,true));
  if(target.dataset.observation&& !e.target.dataset.merge){selected=target.dataset.observation;selectedRegion=null;renderItems();renderInspector();renderCanvas();}
  if(target.dataset.accept!==undefined)acceptPrediction(Number(target.dataset.accept));
  if(target.dataset.append!==undefined)acceptPrediction(Number(target.dataset.append),true);
  if(target.dataset.inherit)inherit(target.dataset.inherit);
  if(target.id==='merge-items')mergeItems();
  if(target.dataset.tool)setTool(target.dataset.tool);
  if(target.dataset.tab){tab=target.dataset.tab;$('item-panel').hidden=tab!=='item';$('frame-panel').hidden=tab!=='frame';document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));}
});
document.addEventListener('change',e=>{if(e.target.dataset.merge){if(e.target.checked)merged.add(e.target.dataset.merge);else merged.delete(e.target.dataset.merge);}});
$('tasks').onchange=e=>openTask(e.target.value).catch(err=>notice(err.message,true));
$('create').onclick=$('empty-create').onclick=()=>$('create-dialog').showModal();
$('cancel-create').onclick=()=>$('create-dialog').close();
$('help').onclick=()=>$('help-dialog').showModal();$('close-help').onclick=()=>$('help-dialog').close();
$('create-form').onsubmit=e=>{
  e.preventDefault();const data=new FormData(e.target),button=e.target.querySelector('[type=submit]');
  busy(button,async()=>{
    await save();
    const parse=(value,n)=>String(value).split('\n').filter(l=>l.trim()).map(l=>{const p=l.split(/[,，]/).map(s=>s.trim());if(p.length!==n)throw new Error('每行字段数量不正确');return p;});
    const segments=parse(data.get('segments'),3).map(([start,end,interval])=>({start:Number(start),end:Number(end),interval:Number(interval)}));
    const extras=parse(data.get('extras'),2).map(([time,scene_id])=>({time:Number(time),scene_id}));
    const result=await api('/api/tasks',{id:data.get('id'),title:data.get('title'),video:data.get('video'),segments,extras});
    $('create-dialog').close();await refreshTasks();await openTask(result.dataset.id);$('tasks').value=result.dataset.id;
  });
};
$('reference').onchange=e=>mutate(()=>{frame().reference_id=e.target.value||null;frame().events=[];frame().reviewed=false;});
$('show-predictions').onchange=$('show-occlusion').onchange=$('zoom').onchange=()=>renderCanvas();
$('prev').onclick=()=>navigate(index-1).catch(e=>notice(e.message,true));$('next').onclick=()=>navigate(index+1).catch(e=>notice(e.message,true));
$('undo').onclick=()=>{if(undoStack.length)restore(undoStack.pop(),redoStack);};$('redo').onclick=()=>{if(redoStack.length)restore(redoStack.pop(),undoStack);};
$('draft').onclick=()=>mutate(()=>frame().status='draft');
$('hidden-item').onclick=()=>mutate(()=>newObservation());
$('done').onclick=()=>busy($('done'),async()=>{
  if(!state)return;checkpoint();frame().status='done';markDirty();
  try{await save();notice('本帧已完成');render();}catch(e){frame().status='draft';markDirty();render();throw e;}
});
$('import-annotation').onclick=()=>{if(state)$('annotation-file').click();else notice('先打开与备份对应的任务',true);};
$('annotation-file').onchange=async e=>{
  const file=e.target.files[0];if(!file)return;
  try{
    const data=JSON.parse(await file.text()),ann=data.annotation;
    if(!ann||ann.dataset_id!==state.dataset.id||ann.video_sha256!==state.dataset.video.sha256)throw new Error('备份与当前任务或视频指纹不一致');
    if(!confirm('用备份恢复当前任务？当前状态会保留为上一个有效版本，并可撤销。'))return;
    await save();const revision=state.annotation.revision;checkpoint();state.annotation=ann;state.annotation.revision=revision;selected=null;markDirty();
    try{await save();render();notice('已恢复标注');}catch(err){state.annotation=undoStack.pop();markDirty();render();throw err;}
  }catch(err){notice(err.message,true);}finally{e.target.value='';}
};
$('export').onclick=async()=>{
  if(!state)return;
  if(blocked){download({dataset:state.dataset,annotation:state.annotation,unsaved_draft:true},state.dataset.id+'-draft.json');return;}
  try{await save();download(await api(taskURL('export')),state.dataset.id+'-annotations.json');notice('已导出任务与人工标注');}catch(e){download({dataset:state.dataset,annotation:state.annotation,unsaved_draft:true},state.dataset.id+'-draft.json');notice('保存失败，已导出本页草稿：'+e.message,true);}
};
$('ocr').onclick=()=>busy($('ocr'),async()=>{if(!state)return;await save();const task=state.dataset.id;notice('正在识别当前原帧，首次加载模型可能需要一些时间…');const result=await api(taskURL('ocr'),{frame_id:frameInfo().id});if(state.dataset.id!==task)return;state.predictions=result.predictions;notice('OCR 完成；人工标注保持独立，请核验预测后接受');render();});
$('import-run').onclick=()=>{if(!state)return;const run=prompt('运行目录（相对项目）','runs/items_trial_v1');if(!run)return;busy($('import-run'),async()=>{await save();const task=state.dataset.id;const result=await api(taskURL('import-run'),{run});if(state.dataset.id!==task)return;state.predictions=result.data.predictions;notice(`已导入 ${result.frames} 帧 / ${result.imported} 个预测框；未覆盖人工标注`);render();});};
$('regenerate').onclick=()=>busy($('regenerate'),async()=>{if(!state)return;await save();await api(taskURL('regenerate'),{});notice('已按视频指纹重建原帧缓存');render();});
function seekVideo(time){
  if(!state)return;
  const video=$('video');
  if(!video.getAttribute('src')){
    video.src=taskURL('video');
    video.addEventListener('loadedmetadata',()=>{video.currentTime=time;},{once:true});
  }else video.currentTime=time;
}
$('video-details').ontoggle=()=>{if($('video-details').open)seekVideo(frameInfo().time);else $('video').pause();};
$('seek-current').onclick=()=>seekVideo(frameInfo().time);
$('seek-reference').onclick=()=>{const ref=state?.dataset.frames.find(f=>f.id===frame().reference_id);if(ref)seekVideo(ref.time);};
$('current-image').onerror=()=>notice('当前帧图片缺失，可点击“重建图片”恢复',true);
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
window.addEventListener('keydown',e=>{
  const editing=['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName);
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();save().catch(err=>notice(err.message,true));return;}
  if(editing||document.querySelector('dialog[open]'))return;
  if(e.key==='Escape'){points=[];gesture=null;setTool('select');}
  if(e.key==='Enter'&&points.length){e.preventDefault();finishPolygon();}
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();if(e.shiftKey)$('redo').click();else $('undo').click();}
  if(e.key==='ArrowLeft'){e.preventDefault();$('prev').click();}if(e.key==='ArrowRight'){e.preventDefault();$('next').click();}
});
window.addEventListener('error',e=>notice(e.message,true));
window.addEventListener('unhandledrejection',e=>notice(e.reason?.message||'操作失败',true));
refreshTasks().then(()=>{const id=localStorage.getItem('annotation-task');if(id&&[...$('tasks').options].some(o=>o.value===id))return openTask(id);}).catch(e=>notice(e.message,true));
