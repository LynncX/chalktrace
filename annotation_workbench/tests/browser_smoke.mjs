#!/usr/bin/env node
/** Background: 2026-11-09, verify real browser editing and persistence without installing a browser library.
 * Usage: node annotation_workbench/tests/browser_smoke.mjs --url http://127.0.0.1:8765 --task ui_smoke [--screenshot /tmp/annotation.png] [--view-only]
 */
import {spawn} from 'node:child_process';
import {mkdtemp,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import assert from 'node:assert/strict';
const args=process.argv.slice(2);
if(args.includes('--help')||args.includes('-h')){console.log('Usage: browser_smoke.mjs --url URL --task ID [--screenshot PATH] [--view-only]');process.exit(0);}
const arg=(key,fallback)=>{const i=args.indexOf(key);return i>=0?args[i+1]:fallback;};
const url=arg('--url','http://127.0.0.1:8765'),task=arg('--task','ui_smoke');
const profile=await mkdtemp(join(tmpdir(),'annotation-browser-'));
let chrome,ws;
try{
  let stderr='';
  chrome=spawn('/usr/bin/google-chrome',['--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-first-run','--disable-background-networking','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{stdio:['ignore','ignore','pipe']});
  chrome.stderr.on('data',b=>stderr+=b);
  const wait=async fn=>{const until=Date.now()+15000;while(Date.now()<until){const v=await fn();if(v)return v;await new Promise(r=>setTimeout(r,70));}throw new Error('Timed out: '+stderr.slice(-700));};
  const endpoint=await wait(()=>stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/)?.[1]);
  const origin=new URL(endpoint);const tabs=await (await fetch(`http://${origin.host}/json/list`)).json();
  ws=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  let seq=0;const pending=new Map(),errors=[];
  ws.onmessage=event=>{const data=JSON.parse(event.data);if(data.id){const p=pending.get(data.id);pending.delete(data.id);data.error?p.reject(new Error(JSON.stringify(data.error))):p.resolve(data.result);}if(data.method==='Runtime.exceptionThrown')errors.push(data.params.exceptionDetails.text+': '+data.params.exceptionDetails.exception?.description);};
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
  await send('Runtime.enable');await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1050,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url});
  await wait(()=>evaluate(`!!document.getElementById('tasks') && document.getElementById('tasks').options.length>1`));
  await evaluate(`openTask(${JSON.stringify(task)})`);
  await wait(()=>evaluate(`!document.getElementById('workspace').hidden && document.getElementById('current-image').complete`));
  if(!args.includes('--view-only')){
    // 通过页面事件接受 OCR 预测，再通过表单确认和保存。
    await evaluate(`document.querySelector('[data-accept="0"]').click()`);
    assert.equal(await evaluate(`frame().observations.length`),1);
    await evaluate(`document.getElementById('visible-text').value='manually corrected';document.getElementById('visible-text').dispatchEvent(new Event('change'));`);
    await evaluate(`document.getElementById('confirmed').click();document.querySelector('[data-tab="frame"]').click();document.getElementById('reviewed').click();`);
    await evaluate(`document.getElementById('done').click()`);
    await wait(()=>evaluate(`!dirty && frame().status==='done'`));
    assert.equal(await evaluate(`frame().observations[0].visible_text`),'manually corrected');
    await evaluate(`navigate(1)`);
    await evaluate(`document.querySelector('[data-inherit]').click()`);
    assert.equal(await evaluate(`frame().observations[0].track_id`),'S01-L001');
    // 新增可见片段：使用真正的鼠标输入，验证显示坐标到原图坐标的转换。
    await evaluate(`document.querySelector('[data-tab="item"]').click();document.getElementById('add-region').click();`);
    const box=await evaluate(`(()=>{const r=document.getElementById('canvas').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};})()`);
    const mouse=async(type,x,y,buttons=0)=>send('Input.dispatchMouseEvent',{type,x,y,button:type==='mouseMoved'?'none':'left',buttons,clickCount:1});
    await mouse('mousePressed',box.x+box.width*.55,box.y+box.height*.5,1);
    await mouse('mouseMoved',box.x+box.width*.8,box.y+box.height*.7,1);
    await mouse('mouseReleased',box.x+box.width*.8,box.y+box.height*.7);
    assert.equal(await evaluate(`frame().observations[0].regions.length`),2);
    const region=await evaluate(`frame().observations[0].regions[1]`);
    assert.ok(Math.abs(region[0][0]-88)<1);
    // 拆分/合并不依赖 OCR 框数量；所有结果仍待人工确认。
    await evaluate(`window.prompt=()=> '40';document.getElementById('split-item').click()`);
    assert.equal(await evaluate(`frame().observations.length`),2);
    await evaluate(`document.querySelectorAll('[data-merge]').forEach(el=>el.click());document.getElementById('merge-items').click()`);
    assert.equal(await evaluate(`frame().observations.length`),1);
    assert.equal(await evaluate(`frame().observations[0].regions.length`),2);
    await evaluate(`document.getElementById('new-version').click()`);
    assert.equal(await evaluate(`frame().observations[0].version_id`),'V002');
    // 多边形绘制、遮挡比例以及撤销/重做。
    await evaluate(`setTool('occlusion')`);
    for(const [x,y] of [[.1,.5],[.3,.5],[.3,.9],[.1,.9]]){
      await mouse('mousePressed',box.x+box.width*x,box.y+box.height*y,1);
      await mouse('mouseReleased',box.x+box.width*x,box.y+box.height*y);
    }
    await evaluate(`finishPolygon()`);
    assert.equal(await evaluate(`frame().occluders.length`),1);
    await evaluate(`document.getElementById('undo').click()`);
    assert.equal(await evaluate(`frame().occluders.length`),0);
    await evaluate(`document.getElementById('redo').click()`);
    assert.equal(await evaluate(`frame().occluders.length`),1);
    await evaluate(`save()`);
    // 刷新必须从服务端恢复相同人工修改，而不是浏览器内存。
    await send('Page.reload');
    await wait(()=>evaluate(`typeof state!=='undefined' && !!state`));
    assert.equal(await evaluate(`state.annotation.frames[state.dataset.frames[0].id].status`),'done');
    assert.equal(await evaluate(`state.annotation.frames[state.dataset.frames[1].id].observations[0].regions.length`),2);
    // 备份恢复使用的完整标注结构可被服务端再次校验。
    const exported=await (await fetch(`${url}/api/tasks/${task}/export`)).json();
    assert.equal(exported.annotation.tracks['S01-L001'].versions.V001,'first line');
    console.log('PASS: OCR revision, frame review, inheritance, drawing, split/merge, versions, occlusion, undo/redo, persistence and export');
  }else{
    await evaluate(`navigate(Math.min(2,state.dataset.frames.length-1))`);
    await wait(()=>evaluate(`document.getElementById('current-image').complete`));
  }
  assert.deepEqual(errors,[]);
  if(arg('--screenshot')){
    const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
    await writeFile(arg('--screenshot'),Buffer.from(shot.data,'base64'));
    console.log('Screenshot:',arg('--screenshot'));
  }
}finally{
  if(ws)ws.close();
  if(chrome){chrome.kill();await new Promise(resolve=>{if(chrome.exitCode!==null)resolve();else{chrome.once('exit',resolve);setTimeout(resolve,3000);}});}
  await rm(profile,{recursive:true,force:true});
}
