async function refreshLogs(){
  try{
    const res = await fetch('/api/logs');
    const data = await res.json();
    const tbody = document.querySelector('#recent-table tbody');
    if(!tbody) return;
    tbody.innerHTML = data.map(r => `<tr>
      <td>${r.timestamp}</td>
      <td>${r.worker}</td>
      <td>${r.bundle}</td>
      <td>${r.operation}</td>
      <td></td>
    </tr>`).join('');
  }catch(e){ /* no-op */ }
}
setInterval(refreshLogs, 10000);
