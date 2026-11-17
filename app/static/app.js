const $ = id => document.getElementById(id);
let token = '', tenant = '', session = '', busy = false;
async function api(path, options={}) {
  const r = await fetch(path,{...options,headers:{...(options.headers||{}),Authorization:`Bearer ${token}`}});
  if(!r.ok){let message=`Request failed (${r.status})`;try{message=(await r.json()).detail||message}catch{}throw new Error(message)}
  return r.json();
}
function setError(message){$('connection').textContent=message;$('connection').className='error'}
function setReady(){const ok=!!tenant;$('new').disabled=!ok;$('question').disabled=!ok;$('send').disabled=!ok||busy;$('tenant-pill').textContent=tenant?tenant.replaceAll('-',' '):'No tenant selected';$('heading').textContent=tenant?`${tenant.replaceAll('-',' ')} knowledge`:'Ask your documents'}
function clearMessages(){ $('messages').innerHTML=''; }
function welcome(){ $('messages').innerHTML='<div class="welcome"><div class="welcome-icon">✦</div><h2>Ask a question to get started.</h2><p>Search procedures and workbook values in the selected tenant’s files.</p></div>'; }
function addMessage(role,content,status,sources=[]){
  if($('messages').querySelector('.welcome'))clearMessages();
  const box=document.createElement('div');box.className=`message ${role}`;
  if(role==='user'){box.textContent=content}else{
    const state=document.createElement('div');state.className=`status ${status||'partial'}`;state.textContent=status||'Answer';box.append(state);
    const answer=document.createElement('div');answer.className='answer';answer.textContent=content;box.append(answer);
    if(sources.length){const detail=document.createElement('details');detail.className='source-list';const summary=document.createElement('summary');summary.textContent=`${sources.length} source${sources.length===1?'':'s'}`;detail.append(summary);
      for(const src of sources){const el=document.createElement('div');el.className='source';const strong=document.createElement('strong');strong.textContent=src.filename;el.append(strong);el.append(document.createTextNode(`${src.location} · version ${src.version||1}`));const dl=document.createElement('button');dl.className='download';dl.textContent='Download source';dl.onclick=async()=>{try{const r=await fetch(`/api/tenants/${tenant}/documents/${src.document_id}/download`,{headers:{Authorization:`Bearer ${token}`}});if(!r.ok)throw new Error('Download failed');const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download=src.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),60000)}catch(e){setError(e.message)}};el.append(dl);
        if(src.cells?.length){const cells=document.createElement('div');cells.textContent=src.cells.map(c=>`${c.coordinate}: ${c.value??'cached result unavailable'}`).join(' · ');el.append(cells)}detail.append(el)}box.append(detail)}
    const actions=document.createElement('div');actions.className='actions';const copy=document.createElement('button');copy.textContent='Copy';copy.onclick=()=>navigator.clipboard.writeText(content);actions.append(copy);
    for(const rating of ['helpful','incomplete','incorrect']){const button=document.createElement('button');button.textContent=rating;button.onclick=async()=>{try{await api(`/api/sessions/${session}/feedback`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rating,note:''})});button.textContent='Saved'}catch(e){setError(e.message)}};actions.append(button)}box.append(actions)
  }
  $('messages').append(box);$('messages').scrollTop=$('messages').scrollHeight;
}
async function refreshSessions(){if(!tenant)return;const list=await api(`/api/sessions?tenant_id=${encodeURIComponent(tenant)}`);$('sessions').innerHTML='';for(const item of list){const btn=document.createElement('button');btn.textContent=`Conversation · ${new Date(item.created_at).toLocaleString()}`;btn.className=item.id===session?'active':'';btn.onclick=()=>openSession(item.id);$('sessions').append(btn)}}
async function openSession(id){session=id;const messages=await api(`/api/sessions/${id}/messages`);clearMessages();if(!messages.length)welcome();for(const item of messages)addMessage(item.role,item.content,item.status,item.sources||[]);await refreshSessions()}
async function createSession(){const item=await api('/api/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tenant_id:tenant})});session=item.id;welcome();await refreshSessions();$('question').focus()}
$('connect').onclick=async()=>{token=$('token').value.trim();try{const tenants=await api('/api/tenants');$('tenant').innerHTML='';for(const t of tenants){const option=document.createElement('option');option.value=t.id;option.textContent=t.name;$('tenant').append(option)}$('tenant').disabled=!tenants.length;tenant=tenants[0]?.id||'';session='';$('connection').textContent=tenants.length?'Connected':'No assigned tenants';$('connection').className='';setReady();if(tenant){await createSession()}}catch(e){token='';tenant='';setReady();setError(e.message)}};
$('tenant').onchange=async()=>{tenant=$('tenant').value;session='';setReady();try{await createSession()}catch(e){setError(e.message)}};
$('new').onclick=async()=>{try{await createSession()}catch(e){setError(e.message)}};
$('composer').onsubmit=async e=>{e.preventDefault();const question=$('question').value.trim();if(!question||busy||!session)return;busy=true;setReady();$('question').value='';addMessage('user',question);const pending=document.createElement('div');pending.className='message assistant';pending.textContent='Searching the tenant documents…';$('messages').append(pending);try{const result=await api(`/api/sessions/${session}/messages`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:question})});pending.remove();addMessage('assistant',result.answer,result.status,result.sources);await refreshSessions()}catch(err){pending.remove();addMessage('assistant',err.message,'partial')}finally{busy=false;setReady();$('question').focus()}};
$('question').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('composer').requestSubmit()}};
