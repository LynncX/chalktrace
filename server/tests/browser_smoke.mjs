#!/usr/bin/env node
/** Background: 2026-11-09, verify Web upload, ROI, real OCR, evidence and refresh without installing a browser library.
 * Usage: node server/tests/browser_smoke.mjs --url http://127.0.0.1:8001 --video /absolute/clip.mp4 [--screenshot /tmp/web.png]
 */
import {spawn} from 'node:child_process';
import {mkdtemp,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import assert from 'node:assert/strict';
const args=process.argv.slice(2);
if(args.includes('--help')||args.includes('-h')){console.log('Usage: browser_smoke.mjs --url URL (--video PATH | --job ID) [--screenshot PATH]');process.exit(0);}
const arg=(key,fallback)=>{const i=args.indexOf(key);return i>=0?args[i+1]:fallback;};
const url=arg('--url','http://127.0.0.1:8001');
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
  await wait(()=>evaluate(`document.readyState==='complete' && typeof openJob==='function'`));
  if(arg('--job')){await evaluate(`openJob(${JSON.stringify(arg('--job'))})`);}else{
  await send('DOM.enable');
  await wait(()=>evaluate(`document.readyState==='complete'`));
  const input=await send('Runtime.evaluate',{expression:"document.getElementById('file')"});
  assert.ok(arg('--video'),'--video required (absolute path)');
  await send('DOM.setFileInputFiles',{objectId:input.result.objectId,files:[arg('--video')]});
  await wait(()=>evaluate(`document.getElementById('preview').readyState>=2`));
  const box=await evaluate(`(()=>{const r=document.getElementById('roi-canvas').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};})()`);
  const mouse=async(type,x,y,buttons=0)=>send('Input.dispatchMouseEvent',{type,x,y,button:type==='mouseMoved'?'none':'left',buttons,clickCount:1});
  await mouse('mousePressed',box.x+box.width*.20,box.y+box.height*.025,1);
  await mouse('mouseMoved',box.x+box.width*.80,box.y+box.height*.24,1);
  await mouse('mouseReleased',box.x+box.width*.80,box.y+box.height*.24);
  const roi=await evaluate('roi');
  assert.equal(roi.length,4);assert.ok(roi[2]>700 && roi[3]>100,JSON.stringify(roi));
  await evaluate(`document.getElementById('frames').value='2';document.getElementById('upload-form').requestSubmit()`);
  await wait(()=>evaluate(`!!current`));
  }
  const id=await evaluate('current');
  const until=Date.now()+180000;
  while(Date.now()<until){
    const state=await (await fetch(`${url}/api/jobs/${id}`)).json();
    if(state.status==='failed')throw new Error(state.error);
    if(state.status==='done')break;
    await new Promise(r=>setTimeout(r,500));
  }
  await wait(()=>evaluate(`document.getElementById('status').textContent==='已完成'`));
  const count=await evaluate(`document.querySelectorAll('.item').length`);
  assert.ok(count>0,'real OCR should produce items');
  await evaluate(`document.querySelectorAll('.item')[Math.min(1,document.querySelectorAll('.item').length-1)].click()`);
  await wait(()=>evaluate(`document.getElementById('crop').complete && document.getElementById('crop').naturalWidth>0 && document.getElementById('source').naturalWidth>0`));
  const ts=await evaluate(`manifest.items.find(x=>x.item_id===selected).best.ts`);
  assert.ok(Math.abs(await evaluate(`document.getElementById('player').currentTime`)-ts)<.3);
  const download=await evaluate(`document.getElementById('download-txt').href`);
  const response=await fetch(download);assert.equal(response.status,200);assert.ok((await response.text()).length>20);
  assert.ok(response.headers.get('content-disposition').includes('attachment'));
  await send('Page.reload');
  await wait(()=>evaluate(`document.getElementById('status').textContent==='已完成' && document.querySelectorAll('.item').length>0`));
  assert.equal(await evaluate('current'),id);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({result:arg('--job')?'PASS: existing result, evidence, seek, download, refresh':'PASS: upload, ROI, real OCR, evidence, seek, download, refresh',job_id:id,items:count}));
  if(arg('--screenshot')){
    const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
    await writeFile(arg('--screenshot'),Buffer.from(shot.data,'base64'));
  }
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  assert.ok(await evaluate(`document.documentElement.scrollWidth<=window.innerWidth`),'mobile horizontal overflow');
}finally{
  if(ws)ws.close();
  if(chrome){chrome.kill();await new Promise(resolve=>{if(chrome.exitCode!==null)resolve();else{chrome.once('exit',resolve);setTimeout(resolve,3000);}});}
  await rm(profile,{recursive:true,force:true});
}
