// PMS UI wiring for Flask APIs
card.style.justifyContent = 'space-between';
card.style.alignItems = 'center';
card.style.margin = '8px 0';
card.innerHTML = `<strong>Bundle #${escapeHtml(b.code)}</strong><span class="department-tag">Qty: ${b.qty}</span>`;
col.appendChild(card);
});
grid.appendChild(col);
});
}


// Uploads
$('#uploadObBtn')?.addEventListener('click', async ()=>{
const f = $('#obFileInput').files[0];
if(!f){ $('#obUploadStatus').textContent = 'Pick a file first.'; return; }
const fd = new FormData(); fd.append('file', f);
const r = await fetch('/api/upload/ob', { method:'POST', body: fd });
$('#obUploadStatus').textContent = r.ok ? 'Uploaded ✓' : 'Failed';
});
$('#uploadPoBtn')?.addEventListener('click', async ()=>{
const f = $('#poFileInput').files[0];
if(!f){ $('#poUploadStatus').textContent = 'Pick a file first.'; return; }
const fd = new FormData(); fd.append('file', f);
const r = await fetch('/api/upload/po', { method:'POST', body: fd });
$('#poUploadStatus').textContent = r.ok ? 'Uploaded ✓' : 'Failed';
});


// ESP32 simulate
$('#simulateScanBtn')?.addEventListener('click', async ()=>{
const token = $('#simulateToken').value.trim();
const type = $('#simulateType').value;
if(!token){ $('#scanResult').textContent = 'Enter a token id'; return; }
const r = await fetch('/scan', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ token_id: token, secret: '" + (window.DEVICE_SECRET || '') + "', scan_type: type }) });
const j = await r.json();
$('#scanResult').textContent = j.status === 'success' ? `${j.message} — ${j.name}` : (j.message || 'Failed');
await loadActivities();
});


// Mock charts (reports page)
async function drawProductivityMock(){
const ctx = document.getElementById('productivityChart');
if(!ctx) return;
const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const pieces = months.map(()=> Math.floor(250 + Math.random()*700));
const minutes = months.map(()=> Math.floor(600 + Math.random()*900));
new Chart(ctx, { type:'line', data:{ labels:months, datasets:[ {label:'Pieces', data:pieces, tension:.35, fill:true, borderColor:'#7c5cff', backgroundColor:'rgba(124,92,255,.18)'}, {label:'Minutes', data:minutes, tension:.35, borderColor:'#22c55e'} ] }, options:{ plugins:{ legend:{ labels:{ color:'#cfe1ff' } } }, scales:{ x:{ ticks:{ color:'#cfe1ff' } }, y:{ ticks:{ color:'#cfe1ff' } } } } });
}
async function drawEarningsMock(){
const wrap = $('#earningsSummary');
if(!wrap) return;
const depts = ['SLEEVE','COLLAR','LINING','BODY','ASSE-1','ASSE-2','FLAP','BACK'];
wrap.innerHTML = '';
depts.forEach(d => {
const row = document.createElement('div');
row.className = 'earning-row';
row.style.display = 'flex';
row.style.justifyContent = 'space-between';
row.innerHTML = `<span>${d}</span><strong>${currency(12000 + Math.random()*30000)}</strong>`;
wrap.appendChild(row);
});
}


function escapeHtml(str){
return String(str||'').replace(/[&<>"']/g, s=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;' }[s]));
}