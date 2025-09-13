/* ===========================
   PMS — Feature JS (Chart.js)
   Works with your existing HTML
   =========================== */

// ---------- Utilities ----------
const $ = (s)=>document.querySelector(s);
const $$ = (s)=>Array.from(document.querySelectorAll(s));
const rand = (min,max)=> Math.floor(Math.random()*(max-min+1))+min;
const currency = n => `₹${Number(n).toFixed(2)}`;
const nowTime = ()=> new Date().toLocaleTimeString();

// ---------- Sidebar toggle ----------
const sidebar = $('#sidebar');
const toggleBtn = $('#sidebarToggle');
toggleBtn?.addEventListener('click', ()=>{
  sidebar.classList.toggle('collapsed');
  // push content under
  const main = document.querySelector('.main-content');
  if (window.innerWidth > 1024) {
    main.style.marginLeft = sidebar.classList.contains('collapsed') ? '0' : '260px';
  }
});

// ---------- Section nav ----------
$$('.nav-link').forEach(link=>{
  link.addEventListener('click', (e)=>{
    e.preventDefault();
    const sectionId = link.dataset.section;
    $$('.section').forEach(s=>s.classList.remove('active'));
    $$('#sidebar .nav-link').forEach(a=>a.classList.remove('active'));
    link.classList.add('active');
    document.getElementById(sectionId).classList.add('active');
    document.getElementById(sectionId).scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
});

// ---------- Mock Data ----------
const departments = ["SLEEVE","COLLAR","LINING","BODY","ASSE-1","ASSE-2","FLAP","BACK","POST ASSEMBLY"];

const workers = Array.from({length: 28}).map((_,i)=>({
  name: `Worker ${i+1}`,
  token: String(1000+i),
  department: departments[i%departments.length],
  line: `Line-${(i%4)+1}`,
  status: Math.random()>.2 ? "Active" : "Idle"
}));

const operations = Array.from({length: 40}).map((_,i)=>({
  seq: i+1,
  opNo: 200+i,
  description: `Operation step ${i+1} — sample description for visual`, 
  machine: ["SNLS","OL","FOA","BH","BARTACK"][i%5],
  department: departments[i%departments.length],
  stdMin: (Math.random()*2 + .3).toFixed(2),
  rate: (Math.random()*2 + .6).toFixed(2),
}));

const bundles = [
  { id: "A12", qty: 28, status: "Pending" },
  { id: "B04", qty: 22, status: "Pending" },
  { id: "C09", qty: 20, status: "Pending" },
  { id: "A01", qty: 30, status: "In Progress" },
  { id: "B11", qty: 26, status: "In Progress" },
  { id: "C02", qty: 18, status: "In Progress" },
  { id: "D07", qty: 33, status: "In Progress" },
  { id: "A05", qty: 16, status: "QA" },
  { id: "C03", qty: 14, status: "QA" },
  { id: "A08", qty: 25, status: "Completed" },
  { id: "B06", qty: 27, status: "Completed" },
  { id: "C12", qty: 21, status: "Completed" },
  { id: "D01", qty: 24, status: "Completed" },
  { id: "E03", qty: 19, status: "Completed" },
];

const activitySeed = [
  "Bundle #A12 assigned to Worker 7",
  "QA passed for Bundle #B04",
  "Operation 214 updated",
  "Worker 3 clocked in",
  "Worker 5 completed task",
  "New PO uploaded",
  "Scanner sync complete",
  "Bundle #C09 moved to QA",
];

// ---------- Dashboard KPIs ----------
function renderKPIs(){
  $('#activeWorkers').textContent = workers.filter(w => w.status === 'Active').length;
  $('#totalBundles').textContent = bundles.length;
  $('#totalOperations').textContent = operations.length;
  const earnings = workers.reduce((acc,_,i)=> acc + 200 + (i%5)*10, 0);
  $('#totalEarnings').textContent = currency(earnings);
}
renderKPIs();

// ---------- Last updated ----------
function stampUpdate(){
  $('#lastUpdate').textContent = nowTime();
}
stampUpdate();
$('#refreshData').addEventListener('click', ()=>{
  stampUpdate();
  // small pulse animation
  $('#refreshData').animate([{ transform: 'rotate(0deg)' },{ transform: 'rotate(360deg)' }], { duration: 600 });
});

// ---------- Charts (Chart.js) ----------
const palette = ['#7c5cff', '#22c55e', '#f59e0b', '#ef4444', '#5b8dff', '#8b5cf6'];

const bundleStatusCounts = ["Pending","In Progress","QA","Completed"].map(s => bundles.filter(b => b.status===s).length);

const bundleCtx = document.getElementById('bundleStatusChart');
new Chart(bundleCtx, {
  type: 'doughnut',
  data: {
    labels: ["Pending","In Progress","QA","Completed"],
    datasets: [{ data: bundleStatusCounts, backgroundColor: palette.slice(0,4), borderWidth: 0 }]
  },
  options: { plugins: { legend: { labels: { color: '#cfe1ff' } } } }
});

const deptLoads = departments.map(d => rand(20,100));
const deptCtx = document.getElementById('departmentChart');
new Chart(deptCtx, {
  type: 'bar',
  data: {
    labels: departments,
    datasets: [{ label: 'Queued pieces', data: deptLoads, backgroundColor: '#5b8dff' }]
  },
  options: {
    scales: { x: { ticks: { color: '#cfe1ff' }}, y: { ticks: { color: '#cfe1ff' }}},
    plugins: { legend: { labels: { color: '#cfe1ff' } } }
  }
});

// ---------- Activity Feed ----------
function renderActivity(){
  const feed = $('#activityFeed');
  feed.innerHTML = '';
  activitySeed.map((text,i)=>({ text, time: `${rand(2,58)} min ago` }))
    .forEach(a=>{
      const div = document.createElement('div');
      div.className = 'activity-item';
      div.innerHTML = `<span>🟣</span>
        <div><div>${a.text}</div><time>${a.time}</time></div>`;
      feed.appendChild(div);
    });
}
renderActivity();

// ---------- Workers Table ----------
function renderWorkersTable(){
  const tbody = $('#workersTableBody');
  const q = ($('#workerSearch').value || '').toLowerCase();
  const dept = $('#departmentFilter').value;
  tbody.innerHTML = '';
  workers
    .filter(w => (dept? w.department === dept : true) && (q? `${w.name} ${w.token} ${w.department} ${w.line}`.toLowerCase().includes(q) : true))
    .forEach(w=>{
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${w.name}</td>
        <td>${w.token}</td>
        <td><span class="badge">${w.department}</span></td>
        <td>${w.line}</td>
        <td>
          <span class="badge" style="border-color:${w.status==='Active'?'#1f9d63':'#4a5b8a'};color:${w.status==='Active'?'#8df0c4':'#a9b6d8'}">
            <span style="display:inline-block;width:8px;height:8px;border-radius:999px;background:${w.status==='Active'?'#22c55e':'#7f8fb4'}"></span>
            ${w.status}
          </span>
        </td>
        <td><button class="btn btn--secondary" data-qr="${w.token}" data-name="${w.name}">Show</button></td>
        <td><button class="btn btn--primary" data-action="assign" data-token="${w.token}">Assign</button></td>
      `;
      tbody.appendChild(tr);
    });
}
renderWorkersTable();

$('#workerSearch').addEventListener('input', renderWorkersTable);
$('#departmentFilter').addEventListener('change', renderWorkersTable);

// ---------- Operations Table ----------
function renderOperationsTable(){
  const tbody = $('#operationsTableBody');
  const filter = $('#operationsFilter').value;
  tbody.innerHTML = '';
  operations
    .filter(op => filter ? op.department === filter : true)
    .forEach(op=>{
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${op.seq}</td>
        <td>${op.opNo}</td>
        <td title="${op.description}">${op.description}</td>
        <td>${op.machine}</td>
        <td><span class="badge">${op.department}</span></td>
        <td>${op.stdMin}</td>
        <td>${Number(op.rate).toFixed(2)}</td>
      `;
      tbody.appendChild(tr);
    });
}
renderOperationsTable();
$('#operationsFilter').addEventListener('change', renderOperationsTable);

// ---------- Bundles Grid ----------
function renderBundles(){
  const grid = $('#bundlesGrid');
  grid.innerHTML = '';
  const groups = ["Pending","In Progress","QA","Completed"];
  groups.forEach(group=>{
    const column = document.createElement('div');
    column.className = 'card';
    column.innerHTML = `
      <div class="card__header"><h3>${group}</h3></div>
      <div class="card__body" data-col="${group}"></div>
    `;
    const wrap = column.querySelector('.card__body');
    bundles.filter(b=>b.status===group).forEach(b=>{
      const pct = group === 'Completed' ? 100 : rand(10,90);
      const card = document.createElement('div');
      card.className = 'bundle';
      card.innerHTML = `
        <div class="bundle__hdr">
          <strong>Bundle #${b.id}</strong>
          <span class="badge">Qty: ${b.qty}</span>
        </div>
        <div class="progress"><span style="width:${pct}%"></span></div>
        <div class="row" style="display:flex;gap:8px">
          <button class="btn btn--secondary" data-assign="${b.id}">Assign</button>
          <button class="btn" data-move="${b.id}">Move →</button>
        </div>
      `;
      wrap.appendChild(card);
    });
    grid.appendChild(column);
  });
}
renderBundles();

$('#assignBundleBtn').addEventListener('click', openAssignModal);
document.addEventListener('click', (e)=>{
  const move = e.target.closest('[data-move]');
  if (move){
    const id = move.dataset.move;
    const idx = bundles.findIndex(b => b.id === id);
    const order = ["Pending","In Progress","QA","Completed"];
    const next = order.indexOf(bundles[idx].status) + 1;
    bundles[idx].status = order[Math.min(next, order.length - 1)];
    renderBundles();
    renderKPIs();
  }
});

// ---------- File Uploads ----------
function hookupUpload(areaSel, inputSel, statusSel){
  const area = $(areaSel), input = $(inputSel), status = $(statusSel);
  area.addEventListener('click', ()=> input.click());
  ['dragenter','dragover'].forEach(ev=> area.addEventListener(ev, e=>{ e.preventDefault(); area.style.background='#0e1731'; }));
  ['dragleave','drop'].forEach(ev=> area.addEventListener(ev, e=>{ e.preventDefault(); area.style.background=''; }));
  area.addEventListener('drop', (e)=>{ e.preventDefault(); input.files = e.dataTransfer.files; status.textContent = `Selected: ${[...input.files].map(f=>f.name).join(', ')}`; });
  input.addEventListener('change', ()=>{ status.textContent = `Selected: ${[...input.files].map(f=>f.name).join(', ')}`; });
}
hookupUpload('#obUploadArea', '#obFileInput', '#obUploadStatus');
hookupUpload('#poUploadArea', '#poFileInput', '#poUploadStatus');

// ---------- ESP32 Scanner Demo ----------
const scanStatus = $('#scanStatus');
$('#simulateScanBtn').addEventListener('click', ()=>{
  scanStatus.textContent = 'Scanning...';
  setTimeout(()=>{
    const w = workers[rand(0,workers.length-1)];
    pushScanLog(`Scanned token ${w.token} (${w.name})`);
    scanStatus.textContent = 'Ready to scan...';
  }, 700);
});
$('#resetScannerBtn').addEventListener('click', ()=> $('#scanLog').innerHTML='');

function pushScanLog(text){
  const row = document.createElement('div');
  row.className = 'earning-row';
  row.innerHTML = `<span>🟢 ${text}</span><span class="muted">${nowTime()}</span>`;
  $('#scanLog').prepend(row);
  // keep only 12
  const max = 12;
  while ($('#scanLog').children.length > max) $('#scanLog').removeChild($('#scanLog').lastChild);
}

// ---------- Reports ----------
const prodCtx = document.getElementById('productivityChart');
const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const pieces = months.map(()=> rand(250,950));
const minutes = months.map(()=> rand(600,1600));
new Chart(prodCtx, {
  type: 'line',
  data: {
    labels: months,
    datasets: [
      { label: 'Pieces', data: pieces, tension: .35, fill: true, borderColor: '#7c5cff', backgroundColor: 'rgba(124,92,255,.18)' },
      { label: 'Minutes', data: minutes, tension: .35, borderColor: '#22c55e' }
    ]
  },
  options: {
    scales: { x: { ticks: { color: '#cfe1ff' }}, y: { ticks: { color: '#cfe1ff' }} },
    plugins: { legend: { labels: { color: '#cfe1ff' } } }
  }
});

function renderEarnings(){
  const wrap = $('#earningsSummary'); wrap.innerHTML = '';
  const rows = departments.slice(0,6).map(d => [d, currency(rand(12000, 42000))]);
  rows.forEach(([label,val])=>{
    const r = document.createElement('div');
    r.className = 'earning-row';
    r.innerHTML = `<span>${label}</span><strong>${val}</strong>`;
    wrap.appendChild(r);
  });
}
renderEarnings();

$('#exportReportBtn').addEventListener('click', ()=>{
  const rows = [['Department','Earnings'], ...departments.map(d=>[d, rand(20000,50000)])];
  const csv = rows.map(r=>r.join(',')).join('\n');
  const blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = 'earnings_report.csv'; a.click();
  URL.revokeObjectURL(url);
});

// ---------- Modals: Add Worker ----------
const addWorkerModal = $('#addWorkerModal');
$('#addWorkerBtn').addEventListener('click', ()=> addWorkerModal.classList.remove('hidden'));
$('#closeAddWorkerModal').addEventListener('click', ()=> addWorkerModal.classList.add('hidden'));
$('#cancelAddWorker').addEventListener('click', ()=> addWorkerModal.classList.add('hidden'));

$('#addWorkerForm').addEventListener('submit', (e)=>{
  e.preventDefault();
  const name = $('#workerName').value.trim();
  const token = $('#workerToken').value.trim();
  const department = $('#workerDepartment').value;
  const line = $('#workerLine').value;
  if (!name || !token || !department || !line) return;
  workers.push({ name, token, department, line, status: 'Active' });
  renderWorkersTable();
  addWorkerModal.classList.add('hidden');
  e.target.reset();
});

// ---------- Modal: QR Code (simple canvas pattern) ----------
const qrModal = $('#qrCodeModal');
const qrContainer = $('#qrCodeContainer');
const qrInfo = $('#qrWorkerInfo');

document.addEventListener('click', (e)=>{
  const btn = e.target.closest('[data-qr]');
  if (!btn) return;
  const name = btn.dataset.name; const token = btn.dataset.qr;
  showQR(name, token);
});

function showQR(name, token){
  qrModal.classList.remove('hidden');
  qrInfo.textContent = `${name} • ${token}`;
  qrContainer.innerHTML = '';
  const c = document.createElement('canvas');
  c.width = 200; c.height = 200;
  const ctx = c.getContext('2d');
  ctx.fillStyle = '#fff'; ctx.fillRect(0,0,200,200);
  const seed = [...token].reduce((a,ch)=>a + ch.charCodeAt(0), 0);
  for(let y=0;y<21;y++) for(let x=0;x<21;x++){
    const on = ((x*31 + y*17 + seed) % 7) < 3;
    if (on) { ctx.fillStyle = '#0b1120'; ctx.fillRect(x*8+6, y*8+6, 6,6); }
  }
  qrContainer.appendChild(c);
}
$('#closeQrModal').addEventListener('click', ()=> qrModal.classList.add('hidden'));
$('#downloadQrBtn').addEventListener('click', ()=>{
  const canvas = qrContainer.querySelector('canvas');
  if (!canvas) return;
  const a = document.createElement('a');
  a.href = canvas.toDataURL('image/png');
  a.download = `${qrInfo.textContent.replace(/\s+•\s+/,'_')}.png`;
  a.click();
});

// ---------- Modal: Assign Bundle ----------
const assignModal = $('#assignBundleModal');
$('#assignBundleBtn').addEventListener('click', openAssignModal);
$('#closeAssignModal').addEventListener('click', ()=> assignModal.classList.add('hidden'));
$('#cancelAssign').addEventListener('click', ()=> assignModal.classList.add('hidden'));

function openAssignModal(){
  assignModal.classList.remove('hidden');
  // populate selects
  const bundleSel = $('#bundleSelect'); const workerSel = $('#workerSelect'); const opSel = $('#operationSelect');
  bundleSel.innerHTML = bundles.filter(b=>b.status!=='Completed').map(b=>`<option value="${b.id}">#${b.id} (${b.status})</option>`).join('');
  workerSel.innerHTML = workers.map(w=>`<option value="${w.token}">${w.name} (${w.token})</option>`).join('');
  opSel.innerHTML = operations.slice(0,25).map(o=>`<option value="${o.opNo}">${o.opNo} — ${o.machine}</option>`).join('');
}

$('#assignBundleForm').addEventListener('submit', (e)=>{
  e.preventDefault();
  const bundleId = $('#bundleSelect').value;
  const workerToken = $('#workerSelect').value;
  const opNo = $('#operationSelect').value;
  // fake update
  const idx = bundles.findIndex(b=>b.id===bundleId);
  if (idx > -1) bundles[idx].status = 'In Progress';
  renderBundles();
  assignModal.classList.add('hidden');
});

// ---------- Loading Overlay demo ----------
const overlay = $('#loadingOverlay');
function showLoading(ms=800){
  overlay.classList.remove('hidden');
  setTimeout(()=> overlay.classList.add('hidden'), ms);
}
document.addEventListener('submit', (e)=>{
  if (e.target.closest('#addWorkerForm') || e.target.closest('#assignBundleForm')) showLoading(600);
});
